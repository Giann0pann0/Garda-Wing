"""Punto d'ingresso.

    python3 -m gardawind                 avvia il cruscotto
    python3 -m gardawind --backfill      scarica gli archivi storici e addestra
    python3 -m gardawind --train         riaddestra dai dati gia' scaricati
    python3 -m gardawind --verify        rimisura la skill dei singoli modelli
    python3 -m gardawind --report        stampa lo stato senza avviare nulla
    python3 -m gardawind --validate      tabella per spot x regime x scadenza
    python3 -m gardawind --bands         confronta i tagli di fascia di scadenza
    python3 -m gardawind --direzioni     da dove viene il vento, per settore
    python3 -m gardawind --raffiche      media, raffica ricorrente, raffica massima
    python3 -m gardawind --orari         quando entra il vento: regime e planata
    python3 -m gardawind --poll-once     legge le centraline una volta ed esce
    python3 -m gardawind --live-json F   legge le centraline e scrive F (solo osservato)
    python3 -m gardawind --addicted [N]  legge addicted-sports (N giorni indietro)
    python3 -m gardawind --nowcast-validazione  valida persistenza intraday senza attivarla
    python3 -m gardawind --analoghi-validazione  valida la forma da analoghi storici
    python3 -m gardawind --export DIR    scrive il cruscotto come sito statico
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser

from . import analogs, config, engine, store, web
from .util import local_day, local_hour, parse_dt_any, to_local


def cmd_report():
    print("Database: %s" % store.db_path())
    for station in sorted({s["station"] for s in config.SPOTS.values()}):
        st = store.obs_stats(station)
        print("  centralina %-10s  %7d campioni  %6d ore  %s -> %s  (%d giorni archivio)"
              % (station, st["samples"], st["hours"],
                 (st["hour_from"] or "-")[:10], (st["hour_to"] or "-")[:10], st["days"]))
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        if not L:
            print("  modello    %-22s non addestrato" % name)
            continue
        m = L["metrics"]
        print("  modello    %-22s livello=%-8s n=%-5s MAE=%s (rif %s)  Brier=%s (clim %s)  usabile=%s"
              % (name, m.get("tier"), m.get("n"),
                 _f(m.get("mae")), _f(m.get("mae_base")),
                 _f(m.get("brier"), 4), _f(m.get("brier_base"), 4), m.get("usable")))
    for e in store.recent_events(8):
        print("  log  %s  %-7s %-22s %s" % (e["ts"][:16], e["level"], e["scope"], e["message"]))


def _f(v, d=2):
    return ("%.*f" % (d, v)) if isinstance(v, (int, float)) else "-"


def _ic(g):
    """Guadagno con intervallo, e un segno che dice se e' distinguibile da zero."""
    if not g or g.get("punto") is None:
        return "-"
    lo, hi = g.get("ic_lo"), g.get("ic_hi")
    if lo is None or hi is None:
        return "%+.0f%%" % g["punto"]
    return "%+.0f%% [%+.0f,%+.0f]%s" % (g["punto"], lo, hi,
                                       "" if g.get("significativo") else " ns")


def cmd_validate(spots=None, bands=None, sector=True, out_json=None,
                 periodo_comune=False):
    """La tabella per spot x regime x scadenza, con tutto cio' che la qualifica.

    Non stampa un punteggio unico. Un punteggio unico nasconde esattamente
    l'informazione che serve: dove il modello e' forte e dove i dati non
    bastano ancora. Ogni riga porta quanti giorni di prova ha dietro, il
    confronto con i riferimenti banali e l'intervallo di confidenza del
    guadagno; le righe marcate "ns" hanno un intervallo che attraversa lo zero,
    cioe' un miglioramento che non si distingue dal rumore.
    """
    from . import engine, regimes, validate as V
    names = spots or list(config.SPOT_ORDER)
    report = {"versione": config.APP_VERSION, "spot": {}}

    for spot_name in names:
        spot = config.SPOTS[spot_name]
        print("\n" + "=" * 78)
        print("%s  (%s, finestra %02d-%02d locali, soglia %g kn, asse modelli %g, "
              "asse centralina %g)"
              % (spot_name, spot["regime"], spot["window"][0], spot["window"][1],
                 spot["min_kn"], spot["axis"], spot.get("axis_obs", spot["axis"])))
        print("=" * 78)

        by_lead = engine.samples_by_lead(spot_name)
        if not by_lead:
            print("  nessun campione: archivi non ancora scaricati")
            report["spot"][spot_name] = {"stato": "nessun campione"}
            continue

        if periodo_comune and len(by_lead) > 1:
            # Ogni scadenza sugli STESSI giorni. Senza questo, la scadenza zero
            # arriva dall'archivio ordinario (dal 2021) e le altre da quello
            # delle run precedenti (dal 2024): i primi fold, cioe' il periodo in
            # cui il modello ha meno dati e sbaglia di piu', finiscono tutti
            # nella riga di oggi e in nessun'altra. Confrontare le righe fra
            # loro, in quel caso, e' confrontare periodi diversi.
            comune = None
            for rows in by_lead.values():
                giorni = {r["day"] for r in rows}
                comune = giorni if comune is None else (comune & giorni)
            if comune and len(comune) >= 200:
                by_lead = {l: [r for r in rows if r["day"] in comune]
                           for l, rows in by_lead.items()}
                print("  PERIODO COMUNE a tutte le scadenze: %s -> %s (%d giorni)"
                      % (min(comune), max(comune), len(comune)))
            else:
                print("  periodo comune troppo corto (%d giorni): uso tutto"
                      % (len(comune or [])))

        print("  campioni per scadenza: " + ", ".join(
            "D+%d=%d" % (l, len(by_lead[l])) for l in sorted(by_lead)))

        entry = {"campioni_per_scadenza": {l: len(v) for l, v in by_lead.items()},
                 "fasce": [], "per_scadenza": []}

        print("\n  fascia   scad.  n_addestr  n_prova  gg_prova  "
              "Brier (clim)        MAE (grezzo)       validata")
        print("  " + "-" * 74)
        for band_name, (a, b) in (bands or config.LEAD_BANDS):
            pooled = []
            for lead in range(a, b + 1):
                pooled.extend(by_lead.get(lead) or [])
            if len(pooled) < 120:
                print("  %-8s D+%d-%d  %s" % (band_name, a, b,
                                              "dati insufficienti (%d campioni)" % len(pooled)))
                entry["fasce"].append({"band": band_name, "stato": "dati insufficienti",
                                       "n": len(pooled)})
                continue
            r = V.fit_band(spot_name, pooled, "surface", band_name)
            if not r:
                print("  %-8s D+%d-%d  periodo troppo corto per il forward chaining"
                      % (band_name, a, b))
                entry["fasce"].append({"band": band_name, "stato": "periodo corto"})
                continue
            p, i = r["prob"] or {}, r["intensity"] or {}
            if not r["n_test"]:
                # Il forward chaining e' andato a vuoto: nessuna giornata
                # predetta fuori campione. Dirlo, invece di riempire la riga di
                # trattini che si leggono come "zero".
                print("  %-8s D+%d-%d  %9d  non valutabile: nessuna giornata di "
                      "prova fuori campione" % (band_name, a, b, r["n"]))
                entry["fasce"].append({"band": band_name, "stato": "non valutabile",
                                       "n": r["n"]})
                continue
            print("  %-8s D+%d-%d  %9d  %7d  %8d  %s (%s)    %s (%s)   %s"
                  % (band_name, a, b, r["n"], r["n_test"], r["n_test_days"],
                     _f(p.get("brier"), 3), _f(p.get("brier_base"), 3),
                     _f(i.get("mae")), _f(i.get("mae_raw")),
                     "SI" if r["validated"] else "no"))
            print("           guadagno probabilita' %s   intensita' %s"
                  % (_ic(r["gain_prob"]), _ic(r["gain_int"])))
            if p.get("calibration_error") is not None:
                print("           errore di calibrazione %.3f, %d blocchi isotonici, "
                      "%d fold, blocco cieco %d giorni"
                      % (p["calibration_error"], r["calibration_blocks"],
                         r["n_folds"], r["n_blind_days"]))
            if r["timing"]:
                t = r["timing"]
                print("           orario: MAE %.0f min (grezzo %s), entro 30' nel %.0f%% dei casi"
                      % (t["mae_min"], _f(t.get("mae_raw_min"), 0), 100 * t["p30"]))
            entry["fasce"].append({k: v for k, v in r.items() if k != "payload"})

            for lead in sorted(r["per_lead"]):
                e = r["per_lead"][lead]
                pp, ii = e["prob"] or {}, e["intensity"] or {}
                print("      D+%d   gg=%-4d  Brier %s (clim %s)  MAE %s (grezzo %s)  "
                      "bias %s  %s"
                      % (lead, e["n_test_days"],
                         _f(pp.get("brier"), 3), _f(pp.get("brier_base"), 3),
                         _f(ii.get("mae")), _f(ii.get("mae_raw")),
                         _f(ii.get("bias")), _ic(e.get("gain_int"))))
                if e.get("banda"):
                    print("            banda empirica dai residui: %s / %s kn"
                          % (_f(e["banda"]["q10"], 1), _f(e["banda"]["q90"], 1)))
                if e.get("timing"):
                    print("            orario: MAE %.0f min, bias %+.0f min"
                          % (e["timing"]["mae_min"], e["timing"]["bias_min"]))
                entry["per_scadenza"].append(e)

        if sector and spot["target"] == "hourly":
            cls = regimes.classify_days(store.obs_hours(spot["station"]),
                                        window=spot["window"],
                                        settori=regimes.settori_per_spot(spot))
            st = regimes.sector_study(cls, spot.get("axis_obs", spot["axis"]))
            if st:
                print("\n  settore direzionale sui %d giorni ventosi osservati:" % st["n"])
                print("    ampiezza  giorni dentro  quota  picco dentro  picco fuori  "
                      "classe dominante  purezza")
                for row in st["soglie"]:
                    print("    +/-%-5.0f  %13d  %4.0f%%  %12s  %11s  %-16s  %5.0f%%"
                          % (row["deg"], row["n_dentro"], 100 * row["quota_dentro"],
                             _f(row["picco_mediano_dentro"], 1),
                             _f(row["picco_mediano_fuori"], 1),
                             row["classe_dominante"], 100 * row["purezza"]))
                if st["per_stagione"]:
                    print("    per stagione (scarto mediano dall'asse): " + ", ".join(
                        "%s %.0f gradi su %d gg" % (k, v["scarto_mediano"], v["n"])
                        for k, v in sorted(st["per_stagione"].items())))
                entry["settore"] = st
                entry["regimi"] = regimes.summary(cls)
                print("\n  regimi osservati: " + ", ".join(
                    "%s %d (%.0f%%)" % (x["etichetta"], x["n"], 100 * x["quota"])
                    for x in entry["regimi"][:6]))

        report["spot"][spot_name] = entry

    print("\n" + "=" * 78)
    print("Righe marcate 'ns': il guadagno non si distingue dal rumore.")
    print("Fasce 'no' nella colonna validata: NON usare quei numeri come promessa.")
    if out_json:
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, default=str, indent=1)
        print("Dettaglio completo in %s" % out_json)
    return report


def cmd_raffiche(spot_name=None, soglie=(14, 16, 18, 20, 22)):
    """Analisi descrittiva. Nessuna soglia decisa qui.

    Due livelli, tenuti SEPARATI, ognuno col proprio numero di giornate:

      il vento medio, su tutto lo storico disponibile - a Torbole quattordici
      anni - perche' e' li' che si imparano stagionalita', orari, durata e
      differenze fra Ora e Peler;

      la raffica, solo sulle giornate che ce l'hanno davvero.

    La prima versione di questo comando scartava ogni campione senza raffica, e
    siccome l'archivio storico di Torbole non contiene la raffica, "analisi di
    quattordici anni" diventava in silenzio "analisi di nove giorni". La
    raffica e' un livello che si aggiunge man mano che la raccogliamo, non un
    filtro d'ingresso che rende inutilizzabile tutto il resto.

    Niente costanti di cadenza: i minuti si misurano in minuti, la cadenza si
    deduce dai dati, e la finestra della mediana mobile si adatta.
    """
    from gardawind.util import (FINESTRA_RICORRENTE_MIN, angle_diff,
                                covered_minutes, gust_level, median,
                                merge_by_instant, sampling_cadence,
                                sustained_onset, time_above, window_estimable)

    spots = [spot_name] if spot_name else [
        n for n in config.SPOT_ORDER if config.SPOTS[n]["target"] == "hourly"]
    # Ogni statistica ha il suo minimo, perche' non sono ugualmente fragili:
    # una mediana su dodici numeri e' informativa, un q99 su dodici numeri e'
    # il massimo di dodici valori con un'etichetta che promette una coda al
    # centesimo. Un'unica soglia a trenta - come nella prima versione - e'
    # onesta sui quantili e inutilmente muta sulle mediane, e infatti sul
    # rapporto vero cancellava righe che avevano qualcosa da dire.
    MIN_MEDIANA = 10
    MIN_Q75 = 20
    MIN_QUANTILI = 30
    MIN_COPERTURA_MIN = 120.0   # due ore dentro la finestra del regime

    def q(xs, p):
        y = sorted(xs)
        return y[min(len(y) - 1, max(0, int(p * (len(y) - 1))))] if y else float("nan")

    def riga_q(etichetta, dati):
        n = len(dati)
        if n >= MIN_QUANTILI:
            return ("  %-22s %7.1f %7.1f %7.1f %7.1f %7.1f"
                    % (etichetta, q(dati, .10), q(dati, .50), q(dati, .75),
                       q(dati, .90), q(dati, .99)))
        if n >= MIN_MEDIANA:
            return ("  %-22s %7s %7.1f %7s %7s %7s   (%d giornate: solo mediana)"
                    % (etichetta, "-", q(dati, .50), "-", "-", "-", n))
        return ("  %-22s   %d giornate: troppe poche anche per una mediana"
                % (etichetta, n))

    for name in spots:
        spot = config.SPOTS[name]
        station = spot["station"]
        h0, h1 = spot["window"]
        print("")
        print("=" * 74)
        print("  %s  -  finestra %02d:00-%02d:00  -  centralina %s"
              % (name, h0, h1 + 1, station))
        print("=" * 74)

        # La chiave dei campioni e' (stazione, istante, FONTE): lo stesso
        # istante puo' arrivare due volte, dall'archivio storico e dal canale
        # realtime, ed e' esattamente cio' che succede sulle giornate recenti -
        # l'archivio senza raffica, il realtime con la raffica. I due vanno
        # UNITI tenendo il valore presente, non accodati: due righe sullo
        # stesso minuto falsano la cadenza (un intervallo di zero minuti), la
        # copertura e le durate, e il campione senza raffica butterebbe via
        # quello con la raffica.
        pronti = []
        etichetta = {}
        n_camp = n_gust = 0
        for s in store.samples_since(station, "0000"):
            dt_ = parse_dt_any(s["ts"])
            if dt_ is None:
                continue
            r = dict(s)
            r["_key"] = dt_.timestamp()
            pronti.append(r)
            loc = to_local(dt_)
            etichetta[r["_key"]] = (local_day(dt_),
                                    loc.hour * 60.0 + loc.minute)
            n_camp += 1
            if s["gust_kn"] is not None:
                n_gust += 1
        per_istante, conflitti = merge_by_instant(pronti)

        per_giorno = {}
        tempi = []
        for key, u in per_istante.items():
            if u["wind"] is None:
                continue
            giorno, minuti = etichetta[key]
            per_giorno.setdefault(giorno, []).append(
                (minuti, u["wind"], u["gust"], u["dir"]))
            tempi.append(key / 60.0)
        tempi.sort()
        n_unici = len(per_istante)

        if not per_giorno:
            print("  nessun campione per questa centralina.")
            continue

        cadenza = sampling_cadence(tempi) or 0.0
        gg_con_raffica = sum(1 for v in per_giorno.values()
                             if any(g is not None for _m, _w, g, _d in v))
        print("")
        print("  archivio: %d campioni su %d giornate, cadenza tipica %g min"
              % (n_camp, len(per_giorno), cadenza))
        if n_unici < n_camp:
            print("  %d istanti distinti: %d campioni erano lo stesso istante da"
                  % (n_unici, n_camp - n_unici))
            print("  due fonti (archivio e realtime), uniti campo per campo")
        if conflitti:
            peggiore = max(conflitti, key=lambda c: c["differenza"])
            print("  ATTENZIONE: %d conflitti fra fonti sullo stesso istante."
                  % len(conflitti))
            print("  Il maggiore: %s %.1f (%s) contro %.1f (%s). Tenuto il"
                  % (peggiore["campo"], peggiore["tenuto"],
                     peggiore["fonte_tenuta"], peggiore["scartato"],
                     peggiore["fonte_scartata"]))
            print("  primo per la regola dichiarata, non scelto a caso.")
        elif n_unici < n_camp:
            print("  nessun conflitto: le due fonti concordavano")
        print("  raffica presente su %d campioni (%.1f%%) e %d giornate"
              % (n_gust, 100.0 * n_gust / n_camp, gg_con_raffica))
        # La stimabilita' della ricorrente a 30' NON e' una proprieta' della
        # centralina: e' una proprieta' del dato di quella giornata. L'archivio
        # di Malcesine cambia cadenza nel tempo, quindi alcune giornate la
        # sostengono e altre no. Deciderlo una volta per stazione, sulla
        # cadenza mediana, buttava via le giornate buone di una stazione rada -
        # o, peggio, contava come "zero" le giornate rade di una stazione
        # fitta, che si legge "non c'era vento".
        print("  la stimabilita' della ricorrente 30' e' valutata PER GIORNATA")
        if gg_con_raffica == 0:
            print("  -> raffica storica NON disponibile per questa centralina.")
        elif gg_con_raffica < 0.5 * len(per_giorno):
            print("  -> raffica storica disponibile solo di recente: il secondo")
            print("     blocco parla di %d giornate, non di %d."
                  % (gg_con_raffica, len(per_giorno)))

        # ---- livello 1: il vento medio, su TUTTO lo storico ----
        # Il giudizio di ogni giornata NON si rifa' qui: lo fa la logica pura,
        # orari.giudica_giornata(), che e' l'unico posto dove sono definiti il
        # settore, la copertura minima e "sopra soglia". Due copie della stessa
        # definizione sono una definizione che prima o poi divergera', e la
        # differenza si scoprirebbe leggendo due tabelle che non tornano.
        from gardawind import orari as O
        asse_obs = spot.get("axis_obs", spot["axis"])
        settore = config.REGIME_SECTOR_DEG
        LETTURE = ("vento", "regime")
        SOGLIE_W = (spot["min_kn"], spot["planing_kn"])
        medie = {l: [] for l in LETTURE}
        durate_m = {(l, t): [] for l in LETTURE for t in SOGLIE_W}
        gg_validi = gg_dir_ignota = 0
        for day in sorted(per_giorno):
            righe = [(m, w, d) for m, w, _g, d in per_giorno[day]
                     if h0 * 60 <= m <= (h1 + 1) * 60]
            G = O.giudica_giornata(righe, asse_obs, settore,
                                   SOGLIE_W[0], SOGLIE_W[1],
                                   min_copertura_min=MIN_COPERTURA_MIN,
                                   date=day)
            if not G["estimable"]:
                continue
            gg_validi += 1
            if (G["dir_unknown_frac"] or 0.0) > 0.2:
                gg_dir_ignota += 1
            if G["peak_wind"] is not None:
                medie["vento"].append(G["peak_wind"])
            if G["peak_regime"] is not None:
                medie["regime"].append(G["peak_regime"])
            # I nomi del contratto: "_wind" e' la lettura senza direzione.
            durate_m[("vento", SOGLIE_W[0])].append(
                G["regime_duration_wind_min"] or 0.0)
            durate_m[("regime", SOGLIE_W[0])].append(
                G["regime_duration_min"] or 0.0)
            durate_m[("vento", SOGLIE_W[1])].append(
                G["planing_duration_wind_min"] or 0.0)
            durate_m[("regime", SOGLIE_W[1])].append(
                G["planing_duration_min"] or 0.0)

        print("")
        print("  VENTO MEDIO  -  %d giornate con almeno due ore di copertura"
              % gg_validi)
        if gg_dir_ignota:
            print("  (%d con direzione ignota su oltre un quinto dei campioni:"
                  % gg_dir_ignota)
            print("   in quelle la lettura REGIME e' per forza piu' bassa)")
        print("  %-22s %7s %7s %7s %7s %7s"
              % ("picco del giorno", "q10", "mediana", "q75", "q90", "q99"))
        print(riga_q("vento, ogni direzione", medie["vento"]))
        print(riga_q("regime (nel settore)", medie["regime"]))
        # Due letture affiancate, sempre, perche' la prima non diventi la
        # seconda: "il vento supera i 14 nodi nel 63% dei pomeriggi" e "l'Ora
        # e' utile nel 63% dei pomeriggi" sono frasi diverse, e la differenza
        # fra le due colonne E' quanto conta la direzione.
        print("")
        print("  %-18s %22s   %22s"
              % ("", "VENTO (intensita')", "REGIME (+ direzione)"))
        print("  %-18s %8s %13s   %8s %13s"
              % ("soglia", "giornate", "durata med.", "giornate", "durata med."))
        for t in SOGLIE_W:
            etichetta = ("regime %g kn" % t if abs(t - SOGLIE_W[0]) < 1e-9
                         else "planata %g kn" % t)
            celle = []
            for l in LETTURE:
                d = [x for x in durate_m[(l, t)] if x > 0]
                if len(d) < MIN_MEDIANA:
                    celle.append("%4d %3.0f%% %13s"
                                 % (len(d), 100.0 * len(d) / max(1, gg_validi), "-"))
                else:
                    celle.append("%4d %3.0f%% %9.0f min"
                                 % (len(d), 100.0 * len(d) / max(1, gg_validi),
                                    median(d) or 0))
            print("  %-18s %s   %s" % (etichetta, celle[0], celle[1]))
        dv = len([x for x in durate_m[("vento", SOGLIE_W[0])] if x > 0])
        dr = len([x for x in durate_m[("regime", SOGLIE_W[0])] if x > 0])
        if dv:
            print("  La direzione taglia %d giornate su %d (%.0f%%): il vento"
                  % (dv - dr, dv, 100.0 * (dv - dr) / dv))
            print("  bastava ma non era %s. L'orario di INGRESSO, con le stesse"
                  % ("l'Ora" if spot["regime"] == "ORA" else "il Peler"))
            print("  due letture, sta in --orari.")

        # ---- livello 2: la raffica. Una tabella PER METRICA, mai mescolate ----
        # Ogni giornata finisce nel secchio della metrica che il suo dato
        # sostiene: 30' dove la cadenza lo permette, 90' altrove.
        METRICHE = ((FINESTRA_RICORRENTE_MIN, "raffica ricorrente 30'"),
                    (90.0, "raffica sostenuta 90'"))
        secchi = {nome: {"ric": [], "max": [], "rap": [], "gg": 0,
                         "durate": {t: [] for t in soglie},
                         "ingressi": {t: [] for t in soglie}}
                  for _w, nome in METRICHE}
        gg_senza_raffica = 0
        for day in sorted(per_giorno):
            righe = sorted(per_giorno[day], key=lambda r: r[0])
            if not any(g is not None for _m, _w, g, _d in righe):
                continue
            cad_g = sampling_cadence([m for m, _w, g, _d in righe
                                      if g is not None]) or cadenza
            fin, nome = next(
                ((w, n) for w, n in METRICHE if window_estimable(cad_g, w)),
                (None, None))
            if fin is None:
                gg_senza_raffica += 1
                continue
            serie_ric = gust_level([(m, g) for m, _w, g, _d in righe],
                                   fin, centered=True, cadence_min=cad_g)
            sel = [(m, w, g, r) for (m, w, g, _d), (_m2, r)
                   in zip(righe, serie_ric)
                   if h0 * 60 <= m <= (h1 + 1) * 60]
            if covered_minutes([m for m, _w, _g, _r in sel],
                               cad_g) < MIN_COPERTURA_MIN:
                continue
            rs = [r for _m, _w, _g, r in sel if r is not None]
            if not rs:
                gg_senza_raffica += 1
                continue
            B = secchi[nome]
            B["gg"] += 1
            gs = [g for _m, _w, g, _r in sel if g is not None]
            ws = [w for _m, w, _g, _r in sel if w is not None]
            if gs:
                B["max"].append(max(gs))
            B["ric"].append(max(rs))
            if ws and max(ws) > 0.5:
                B["rap"].append(max(rs) / max(ws))
            sr = [(m, r) for m, _w, _g, r in sel if r is not None]
            for t in soglie:
                B["durate"][t].append(time_above(sr, float(t), cad_g))
                ing = sustained_onset(sr, float(t),
                                      persist_min=O.PERSISTENZA_MIN,
                                      cadence_min=cad_g)
                if ing is not None:
                    B["ingressi"][t].append(ing)

        if not any(secchi[n]["gg"] for _w, n in METRICHE):
            print("")
            print("  RAFFICA  -  non stimabile su questa centralina.")
            print("  Non e' vento assente: e' misura assente o troppo rada. Si")
            print("  accumula da qui in avanti, e questo blocco comparira' da solo.")
            continue

        for _fin, nome in METRICHE:
            B = secchi[nome]
            if not B["gg"]:
                continue
            print("")
            print("  RAFFICA  -  %d giornate  -  metrica: %s" % (B["gg"], nome))
            print("  %-22s %7s %7s %7s %7s %7s"
                  % ("picco del giorno", "q10", "mediana", "q75", "q90", "q99"))
            print(riga_q(nome, B["ric"]))
            print(riga_q("raffica massima", B["max"]))
            if len(B["rap"]) >= MIN_QUANTILI:
                print("  rapporto raffica/media      mediana %.2f   q10 %.2f   q90 %.2f"
                      % (q(B["rap"], .5), q(B["rap"], .1), q(B["rap"], .9)))
            elif len(B["rap"]) >= MIN_MEDIANA:
                print("  rapporto raffica/media      mediana %.2f  (%d giornate,"
                      " solo mediana)" % (q(B["rap"], .5), len(B["rap"])))
            elif B["rap"]:
                print("  rapporto raffica/media: %d giornate, troppe poche"
                      % len(B["rap"]))
            print("")
            print("  quanto durano le soglie, su: %s" % nome)
            print("  %6s %9s %11s %12s %12s %14s"
                  % ("soglia", "giornate", "% giornate", "durata med.",
                     "durata q75", "ingresso >=30'"))
            for t in soglie:
                d = [x for x in B["durate"][t] if x > 0]
                perc = 100.0 * len(d) / B["gg"]
                ing = B["ingressi"][t]
                if ing:
                    mm = median(ing) or 0
                    ora = "%02d:%02d" % (int(mm // 60) % 24, int(mm % 60))
                else:
                    ora = "-"
                # La mediana compare da dieci giornate, il q75 da venti:
                # sotto, la cella resta vuota invece di contenere un numero
                # che finge una distribuzione.
                if len(d) < MIN_MEDIANA:
                    print("  %6d %9d %10.0f%%   %d giornate: troppe poche"
                          % (t, len(d), perc, len(d)))
                else:
                    cella_q75 = (("%8.0f min" % q(d, .75)) if len(d) >= MIN_Q75
                                 else "%12s" % "-")
                    print("  %6d %9d %10.0f%% %8.0f min %s %14s"
                          % (t, len(d), perc, median(d) or 0, cella_q75, ora))
        if gg_senza_raffica:
            print("")
            print("  %d giornate con raffica ma troppo rada per qualunque"
                  % gg_senza_raffica)
            print("  finestra: escluse, non contate come zero.")
        print("")
        print("  Le soglie qui NON sono decise: sono candidate. La colonna che")
        print("  conta e' la durata - una soglia superata per venti minuti e'")
        print("  un colpo di vento, non una sessione.")
        sys.stdout.flush()


# I codici di "reason" tradotti in italiano. La tabella sta qui, nel
# rendering, e non nella logica: cambiare una parola non deve poter toccare
# un controllo scientifico, e aggiungere un codice deve costringere a
# passare da gardawind/orari.py.
MOTIVI = {
    "ok": "regime entrato, orario misurato",
    "left_censored": "regime gia' presente all'inizio della finestra: "
                     "orario non osservabile",
    "no_data": "nessun campione con vento nella finestra",
    "insufficient_coverage": "copertura oraria insufficiente",
    "gap_too_large": "entrato, ma il passaggio cade in un buco: orario = limite",
    "direction_outside_sector": "vento sufficiente, direzione fuori settore",
    "threshold_not_sustained": "soglia superata, ma non abbastanza a lungo",
    "no_regime": "soglia mai superata",
}

MESI_BREVI = ["gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic"]

# Perche' due massimi locali non sono stati dichiarati due modi. Come per i
# codici delle giornate: la logica usa codici, il rendering le parole.
MOTIVI_MODI = {
    "valle_alta": "con la valle alta quanto il picco",
    "troppo_vicini": "con i due picchi appiccicati",
    "pochi_dati": "con troppe poche giornate per una forma",
}


def _hhmm(minuti):
    return "%02d:%02d" % (int(minuti // 60) % 24, int(minuti % 60))


def cmd_addicted_audit(stazioni=None, giorni_extra=()):
    """Cosa contiene davvero l'archivio addicted, stazione per stazione.

    Non ingerisce niente: scarica, salva il grezzo separato per stazione, e
    dichiara i fatti. La decisione di usare una di queste stazioni viene dopo
    aver letto questa tabella.
    """
    from gardawind.sources import addicted_audit as A

    slugs = list(stazioni) if stazioni else list(A.SLUG_STAZIONI)
    print("")
    print("=" * 78)
    print("  ADDICTED-SPORTS  -  AUDIT DELL'ARCHIVIO")
    print("  canale: <pagina>?json=wind&from=YYYY-MM-DD   parser %s"
          % A.PARSER_VERSION)
    print("  il grezzo va in %s/<stazione>/"
          % os.path.join(store.support_dir(), "raw", "addicted"))
    print("=" * 78)
    print("")
    print("  Il primo controllo non e' 'quanti giorni ci sono': e' se il server")
    print("  RISPETTA 'from'. Un server che ignora quel parametro e risponde")
    print("  sempre con oggi farebbe concludere 'anni di storico' mentre si")
    print("  rilegge mille volte la stessa giornata - e i dati sembrerebbero")
    print("  buoni, perche' lo sono: sono solo sempre gli stessi.")
    print("")

    riassunti = {}
    for slug in slugs:
        print("  -- %s" % slug)

        def progresso(delta, r, _slug=slug):
            stato = ("serie" if (r["ok"] and r["n_mavg"] > 0)
                     else ("FROM IGNORATO" if r["from_ignorato"]
                           else ("non json" if not r["json"] else "vuota")))
            print("     -%-5d %-12s %s  %s"
                  % (delta, r["giorno"], stato,
                     ("%d slot, %d medie" % (r["n_slot"], r["n_mavg"]))
                     if r["json"] else (r["errore"] or "")[:60]))
            sys.stdout.flush()

        ris, esito_oriz = A.trova_orizzonte(slug, su_progresso=progresso)
        for g in giorni_extra:
            ris[g] = A.audit_giorno(slug, g)
        riassunti[slug] = (A.riassumi(ris), esito_oriz)
        print("")

    print("  " + "=" * 74)
    print("  RIASSUNTO")
    print("  " + "=" * 74)
    print("  %-14s %7s %6s %6s %7s %9s %6s  %s"
          % ("stazione", "provati", "serie", "ignor.", "cadenza",
             "slot/risp.", "buchi", "primo giorno con dati"))
    print("  " + "-" * 78)
    for slug in slugs:
        R, E = riassunti[slug]
        oriz = E["orizzonte"] if isinstance(E, dict) else E
        fondo = isinstance(E, dict) and E.get("fondo_non_raggiunto")
        print("  %-14s %7d %6d %6d %7s %9s %6s  %s%s"
              % (slug, R["n_provati"], R["n_con_serie"], R["n_from_ignorato"],
                 ("%g min" % R["cadenza_mediana"]) if R["cadenza_mediana"] else "-",
                 ("%g" % R["slot_per_giorno"]) if R["slot_per_giorno"] else "-",
                 ("%g" % R["buchi_mediani"]) if R["buchi_mediani"] is not None else "-",
                 ">= " if fondo else "", oriz or "nessun archivio"))
    print("  " + "-" * 78)
    for slug in slugs:
        R, _E = riassunti[slug]
        if R["slot_per_giorno"] and R["cadenza_mediana"]:
            ore = R["slot_per_giorno"] * R["cadenza_mediana"] / 60.0
            print("  %-14s slot per risposta: %g   cadenza: %g min   "
                  "orizzonte risposta: ~%g h"
                  % (slug, R["slot_per_giorno"], R["cadenza_mediana"], ore))
    print("")
    print("  Quei 72 slot NON sono 72 misure in una giornata: sono 72 ORE, cioe'")
    print("  una finestra di tre giorni a cadenza oraria. E' anche il motivo per")
    print("  cui la giornata di ieri ne ha solo 34 piene: il resto della finestra")
    print("  e' futuro. Letto male, farebbe credere che la stazione campioni ogni")
    print("  venti minuti.")
    if any(isinstance(E, dict) and E.get("fondo_non_raggiunto")
           for _R, E in riassunti.values()):
        print("")
        print("  \">=\" vuol dire che la sonda ha esaurito la sua scala senza")
        print("  trovare una giornata vuota: quel giorno NON e' l'inizio")
        print("  dell'archivio, e' il punto piu' profondo che ha guardato.")

    for slug in slugs:
        R, oriz = riassunti[slug]
        print("")
        print("  %s" % slug)
        print("    campi visti:        %s" % (", ".join(R["campi_visti"]) or "-"))
        print("    unita': mavg fino a %s, mmax fino a %s"
              % (R["mavg_max"] if R["mavg_max"] is not None else "-",
                 R["mmax_max"] if R["mmax_max"] is not None else "-"))
        print("      valori di quest'ordine sono NODI. La prova indipendente e'")
        print("      il riquadro 'misurato ora' della pagina, che scrive l'unita':")
        print("      se il canale json fosse in km/h il rapporto starebbe attorno")
        print("      a 1,85 - e --addicted lo controlla a ogni lettura.")
        print("    semantica mavg/mmax:")
        print("      ore con mmax SOTTO mavg: %d" % R["mmax_sotto_mavg"])
        if R["mmax_sotto_mavg"] == 0:
            print("      coerente con 'media dell'ora' e 'massimo dell'ora'.")
            print("      Resta cio' che e': un MASSIMO OSSERVATO NELL'ORA. Non")
            print("      e' la prova di una raffica meteorologica definita, e")
            print("      nel database va tenuto con quel significato.")
        else:
            print("      ATTENZIONE: se il massimo sta sotto la media, i due nomi")
            print("      non vogliono dire quello che sembra. Da chiarire prima")
            print("      di usarli.")
        if R["mae_dichiarato"] is not None:
            print("    errore dichiarato dal sito: %s" % R["mae_dichiarato"])
        if R["errori"]:
            print("    errori incontrati:")
            for e in R["errori"][:4]:
                print("      %s" % e[:110])
    print("")
    print("  Le due Malcesine restano DUE stazioni: qui non vengono unite.")
    print("  Due centraline che misurano lo stesso lago a qualche chilometro")
    print("  di distanza vanno prima confrontate sulle ore in comune, e unirle")
    print("  prima del confronto vorrebbe dire non poterlo piu' fare.")
    print("")
    print("  Nessuna osservazione e' stata scritta nel database: questo comando")
    print("  guarda. L'ingestione e' un'altra decisione, e viene dopo.")
    sys.stdout.flush()


def cmd_addicted_censimento(stazioni=None, massimo=None):
    """Conta Messtage e Windtage senza confondere le due grandezze."""
    from gardawind.sources import addicted_audit as A

    slugs = list(stazioni) if stazioni else list(A.SLUG_STAZIONI)
    print("")
    print("=" * 82)
    print("  ADDICTED-SPORTS  -  CENSIMENTO DELLE GIORNATE SCARICABILI")
    print("  Messtage = giorni con dati; Windtage = >=12 kn per almeno 2 h consecutive")
    print("  un passo ogni %d giorni (una risposta copre %d ore)"
          % (A.PASSO_GIORNI, A.ORE_PER_RISPOSTA))
    print("=" * 82)

    esiti = {}
    for slug in slugs:
        d = A.DICHIARATO.get(slug, {})
        print("")
        print("  -- %s (%s)  snapshot sito: Messtage %s, Windtage %s, dal %s"
              % (slug, d.get("nome", "?"), d.get("messtage", "?"),
                 d.get("windtage", "?"), d.get("dal", "?")))
        sys.stdout.flush()

        def progresso(i, n, giorno, r, _slug=slug):
            if i % 50 == 0 or r["errore"]:
                print("     %5d/%-5d  %s  %s"
                      % (i + 1, n, giorno,
                         (r["errore"] or "")[:50] if r["errore"]
                         else "%d slot, %d medie" % (r["n_slot"], r["n_mavg"])))
                sys.stdout.flush()

        _per_giorno, R = A.censimento(slug, massimo=massimo,
                                      su_progresso=progresso)
        esiti[slug] = R
        print("     richieste %d, dalla cache %d, errori %d"
              % (R["n_richieste"], R["n_dalla_cache"], R["n_errori"]))

    print("")
    print("  " + "=" * 78)
    print("  %-14s %8s %8s %8s %8s %8s  %s"
          % ("stazione", "Messtage", "complete", "mmax", "Windtage", "cop.M", "periodo"))
    print("  " + "-" * 82)
    for slug in slugs:
        R = esiti[slug]
        print("  %-14s %8d %8d %8d %8d %7s  %s -> %s"
              % (slug, R["n_con_dato"], R["n_complete"], R["n_con_mmax"],
                 R["n_windtag"],
                 ("%.0f%%" % (100 * R["quota_messtage"]))
                 if R["quota_messtage"] is not None else "-",
                 R["primo"] or "-", R["ultimo"] or "-"))
    print("  " + "-" * 82)
    print("  cop.M confronta i giorni trovati con i Messtage dello snapshot del sito;")
    print("  NON con i Windtage. Gli snapshot crescono nel tempo, quindi qualche punto")
    print("  percentuale di scarto non e' un errore del parser.")

    for slug in slugs:
        R = esiti[slug]
        if not R["per_anno"]:
            continue
        print("")
        print("  %s, per anno:" % slug)
        print("    anno   con dato  complete  con mmax  Windtage")
        for a in sorted(R["per_anno"]):
            v = R["per_anno"][a]
            print("    %-6s %8d %9d %9d %9d"
                  % (a, v["con_dato"], v["complete"], v["con_mmax"], v["windtag"]))
        if R["windtage_dichiarati"]:
            print("    Windtage ricostruiti %d; snapshot sito %d (%.0f%%)"
                  % (R["n_windtag"], R["windtage_dichiarati"],
                     100 * R["quota_windtage"]))
        if R["mmax_visto"] is not None:
            print("    massimo orario mmax osservato: %.1f kn" % R["mmax_visto"])

    print("")
    print("  Nessuna osservazione scritta nel database: il censimento guarda soltanto.")
    print("  mmax resta 'massimo dell'ora' e NON viene chiamato raffica ricorrente 30'.")
    sys.stdout.flush()


def cmd_addicted_importa(stazioni=None):
    """Ingerisce SOLO i raw gia' scaricati, in una tabella dedicata."""
    from gardawind.sources import addicted_audit as A
    slugs = list(stazioni) if stazioni else list(A.SLUG_STAZIONI)
    print("")
    print("=" * 78)
    print("  ADDICTED-SPORTS  -  IMPORTAZIONE DELLA CACHE")
    print("  nessuna rete; mavg -> media oraria, mmax -> massimo orario")
    print("  destinazione: addicted_hour (separata da gust_rec 30')")
    print("=" * 78)
    totale = 0
    for slug in slugs:
        R = A.importa_cache(slug)
        totale += R["n_salvate"]
        print("  %-14s %7d ore  gruppo %-28s conflitti overlap %d"
              % (slug, R["n_salvate"], R["series_group"], R["conflitti_overlap"]))
    print("  totale: %d ore salvate/aggiornate" % totale)
    print("  Campione e Brenzone condividono lo stesso series_group: non vanno contati")
    print("  come due osservazioni indipendenti finche' la sorgente non cambia.")
    sys.stdout.flush()


def _stampa_copertura(C, cosa="questa analisi"):
    """La copertura del dataset, in testa all'analisi e non in fondo.

    Serve a evitare una frase falsa che nessuno direbbe a voce ma che una
    tabella dice da sola: "abbiamo quattordici anni di planabilita'". I
    quattordici anni sono di vento medio; la raffica ricorrente esiste solo
    dove c'e' la raffica, e nell'archivio storico di Torbole non c'e'.
    """
    def per(x):
        return "-" if x is None else "%.1f%%" % (100.0 * x)

    p0, p1 = C["periodo"]
    print("  COPERTURA DEL DATO  (%s)" % cosa)
    print("    storico mean-only      %5d giornate   %s -> %s   cadenza %s"
          % (C["n_days_total"], p0 or "-", p1 or "-",
             ("%g min" % C["cadenza_mediana"]) if C["cadenza_mediana"] else "-"))
    g0, g1 = C["periodo_gust"]
    print("    con raffica            %5d giornate   %s -> %s   (%s del totale)"
          % (C["n_days_with_gust"], g0 or "-", g1 or "-",
             per(C["quota_with_gust"])))
    r0, r1 = C["periodo_recurrent"]
    print("    ricorrente 30' stimab. %5d giornate   %s -> %s   (%s del totale)"
          % (C["n_days_recurrent_ready"], r0 or "-", r1 or "-",
             per(C["quota_recurrent_ready"])))
    if C["cadenza_raffica_mediana"]:
        print("    cadenza della raffica  %g min  (la ricorrente a 30' chiede "
              "<= 15)" % C["cadenza_raffica_mediana"])
    print("    planabilita': %s" % C["livello_planabilita"])
    if not C["planability_ready"]:
        print("    -> media e direzione si studiano su tutto lo storico;")
        print("       media + raffica ricorrente NO: e' un dataset prospettico,")
        print("       e cresce da adesso. Serve almeno %d giornate."
              % C["soglia_planability"])
    print("")


def _cella(r):
    """Una cella della tabella: giornate, quota censurata, ingresso, disp, durata.

    Tre cose che la cella deve poter dire, e che prima non diceva:

      "c%" e' la quota di giornate in cui il regime era GIA' presente al primo
      campione della finestra. La'  dove e' alta - il Peler d'inverno - l'ora di
      ingresso non e' osservabile, e prima uscivano orari come 03:55 con
      dispersione zero, che nessuno ha misurato;

      un ingresso scritto "<=04:00" e' un LIMITE, non una misura: capita quando
      le censurate sono la maggioranza e la mediana cade dentro di loro;

      una dispersione scritta ">=40" e' un limite inferiore, perche' le
      censurate stanno piu' lontano dalla mediana di quanto si possa misurare.
    """
    q = r.get("quota_censurata")
    cens = "  -" if not q else "%2.0f%%" % (100.0 * q)
    if r["mediana"] is None:
        if r.get("mediana_limite") is not None:
            return "%4d %s %8s %5s %8s" % (
                r["n"], cens, "<=" + _hhmm(r["mediana_limite"]), "-",
                ("%d min" % round(r["durata"])) if r.get("durata") else "-")
        return "%4d %s %8s %5s %8s" % (r["n"], cens, "-", "-", "-")
    disp = "-"
    if r["disp"] is not None:
        disp = ("%s%d" % (">=" if r.get("disp_limite_inferiore") else "+-",
                          round(r["disp"])))
    return "%4d %s %8s %5s %8s" % (
        r["n"], cens, _hhmm(r["mediana"]), disp,
        ("%d min" % round(r["durata"])) if r["durata"] else "-")


def _riga_previsore(O, nome, r, rif):
    """Una riga della tabella di validazione. Nessun calcolo: solo formato."""
    g, lo, hi = r.get("guadagno", (None, None, None))
    guad = "-"
    if nome != rif:
        if g is None:
            guad = "n.d."
        else:
            guad = "%+.0f%% [%+.0f,%+.0f]" % (g, lo if lo is not None else 0.0,
                                              hi if hi is not None else 0.0)
    def mm(x):
        return "-" if x is None else "%.0f" % x
    def pc(x):
        return "-" if x is None else "%.0f%%" % (100.0 * x)
    return ("  %-34s %5d  %5s %6s  %6s   %5s %5s %5s  %s"
            % (r["nome"][:34], r["n"], mm(r["mae"]), mm(r["bias"]),
               mm(r["semiampiezza"]), pc(r["copertura_30"]),
               pc(r["copertura_45"]), pc(r["copertura_60"]), guad))


def _stampa_validazione(O, C):
    """La validazione fuori campione dell'orario. Traduzione, non calcolo.

    Il riferimento e' la climatologia MENSILE osservata. Si misurano anche la
    mediana annuale - per mostrare quanto sarebbe facile "vincere" contro di
    lei - e la climatologia con il bias del mese corretto sul training.

    Le tre porte sono quelle concordate: finestra abbastanza stretta, guadagno
    che regge al bootstrap, nessun bias sistematico di mese o stagione.
    """
    records = list(C["per_giorno"].values())
    previsori = {
        "annuale": O.previsore_climatologico(mensile=False),
        "climatologia+bias": O.previsore_corretto(
            O.previsore_climatologico(), nome="climatologia mensile + bias del mese"),
    }
    for bers in O.BERSAGLI:
        V = O.valida_ingressi(records, bersaglio=bers, lettura="regime",
                              previsori=previsori)
        print("")
        print("  " + "=" * 74)
        print("  VALIDAZIONE FUORI CAMPIONE  -  ingresso %s (con direzione)"
              % bers)
        print("  " + "=" * 74)
        if not V["porte"]:
            print("  %s." % (V.get("motivo") or "non validabile"))
            continue
        print("  %d giornate stimabili, %d con un ingresso MISURATO (%.0f%%)"
              % (V["n_stimabili"], V["n_ingressi"],
                 100.0 * (V["quota_stimabile"] or 0.0)))
        if V.get("n_censurati"):
            print("  %d escluse perche' il regime era gia' presente all'inizio"
                  % V["n_censurati"])
            print("  della finestra: l'ora vera non e' osservabile, e misurare")
            print("  un modello su un limite vuol dire misurarlo su un'ipotesi.")
        print("  %d blocchi di validazione, sempre in avanti nel tempo: il primo"
              % V["n_fold"])
        print("  blocco di giornate serve solo ad addestrare e non viene predetto.")
        print("")
        print("  previsore                            gg    MAE   bias  semiamp"
              "   <=30  <=45  <=60  guadagno sul rif.")
        print("  " + "-" * 104)
        ordine = [V["riferimento"]] + [n for n in sorted(V["previsori"])
                                       if n != V["riferimento"]]
        for nome in ordine:
            print(_riga_previsore(O, nome, V["previsori"][nome], V["riferimento"]))
        print("  " + "-" * 104)
        print("  MAE, bias e semiamp. sono minuti; semiamp. e' la meta'-larghezza")
        print("  della finestra che contiene il %.0f%% degli ingressi reali."
              % (100.0 * O.QUOTA_FINESTRA))

        r = V["previsori"][V["valutato"]]
        peggio = [(abs(v["bias"]), m, v) for m, v in r["bias_per_mese"].items()
                  if v["bias"] is not None]
        if peggio:
            peggio.sort(reverse=True)
            print("")
            print("  Bias per mese (mediana degli errori, + = previsto troppo tardi).")
            print("  \"sist.\" = l'intervallo bootstrap non contiene lo zero:")
            for mese in range(1, 13):
                v = r["bias_per_mese"].get(mese)
                if v and v["bias"] is not None:
                    lo, hi = v.get("ic", (None, None))
                    print("    %-4s n=%-4d %+6.0f min   [%+.0f,%+.0f]  %s"
                          % (MESI_BREVI[mese - 1], v["n"], v["bias"],
                             lo if lo is not None else 0.0,
                             hi if hi is not None else 0.0,
                             "sist." if v.get("significativo") else ""))
            print("  Per stagione:")
            for st in ("primavera", "estate", "autunno", "inverno"):
                v = r["bias_per_stagione"].get(st)
                if v and v["bias"] is not None:
                    lo, hi = v.get("ic", (None, None))
                    print("    %-10s n=%-5d %+6.0f min   [%+.0f,%+.0f]  %s"
                          % (st, v["n"], v["bias"],
                             lo if lo is not None else 0.0,
                             hi if hi is not None else 0.0,
                             "sist." if v.get("significativo") else ""))

        P = V["porte"]
        print("")
        # Il previsore su cui si misurano le porte e' quello che si USEREBBE:
        # il candidato se batte il riferimento, il riferimento altrimenti.
        print("  Le tre porte, sul previsore che si userebbe (%s):" % r["nome"])
        def esito(p):
            return "APERTA" if p["passa"] else ("CHIUSA" if p["passa"] is False
                                                else "non applicabile")
        print("    A  finestra <= %.0f min          %-16s semiampiezza %s"
              % (P["semiampiezza"]["limite"], esito(P["semiampiezza"]),
                 "n.d." if P["semiampiezza"]["valore"] is None
                 else "%.0f min" % P["semiampiezza"]["valore"]))
        g = P["guadagno"]
        dettaglio_g = g.get("nota") or ""
        if g["valore"] is not None:
            ic = g.get("ic") or (None, None)
            numeri = ("guadagno %+.0f%%, IC %+.0f..%+.0f"
                      % (g["valore"], ic[0] or 0.0, ic[1] or 0.0))
            dettaglio_g = (numeri if not dettaglio_g
                           else "%s (%s)" % (dettaglio_g, numeri))
        print("    B  batte la climatologia       %-16s %s"
              % (esito(g), dettaglio_g))
        b2 = P["bias_stagionale"]
        if b2.get("sistematico") is not None:
            dettaglio = ("sistematico: %s, %+.0f min (limite %.0f)"
                         % (b2["sistematico_dove"], b2["sistematico"], b2["limite"]))
        elif b2["valore"] is None:
            dettaglio = "nessun gruppo con giornate a sufficienza"
        else:
            dettaglio = ("il piu' storto e' %s, %+.0f min, ma non e' "
                         "distinguibile da zero"
                         % (b2["dove"], b2["valore"]))
        print("    C  nessun bias sistematico     %-16s %s" % (esito(b2), dettaglio))
        print("")
        if V["esito"] == "affidabile":
            print("  ESITO: timing affidabile. Un modello batte la climatologia")
            print("  fuori campione: la finestra si puo' dichiarare in home.")
        elif V["esito"] == "climatologico":
            print("  ESITO: orario climatologico. Nessun modello batte la")
            print("  climatologia mensile, ma la finestra della climatologia sta")
            print("  entro %.0f minuti: si puo' dichiarare, dicendo da dove viene."
                  % V["porte"]["semiampiezza"]["limite"])
            print("  Sarebbe sbagliato chiamarlo \"incerto\": l'informazione c'e',")
            print("  e viene dalla stagione, non da un modello.")
        else:
            print("  ESITO: orario incerto. In home va una fascia larga, e va detto")
            print("  che il timing e' incerto. %s" % (V["motivo"] or ""))


def _hhmm(minuti):
    """Minuti dalla mezzanotte -> HH:MM. None resta un trattino."""
    if minuti is None:
        return "  -  "
    m = int(round(minuti))
    return "%02d:%02d" % (m // 60, m % 60)


def _durata(minuti):
    if minuti is None:
        return "   - "
    m = int(round(minuti))
    return "%dh%02d" % (m // 60, m % 60)


# Una sola riga-modello per i mesi e per il totale: se le due si scrivono a
# mano separatamente, prima o poi si scollano di un carattere e la tabella
# diventa illeggibile senza che nessun controllo se ne accorga.
RIGA_FINESTRA = "  %-4s %4d  %5d  %s-%s     %s   %s  %s"

MESI_BREVI = ("gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic")


def cmd_distribuzione(spot_name=None):
    """La distribuzione osservata dentro la finestra utile, per mese.

    Serve a una cosa sola: scegliere le soglie guardando i numeri veri invece
    di inventarle. Per questo non c'e' nessuna etichetta "forte / debole" e
    nessuna soglia privilegiata - c'e' la griglia intera, e la scelta la fa chi
    legge.

    Come cmd_orari, qui non si calcola niente: tutta la logica sta in
    gardawind/orari.py e questa funzione traduce e impagina.
    """
    from gardawind import orari as O

    spots = [spot_name] if spot_name else [
        n for n in config.SPOT_ORDER if config.SPOTS[n]["target"] == "hourly"]

    for name in spots:
        spot = config.SPOTS[name]
        h0, h1 = spot["window"]
        D = O.distribuzione_finestra_utile(name)
        soglie = D["soglie"]

        print("")
        print("=" * 78)
        print("  DENTRO LA FINESTRA UTILE  -  %s" % name)
        print("  finestra del regime %02d:00-%02d:00" % (h0, h1 + 1), end="")
        pratica = spot.get("ora_pratica")
        if pratica is not None:
            print("  -  ora pratica %02d:00" % int(pratica), end="")
        print("")
        print("  piu' stretta di: alba + %g min, tramonto - %g min"
              % (config.MARGINE_ALBA_MIN, config.MARGINE_TRAMONTO_MIN))
        print("  asse osservato %g deg  -  settore +-%g  -  fuori settore = 0"
              % (D["asse"], D["settore"]))
        print("  sostenuta = sopra soglia per almeno %g minuti consecutivi"
              % D["persist_min"])
        print("=" * 78)
        print("")
        _stampa_copertura(D["copertura"],
                          "dentro la finestra utile: SOLO vento medio")

        print("  ATTENZIONE, e vale per tutta la tabella: queste quote sono")
        print("  calcolate sul VENTO MEDIO. Con il wing si sta sul foil anche")
        print("  sotto la media, se la raffica ricorrente ripassa spesso -")
        print("  quindi sono un LIMITE INFERIORE della planabilita' vera, non")
        print("  la planabilita'. La ricorrente nell'archivio lungo non c'e'.")
        print("")

        # ------------------------------------------------------------------
        # Tabella 1: com'e' fatta la finestra, e quanto vento ci sta dentro
        # ------------------------------------------------------------------
        print("  LA FINESTRA, E IL VENTO MEDIO CHE CI STA DENTRO")
        print("  mese   gg  stim.  finestra mediana  durata   medio q25/med/q75"
              "   picco")
        print("  " + "-" * 74)
        for m in range(1, 13):
            r = D["mesi"].get(m)
            if not r:
                continue
            tre = "  -  /  -  /  -  "
            if r["media_mediana"] is not None:
                tre = "%5.1f /%5.1f /%5.1f" % (r["media_q25"], r["media_mediana"],
                                               r["media_q75"])
            picco = "   - "
            if r["picco_mediano"] is not None:
                picco = "%5.1f" % r["picco_mediano"]
            print(RIGA_FINESTRA
                  % (MESI_BREVI[m - 1], r["n_giorni"], r["n_stimabili"],
                     _hhmm(r["inizio_mediano"]), _hhmm(r["fine_mediana"]),
                     _durata(r["durata_mediana"]), tre, picco)
                  + ("" if r["sufficiente"] else "  (pochi)"))
        A = D["anno"]
        print("  " + "-" * 74)
        tre = "  -  /  -  /  -  "
        if A["media_mediana"] is not None:
            tre = "%5.1f /%5.1f /%5.1f" % (A["media_q25"], A["media_mediana"],
                                           A["media_q75"])
        print(RIGA_FINESTRA
              % ("anno", A["n_giorni"], A["n_stimabili"],
                 _hhmm(A["inizio_mediano"]), _hhmm(A["fine_mediana"]),
                 _durata(A["durata_mediana"]), tre,
                 "%5.1f" % A["picco_mediano"] if A["picco_mediano"] is not None
                 else "   - "))
        print("  " + "-" * 74)
        print("  \"stim.\" = giornate con abbastanza dato dentro la finestra.")
        print("  \"medio\" = mediana del vento medio nella finestra, per giornata:")
        print("  il fondo della sessione. \"picco\" = mediana del massimo della")
        print("  media, cioe' il momento migliore della giornata tipica.")
        print("  \"(pochi)\" = meno di %d giornate stimabili: numero fragile."
              % D["min_gg"])
        print("")

        # ------------------------------------------------------------------
        # Tabella 2: la griglia delle soglie. Nessuna e' "la" soglia.
        # ------------------------------------------------------------------
        # La tabella e' TRASPOSTA: le soglie in riga e i mesi in colonna. Con
        # la griglia fitta fra gli 8 e i 14 nodi - che e' dove sta davvero la
        # distribuzione del Peler - una soglia per colonna non entrerebbe piu'
        # nella larghezza di un terminale, e una tabella che va a capo e' una
        # tabella che non si legge.
        mesi_presenti = [m for m in range(1, 13) if D["mesi"].get(m)]
        fragili = [m for m in mesi_presenti if not D["mesi"][m]["sufficiente"]]

        def intestazione_mesi(titolo):
            testa = "  %-6s" % titolo
            for m in mesi_presenti:
                testa += "%5s" % (MESI_BREVI[m - 1][:3]
                                  + ("*" if m in fragili else ""))
            return testa + "%7s" % "anno"

        def riga_soglia(t, cella):
            riga = "  %5s " % ("%g" % t)
            for m in mesi_presenti:
                riga += "%4s " % cella(D["mesi"][m]["soglie"].get(t) or {})
            return riga + "%6s" % cella(A["soglie"].get(t) or {})

        def come_quota(c):
            q = c.get("quota")
            return "-" if q is None else "%.0f%%" % (100.0 * q)

        def come_continuita(c):
            """Quanta parte della finestra utile, non quanti minuti.

            I minuti dentro la finestra sono quasi sempre un limite inferiore,
            perche' la finestra utile del Peler e' una fetta ritagliata in
            mezzo a un evento piu' lungo: alle 06:00 il vento spesso c'e' gia'
            e alle 11:00 spesso c'e' ancora. La quota della finestra invece
            non e' censurata da niente - la finestra e' il denominatore, non
            un taglio - ed e' la continuita' che serve alla scheda. I minuti
            si ricavano moltiplicandola per la durata della finestra, che sta
            nella prima tabella; restano nel dato, col loro limite, per chi li
            vuole.
            """
            q = c.get("quota_finestra_mediana")
            return "-" if q is None else "%.0f%%" % (100.0 * q)

        def come_durata(c):
            """Il '+' non e' decorazione: dice che il numero e' un limite.

            Il tempo sopra soglia lo taglia la finestra. Se il vento era gia'
            sopra al primo campione, o era ancora sopra all'ultimo, quel
            periodo cominciava prima o continuava dopo, e la durata misurata
            e' un limite inferiore. A dicembre la finestra utile del Peler e'
            lunga 150 minuti: leggere "150" come una durata invece di "almeno
            150" sarebbe confondere il vento con l'orario del tramonto.
            """
            d = c.get("durata_mediana")
            if not d:
                return "-"
            return "%d%s" % (int(round(d)), "+" if c.get("durata_e_limite") else "")

        print("  QUANTE MATTINE SOPRA SOGLIA, MESE PER MESE")
        print("  quota delle giornate stimabili in cui la media e' rimasta")
        print("  sopra soglia per almeno %g minuti di fila" % D["persist_min"])
        print("")
        print(intestazione_mesi("kn"))
        print("  " + "-" * (7 + 5 * len(mesi_presenti) + 6))
        for t in soglie:
            print(riga_soglia(t, come_quota))
        print("  " + "-" * (7 + 5 * len(mesi_presenti) + 6))
        print("")

        print("  E QUANTO E' DURATA, QUANDO E' SUCCESSO")
        print("  durata mediana in minuti del periodo sopra soglia, sulle sole")
        print("  giornate che la soglia l'hanno superata")
        print("")
        print(intestazione_mesi("kn"))
        print("  " + "-" * (7 + 5 * len(mesi_presenti) + 6))
        for t in soglie:
            print(riga_soglia(t, come_durata))
        print("  " + "-" * (7 + 5 * len(mesi_presenti) + 6))
        if fragili:
            print("  * meno di %d giornate stimabili: numero fragile." % D["min_gg"])
        print("  Il + vuol dire ALMENO, e non e' un dettaglio: su meta' o piu'")
        print("  di quelle giornate il vento era gia' sopra soglia al primo")
        print("  campione della finestra utile, o ancora sopra all'ultimo. Quel")
        print("  periodo cominciava prima o continuava dopo, e quanto sia durato")
        print("  davvero non lo sappiamo - lo taglia la finestra, non il vento.")
        # Anche il mese di esempio si cerca nei dati: qual e' quello con la
        # finestra piu' corta. Scriverlo a mano ("a dicembre...") vale per il
        # Peler di Torbole e per nessun altro spot.
        con_finestra = [(D["mesi"][m]["durata_mediana"], m) for m in mesi_presenti
                        if D["mesi"][m].get("durata_mediana")]
        if con_finestra:
            corto, m_corto = min(con_finestra)
            lungo, m_lungo = max(con_finestra)
            print("  La finestra piu' corta e' quella di %s, %d minuti: se la"
                  % (MESI_BREVI[m_corto - 1], int(round(corto))))
            print("  cella di %s dice %d+ vuol dire \"almeno tutta\", e non si"
                  % (MESI_BREVI[m_corto - 1], int(round(corto))))
            print("  confronta con i minuti di %s, che stanno dentro %d."
                  % (MESI_BREVI[m_lungo - 1], int(round(lungo))))
        print("  (Si scrive col + e non con >= solo per larghezza: dodici mesi")
        print("  di \">=150'\" non entrano in una riga di terminale.)")
        print("  E la durata puo' CRESCERE salendo di soglia: non e' un errore,")
        print("  sono giornate diverse. Le poche che passano i 16 sono giornate")
        print("  forti, e il loro tempo sopra i 16 puo' superare il tempo tipico")
        print("  sopra i 14 di tutte le altre.")
        # L'esempio si CALCOLA. Una frase di legenda con un numero scritto
        # a mano e' un numero che prima o poi sara' sbagliato, e qui lo era
        # gia': diceva "42% delle mattine sopra 10 kn" mentre il 42% e' la
        # riga dei 14 a dicembre - cioe' induceva esattamente l'equivoco che
        # tutta questa tabella esiste per togliere.
        print("  Le due tabelle si leggono insieme: la prima dice quanto")
        print("  spesso, la seconda per quanto. Da questa tabella, per esempio:")
        rif = 10.0 if 10.0 in soglie else soglie[0]
        c10 = A["soglie"].get(rif) or {}
        if c10.get("quota") is not None and c10.get("durata_mediana"):
            print("    sul totale dell'archivio, nel %.0f%% delle mattine"
                  % (100.0 * c10["quota"]))
            print("    stimabili la media e' rimasta sopra i %g kn per almeno" % rif)
            print("    mezz'ora di fila, e quando e' successo e' durata %s minuti."
                  % come_durata(c10))
            mese_top = max(
                (m for m in mesi_presenti
                 if (D["mesi"][m]["soglie"].get(rif) or {}).get("quota") is not None),
                key=lambda m: D["mesi"][m]["soglie"][rif]["quota"], default=None)
            if mese_top:
                print("    Il mese piu' generoso a %g kn e' %s, con il %.0f%%."
                      % (rif, MESI_BREVI[mese_top - 1],
                         100.0 * D["mesi"][mese_top]["soglie"][rif]["quota"]))
        print("  Ognuna delle due meta' da sola non basta per decidere.")
        print("")

        # ------------------------------------------------------------------
        # Tabella 3: le stagioni d'uso. Non si naviga dodici mesi l'anno.
        # ------------------------------------------------------------------
        if D.get("stagioni"):
            nomi = [n for n in D["ordine_stagioni"] if D["stagioni"].get(n)]
            print("  LE STESSE DUE COSE, PER STAGIONE D'USO")
            testa = "  %5s " % "kn"
            for n in nomi:
                testa += "%14s" % n
            print(testa)
            print("  " + "-" * (7 + 14 * len(nomi)))
            for t in soglie:
                riga = "  %5s " % ("%g" % t)
                for n in nomi:
                    c = D["stagioni"][n]["soglie"].get(t) or {}
                    riga += "%8s%6s" % (come_quota(c), come_durata(c))
                print(riga)
            print("  " + "-" * (7 + 14 * len(nomi)))
            riga = "  %5s " % "gg"
            for n in nomi:
                riga += "%14d" % D["stagioni"][n]["n_stimabili"]
            print(riga)
            for n in nomi:
                mesi = D["stagioni"][n].get("mesi_inclusi") or ()
                print("  %-13s %s"
                      % (n, ", ".join(MESI_BREVI[m - 1] for m in mesi)))
            print("  " + "-" * (7 + 14 * len(nomi)))
            print("  La stagione PRIMARIA e' quella su cui si leggono le quote")
            print("  d'uso: e' quando si va in acqua. La DIAGNOSTICA (inverno)")
            print("  serve a vedere persistenza e struttura del regime, non a")
            print("  tarare il prodotto - una metrica tarata su dicembre")
            print("  funzionerebbe bene proprio nei mesi in cui non la usi.")
            print("  Ma la soglia di planata NON si sceglie dalla stagione:")
            print("  quanti nodi ti tengono sul foil e' una proprieta' della")
            print("  tua ala, non del mese. La stagione dice quali righe")
            print("  leggere, il numero lo dai tu.")
            print("")

        print("  COME SI LEGGE, E COSA SI DECIDE")
        print("  Una riga dice: in quella frazione delle giornate del mese il")
        print("  vento medio nella finestra utile e' rimasto sopra quella soglia")
        print("  per almeno mezz'ora di fila, e quando e' successo e' durato")
        print("  quei minuti. Nessuna di queste soglie e' \"la\" soglia: la")
        print("  griglia c'e' tutta proprio perche' la scelta non e' del codice.")
        print("  Serve un numero: a quanti nodi di vento medio, con la tua ala")
        print("  piu' grande, stai sul foil. Da quello nasce la scheda del")
        print("  Peler, e solo da quello.")
        print("")
        P = getattr(config, "PLANATA_DICHIARATA", None)
        if P:
            print("  LA TUA REGOLA, MESSA A VERBALE IL %s" % P["dichiarata_il"])
            print("    sulla media da sola:  %g kn" % P["media_sola_kn"])
            print("    con la ricorrente:    media %g kn se la ricorrente 30'"
                  % P["coppia_media_kn"])
            print("                          arriva a %g kn"
                  % P["coppia_ricorrente_kn"])
            print("    stato: %s" % ("validata" if P.get("validata")
                                     else "DICHIARATA, non validata"))
            if not P.get("validata"):
                print("    La colonna da leggere in questa tabella e' quella")
                print("    dei %g kn: e' la tua regola sulla sola media, ed e'"
                      % P["media_sola_kn"])
                print("    l'unica calcolabile su quattordici anni. La coppia")
                print("    fa planare di piu' - con dieci di media e la spinta")
                print("    che ripassa si sta sul foil - quindi la colonna dei")
                print("    %g kn e' un LIMITE INFERIORE della tua planabilita'"
                      % P["media_sola_kn"])
                print("    vera, non la sua misura. La coppia si potra'")
                print("    misurare a %d ore di raffica contemporanea."
                      % P.get("gate_ore", 1000))
            print("")

        print("  giornate in cui la raffica ricorrente 30' era stimabile: %d su %d"
              % (A["n_ric_stimabile"], A["n_stimabili"]))
        if A["n_stimabili"] and A["n_ric_stimabile"] < A["n_stimabili"]:
            print("  -> e' la distanza che ci separa dal poter rispondere per")
            print("     davvero: la planabilita' vera si decide su media E")
            print("     ricorrente, e la ricorrente c'e' solo da adesso.")
        sys.stdout.flush()


def cmd_orari(spot_name=None):
    """Quando entra il vento: climatologia osservata dell'orario.

    Due bersagli, tenuti separati fino alla UI finale:

      INGRESSO DEL REGIME   attraversamento sostenuto della soglia di regime.
                            "Quando entra davvero Ora/Peler."
      INGRESSO DA PLANATA   attraversamento sostenuto della soglia di planata.
                            "Da quando ha senso andare in acqua."

    E due letture di ciascuno, affiancate:

      VENTO     solo intensita': il vento supera la soglia, da qualunque parte.
      REGIME    intensita' E direzione dentro il settore attorno all'asse
                osservato della centralina.

    Affiancarle non e' pignoleria. "Il vento supera i 14 nodi nel 63% dei
    pomeriggi" e "l'Ora e' utile nel 63% dei pomeriggi" sono due frasi diverse,
    e la prima diventa la seconda appena la si stacca dalla sua colonna. La
    differenza fra le due colonne E' la misura di quanto conta la direzione.

    Questo comando non calcola nulla: tutta la logica sta in gardawind/orari.py
    e qui si traduce e si impagina. E' il confine che serve perche' fra sei mesi
    una modifica alla tabella non finisca per spostare una definizione.
    """
    from gardawind import orari as O

    spots = [spot_name] if spot_name else [
        n for n in config.SPOT_ORDER if config.SPOTS[n]["target"] == "hourly"]

    for name in spots:
        spot = config.SPOTS[name]
        h0, h1 = spot["window"]
        C = O.climatologia(name)
        print("")
        print("=" * 78)
        print("  ORARI DI INGRESSO  -  %s" % name)
        print("  finestra %02d:00-%02d:00  -  asse osservato %g deg  -  settore +-%g"
              % (h0, h1 + 1, C["asse"], C["settore"]))
        print("  soglia di regime %g kn  -  soglia di planata %g kn"
              % (C["soglie"]["regime"], C["soglie"]["planata"]))
        print("  ingresso = soglia superata per almeno %g minuti consecutivi"
              % O.PERSISTENZA_MIN)
        print("  una mediana mensile si stampa da %d giornate in su" % O.MIN_GG_MESE)
        print("=" * 78)

        print("")
        _stampa_copertura(O.copertura_dataset(O.giorni_osservati(name)),
                          "orario di ingresso: usa solo il vento medio e la "
                          "direzione")
        tot = C["n_giorni"] + C["n_non_stimabili"]
        print("  %d giornate nell'archivio: %d stimabili, %d scartate"
              % (tot, C["n_giorni"], C["n_non_stimabili"]))
        if C["n_dir_ignota"]:
            print("  %d stimabili hanno direzione ignota su oltre un quinto dei"
                  % C["n_dir_ignota"])
            print("  campioni: in quelle la colonna REGIME e' per forza piu' bassa.")

        conteggi = {}
        for g in C["per_giorno"].values():
            conteggi[g["reason"]] = conteggi.get(g["reason"], 0) + 1
        if conteggi:
            print("")
            print("  Cosa dice ogni giornata (codici chiusi, non testo libero):")
            for codice in O.REASONS:
                if codice in conteggi:
                    print("    %-24s %5d  %5.1f%%   %s"
                          % (codice, conteggi[codice],
                             100.0 * conteggi[codice] / tot if tot else 0.0,
                             MOTIVI.get(codice, "")))
            sconosciuti = [c for c in conteggi if c not in O.REASONS]
            if sconosciuti:
                print("    ATTENZIONE, codici non previsti: %s"
                      % ", ".join(sorted(str(c) for c in sconosciuti)))

        for bers in O.BERSAGLI:
            print("")
            print("  INGRESSO %s  (soglia %g kn)"
                  % (bers.upper(), C["soglie"][bers]))
            print("                  VENTO (solo intensita')          "
                  "REGIME (intensita' + direzione)")
            print("  mese     gg  c%  ingresso  disp   durata      "
                  "gg  c%  ingresso  disp   durata")
            print("  " + "-" * 84)
            for mese in range(1, 13):
                celle = [_cella(C["per_mese"][(bers, l, mese)]) for l in O.LETTURE]
                rr = C["per_mese"][(bers, "regime", mese)]
                nota = ""
                if rr["modi"] and len(rr["modi"]) >= 2:
                    nota = ("   <- DUE PICCHI: %s e %s"
                            % (_hhmm(rr["modi"][0]), _hhmm(rr["modi"][1])))
                print("  %-6s %s   %s%s"
                      % (MESI_BREVI[mese - 1], celle[0], celle[1], nota))
            print("  " + "-" * 84)
            celle = [_cella(C["annuale"][(bers, l)]) for l in O.LETTURE]
            print("  %-6s %s   %s" % ("anno", celle[0], celle[1]))
            v = C["annuale"][(bers, "vento")]["n"]
            r = C["annuale"][(bers, "regime")]["n"]
            if v:
                tagliati = v - r
                print("  La direzione taglia %d %s su %d (%.0f%%): %s il vento"
                      % (tagliati, "ingresso" if tagliati == 1 else "ingressi",
                         v, 100.0 * tagliati / v,
                         "giornata in cui" if tagliati == 1
                         else "giornate in cui"))
                print("  bastava ma non era %s."
                      % ("l'Ora" if spot["regime"] == "ORA" else "il Peler"))

        # Quante giornate, in tutto, hanno un orario non osservabile. E' il
        # numero che dice se una finestra di osservazione e' troppo stretta
        # per il regime che deve misurare.
        n_cens = sum(1 for g in C["per_giorno"].values()
                     if g.get("regime_onset_censored"))
        if n_cens:
            print("")
            print("  %d giornate (%.0f%% delle stimabili) avevano il regime GIA'"
                  % (n_cens, 100.0 * n_cens / max(1, C["n_giorni"])))
            print("  presente al primo campione della finestra: per quelle l'ora")
            print("  di ingresso non e' osservabile, e valgono come limite - non")
            print("  entrano nell'addestramento del timing e non fanno mediana.")
            print("  Se la quota e' alta in un mese, la finestra di osservazione")
            print("  comincia troppo tardi per quel regime, e non e' un difetto")
            print("  del vento.")
        bimodali = [(b, m) for b in O.BERSAGLI for m in range(1, 13)
                    if (C["per_mese"][(b, "regime", m)]["modi"] or [])
                    and len(C["per_mese"][(b, "regime", m)]["modi"]) >= 2]
        # I rifiutati vanno detti: "non ci sono due picchi" e' un risultato,
        # e tacerlo farebbe sembrare che la forma non sia stata guardata.
        rifiutati = {}
        for b in O.BERSAGLI:
            for m in range(1, 13):
                mot = C["per_mese"][(b, "regime", m)].get("modi_motivo")
                if mot:
                    rifiutati[mot] = rifiutati.get(mot, 0) + 1
        print("")
        if rifiutati:
            print("  Mesi con due massimi locali ma NON due modi: %s."
                  % ", ".join("%d %s" % (n, MOTIVI_MODI.get(k, k))
                              for k, n in sorted(rifiutati.items())))
            print("  Una valle alta quanto il picco non separa due popolazioni:")
            print("  e' una distribuzione larga, e chiamarla bimodale invita a")
            print("  costruire una complessita' che il dato non sostiene.")
            print("")
        if bimodali:
            print("  ATTENZIONE: %d mesi hanno due picchi di ingresso del regime."
                  % len(bimodali))
            print("  Per quei mesi una sola mediana mensile e' un riferimento povero:")
            print("  cade nell'avvallamento fra i due picchi, dove capita poco.")
            for b, m in bimodali:
                rr = C["per_mese"][(b, "regime", m)]
                print("    %-8s %-4s  n=%-4d picchi %s e %s   valle/picco %s"
                      % (b, MESI_BREVI[m - 1], rr["n"], _hhmm(rr["modi"][0]),
                         _hhmm(rr["modi"][1]),
                         ("%.2f" % rr["dip"]) if rr["dip"] is not None else "n.d."))
        else:
            print("  Nessun mese con due picchi: la mediana mensile e' un riassunto")
            print("  adeguato, e va bene come riferimento banale da battere.")
        print("")
        print("  \"disp\" e' la mediana degli scarti dalla mediana, in minuti:")
        print("  quanto l'orario balla da un giorno all'altro DENTRO lo stesso mese.")
        print("  E' il numero che un modello dell'orario deve battere fuori campione.")

        _stampa_validazione(O, C)
        sys.stdout.flush()



def cmd_addicted_validazione():
    """Confronta lo storico Addicted con T0193 senza cambiare il modello."""
    from gardawind import addicted_validate as V
    r = V.rapporto_completo()

    print("\n" + "=" * 78)
    print("  ADDICTED-SPORTS  -  VALIDAZIONE CONTRO T0193")
    print("  sola lettura: nessun dato e nessun parametro del modello viene modificato")
    print("=" * 78)

    def pm(nome, m):
        if not m or not m.get("n"):
            print("  %-24s nessun overlap" % nome); return
        print("  %-24s n=%6d  bias=%+5.2f  MAE=%4.2f  RMSE=%4.2f  r=%4.2f"
              % (nome, m["n"], m["bias"], m["mae"], m["rmse"], m["corr"]))

    print("\n  mavg Addicted vs media oraria T0193 (candidato - riferimento), kn")
    pm("tutto", r["media"].get("tutto"))
    pm("Peler pratico 06-11", r["media"].get("peler_06_11"))
    pm("Ora 11-20", r["media"].get("ora_11_20"))

    print("\n  mmax Addicted nel periodo con raffica T0193 vera")
    pm("vs max raffica dell'ora", r["raffica_recente"].get("max_orario"))
    pm("vs gust_rec 30'", r["raffica_recente"].get("ricorrente30"))
    print("    ore comuni: %d" % r["raffica_recente"].get("ore", 0))

    print("\n  valori estremi ripetuti da auditare, non cancellati")
    if r["massimi_sospetti"]:
        for x in r["massimi_sospetti"]:
            print("    %.1f kn ripetuto %d volte" % (x["value"], x["count"]))
    else:
        print("    nessuno")

    cb = r["campione_brenzone"]
    q = 100.0 * cb["quota"] if cb["quota"] is not None else 0.0
    print("\n  Campione/Brenzone: %d/%d ore comuni identiche (%.3f%%)"
          % (cb["uguali"], cb["n"], q))
    sh = r["campione_brenzone_shift7"]
    qs = 100.0 * sh["quota"] if sh["quota"] is not None else 0.0
    print("  nullo +7 giorni:  %d/%d identiche (%.3f%%)"
          % (sh["uguali"], sh["n"], qs))

    print("\n  QC storico mmax (segnala, non cancella)")
    for st, x in sorted(r["qc_massimi"].items()):
        qok = 100.0 * x.get("quota_qc_ok", 0.0)
        print("    %-14s n=%6d  p99=%5.1f  max=%5.1f  QC-ok=%6.2f%%  sotto-media=%d"
              % (st, x.get("n_max", 0), x.get("p99", 0.0), x.get("max", 0.0),
                 qok, x.get("max_sotto_media", 0)))
        for p in x.get("plateau_sospetti", []):
            print("      plateau sospetto %.1f kn: %d ore (%.2f%%)"
                  % (p["value"], p["count"], 100.0 * p["share"]))

    print("\n  ponte storico mavg -> mmax, solo ore QC-ok")
    prof = r.get("profilo_rafficosita", {})
    for key, label in (("peler_06_11", "Peler 06-11"), ("ora_11_20", "Ora 11-20")):
        x = prof.get("gruppi", {}).get(key, {})
        if not x.get("n"):
            continue
        f = x.get("fit", {})
        print("    %-12s n=%6d  spread med=%4.1f  p90=%4.1f  ratio med*=%4.2f"
              % (label, x["n"], x["spread_mediana"], x["spread_p90"],
                 x.get("ratio_mediana_mavg_ge3") or 0.0))
        print("      mmax ~= %4.1f + %4.2f*mavg   r=%4.2f  MAE fit=%4.2f kn"
              % (f.get("intercetta") or 0.0, f.get("pendenza") or 0.0,
                 f.get("corr") or 0.0, f.get("mae_fit") or 0.0))
    print("    * rapporto calcolato solo con mavg >= 3 kn")

    print("\n  mmax Addicted contro media oraria VERA T0193, solo ore QC-ok")
    pt = r.get("ponte_mmax_t0193", {})
    for key, label in (("peler_06_11", "Peler 06-11"), ("ora_11_20", "Ora 11-20")):
        x = pt.get("gruppi", {}).get(key, {})
        if not x.get("n"):
            continue
        f = x.get("fit", {})
        print("    %-12s n=%6d  ratio med*=%4.2f  spread med=%4.1f kn"
              % (label, x["n"], x.get("ratio_mediana_tmean_ge3") or 0.0,
                 x.get("spread_mediana") or 0.0))
        print("      mmax ~= %4.1f + %4.2f*T0193   r=%4.2f  MAE fit=%4.2f kn"
              % (f.get("intercetta") or 0.0, f.get("pendenza") or 0.0,
                 f.get("corr") or 0.0, f.get("mae_fit") or 0.0))
    print("    * rapporto calcolato solo con T0193 >= 3 kn")

    cal = r.get("calibrazione_media_mensile", {})
    print("\n  stabilita' mavg Addicted vs T0193 per mese")
    print("    mese       Peler 06-11: n / bias / MAE        Ora 11-20: n / bias / MAE")
    for mese in range(1, 13):
        p = cal.get("fascia_mensile", {}).get(("peler_06_11", mese), {})
        o = cal.get("fascia_mensile", {}).get(("ora_11_20", mese), {})
        def cell(x):
            if not x.get("n"):
                return "      - /    - /    -"
            return "%5d / %+4.1f / %4.1f" % (x["n"], x["bias"], x["mae"])
        print("    %02d         %s          %s" % (mese, cell(p), cell(o)))

    stab = r.get("stabilita_ponte", {})
    print("\n  stabilita' temporale del ponte mavg -> mmax QC-ok")
    for key, label in (("peler_06_11", "Peler 06-11"), ("ora_11_20", "Ora 11-20")):
        x = stab.get(key, {})
        if not x.get("mesi_validi"):
            print("    %-12s nessun mese con copertura sufficiente" % label)
            continue
        print("    %-12s %2d mesi: slope med=%4.2f [p10 %4.2f, p90 %4.2f], MAE med=%4.2f kn"
              % (label, x["mesi_validi"], x["pendenza_mediana"],
                 x["pendenza_p10"], x["pendenza_p90"], x["mae_mediana"]))
        print("      spread mensile med=%4.1f kn [p10 %4.1f, p90 %4.1f]"
              % (x["spread_mediana_dei_mesi"], x["spread_p10"], x["spread_p90"]))

    gate = r.get("gate_proxy_gust_rec", {})
    print("\n  gate copertura per futura calibrazione mmax -> gust_rec 30'")
    print("    disponibili: %d ore, %d giorni, %d mesi; richiesti: >=%d ore, >=%d giorni, >=%d mesi"
          % (gate.get("ore", 0), gate.get("giorni", 0), gate.get("mesi", 0),
             gate.get("min_ore", 0), gate.get("min_giorni", 0), gate.get("min_mesi", 0)))
    prog = gate.get("progresso", {})
    print("    avanzamento: ore %5.1f%%  giorni %5.1f%%  mesi %5.1f%%  gate complessivo %5.1f%%"
          % (100.0 * prog.get("ore", 0.0), 100.0 * prog.get("giorni", 0.0),
             100.0 * prog.get("mesi", 0.0), 100.0 * gate.get("progresso_gate", 0.0)))
    print("    stato: %s" % ("APERTO" if gate.get("pronto") else "CHIUSO"))

    print("\n  VERDETTO")
    print("  - mavg e' informativo ma non intercambiabile con T0193: va calibrato.")
    print("  - mmax recente segue bene il massimo di raffica dell'ora, ma NON e'")
    print("    gust_rec 30' e lo storico contiene valori ripetuti sospetti.")
    print("  - nessuna di queste serie entra nella planabilita' finche' la relazione")
    print("    col gust_rec 30' non e' validata su un periodo osservativo piu' lungo.")

def cmd_addicted(giorni=1):
    """Legge addicted-sports e racconta cosa ha letto, con la provenienza.

    E' una fonte che si LEGGE: non c'e' un contratto, c'e' una pagina. Quindi
    il comando stampa tre cose che di solito non si stampano - l'impronta
    della struttura, la versione del parser, e l'accordo fra i due canali -
    perche' sono quelle che diranno, il giorno che il sito cambia, se i numeri
    sono ancora quelli giusti.
    """
    from gardawind.sources import addicted as A

    print("")
    print("=" * 74)
    print("  ADDICTED-SPORTS  -  Torbole")
    print("  stazione %s  -  fonte %s  -  parser %s"
          % (A.STATION, A.SOURCE, A.PARSER_VERSION))
    print("=" * 74)
    s = A.raccogli(giorni=giorni)
    for g in s["giorni"]:
        m = g["meta"]
        print("")
        print("  %s: %d ore misurate, %d salvate"
              % (g["giorno"], g["n_righe"], g["n_salvate"]))
        print("    letto il %s  -  %s byte" % (m["fetched_at"], m["bytes"]))
        print("    struttura %s%s"
              % ((m["struct_sha256"] or "?")[:16],
                 "  CAMBIATA" if m["struttura_cambiata"] else ""))
        if m.get("ultima"):
            print("    ultima ora %s (provvisoria: e' in corso)" % m["ultima"])
        if m.get("mae_dichiarato") is not None:
            print("    errore medio dichiarato dal sito: %s" % m["mae_dichiarato"])
    if s.get("html"):
        ts, w, g_, _d = s["html"]["campione"]
        print("")
        print("  riquadro \"misurato ora\": %s  vento %s kn  raffica %s kn"
              % (ts, w, "-" if g_ is None else g_))
        c = s.get("confronto")
        if not c:
            print("  nessun confronto possibile fra i due canali")
        elif c.get("accordo") is None:
            print("  %s" % c.get("nota"))
        elif c["accordo"]:
            print("  i due canali concordano (scarti %s)"
                  % ", ".join("%s %.1f" % (k, v) for k, v in sorted(c["scarti"].items())))
        else:
            print("  ATTENZIONE: i due canali NON concordano: %s" % c["fuori"])
            print("  uno dei due parser sta leggendo il posto sbagliato.")
    for e in s["errori"]:
        print("  errore: %s" % e)
    print("")
    print("  La DIREZIONE non viene salvata: questa fonte pubblica la direzione")
    print("  PREVISTA, non quella misurata. Usarla come osservazione vorrebbe")
    print("  dire alimentare il filtro di settore - quello che distingue l'Ora")
    print("  dal Peler - con una previsione.")
    print("")
    print("  I campioni stanno in obs_sample sotto la stazione %s, e NON sono"
          % A.STATION)
    print("  ancora collegati a nessuno spot: unire due centraline che misurano")
    print("  lo stesso vento e' una decisione di modello, non di raccolta.")
    sys.stdout.flush()


def cmd_direzioni(spot_name=None, bin_deg=10):
    """Da dove viene davvero il vento. Nessuno scaricamento: legge l'archivio.

    Risponde alle cinque domande che la tabella dei settori pone e non risolve:
    dov'e' la moda, dov'e' la mediana circolare, come cambia per stagione, se
    la distribuzione e' bimodale, e se le giornate lontane dall'asse sono un
    altro fenomeno invece che lo stesso fenomeno storto.

    Una cautela sulla lettura. La CLASSE di ogni giornata e' assegnata dal
    settore, quindi mostrare la classe per settore direbbe solo che il filtro
    funziona: e' circolare. Le colonne che qui contano sono invece indipendenti
    dal settore - ORA DEL PICCO, INTENSITA', STAGIONE - e sono quelle che
    distinguono un Peler vero da un settentrionale sinottico: il Peler e'
    notturno-mattutino e c'e' tutto l'anno, un sinottico entra a qualunque ora.
    """
    from . import regimes
    from .util import (angle_diff, circular_mean, circular_median,
                       circular_modes, median)
    STAG = {12: "inv", 1: "inv", 2: "inv", 3: "pri", 4: "pri", 5: "pri",
            6: "est", 7: "est", 8: "est", 9: "aut", 10: "aut", 11: "aut"}

    for name in ([spot_name] if spot_name else list(config.SPOT_ORDER)):
        spot = config.SPOTS[name]
        if spot["target"] != "hourly":
            continue
        cls = regimes.classify_days(store.obs_hours(spot["station"]),
                                    window=spot["window"],
                                    settori=regimes.settori_per_spot(spot))
        windy = [(r["dir"], r["peak"], r["peak_hour"], STAG[int(d[5:7])], r["classe"])
                 for d, r in cls.items()
                 if r.get("dir") is not None and r["peak"] >= regimes.MIN_REGIME_KN]
        print("\n" + "=" * 78)
        print("%s — %d giornate ventose (>= %g kn) nella finestra %02d-%02d locali"
              % (name, len(windy), regimes.MIN_REGIME_KN,
                 spot["window"][0], spot["window"][1]))
        print("   asse dichiarato: %g gradi" % spot["axis"])
        print("=" * 78)
        if len(windy) < 50:
            print("  troppo poche per dire qualcosa.")
            continue

        dirs = [d for d, _p, _h, _s, _c in windy]
        med = circular_median(dirs)
        mean_dir, R = circular_mean(dirs)
        modes, dip = circular_modes(dirs, bin_deg=bin_deg)

        print("\n  moda principale      %5.0f gradi  (%d giornate)"
              % (modes[0][0], modes[0][1]) if modes else "")
        print("  mediana circolare    %5.0f gradi" % med)
        print("  media circolare      %5.0f gradi  (concentrazione R=%.2f%s)"
              % (mean_dir, R,
                 ", molto concentrata" if R > 0.7 else
                 ", dispersa" if R < 0.4 else ""))
        print("  asse in uso per il bersaglio: %.0f gradi  (scarto della mediana: "
              "%.0f)" % (spot.get("axis_obs", spot["axis"]),
                         angle_diff(med, spot.get("axis_obs", spot["axis"]))))
        print("  asse geometrico del lago:     %.0f gradi  (scarto della mediana: "
              "%.0f)" % (spot["axis"], angle_diff(med, spot["axis"])))

        if len(modes) >= 2:
            # Attenzione allo zero: "dip or 1.0" tratterebbe un ventre
            # perfettamente vuoto (0.0, il caso PIU' bimodale che esista) come
            # dato mancante, e stamperebbe "una sola gobba larga" proprio
            # quando le due mode sono separate del tutto.
            d = 1.0 if dip is None else dip
            print("\n  BIMODALE: seconda moda a %.0f gradi (%d giornate). "
                  "Ventre fra le due al %.0f%% della seconda -> %s"
                  % (modes[1][0], modes[1][1], 100 * d,
                     "davvero separate" if d < 0.6 else "forse una sola gobba larga"))
        else:
            print("\n  unimodale: una sola gobba.")

        print("\n  settore   giorni   picco   ora del   stagione (%)        "
              "scarto")
        print("            ventosi  mediano  picco     inv pri est aut      dall'asse")
        print("  " + "-" * 74)
        bins = {}
        for d, p, h, st, c in windy:
            bins.setdefault(int((d % 360) // bin_deg) * bin_deg, []).append((p, h, st, c))
        top = max(len(v) for v in bins.values())
        for k in sorted(bins):
            v = bins[k]
            if len(v) < max(3, len(windy) // 150):
                continue
            hh = [h for _p, h, _s, _c in v if h is not None]
            quote = []
            for s_ in ("inv", "pri", "est", "aut"):
                quote.append(100.0 * sum(1 for _p, _h, s2, _c in v if s2 == s_) / len(v))
            barra = "#" * max(1, int(14 * len(v) / top))
            print("  %3d-%3d   %5d   %5.1f    %s   %3.0f %3.0f %3.0f %3.0f  %-14s %4.0f"
                  % (k, k + bin_deg, len(v), median([p for p, _h, _s, _c in v]),
                     ("%5.1f" % median(hh)) if hh else "    -",
                     quote[0], quote[1], quote[2], quote[3], barra,
                     angle_diff(k + bin_deg / 2.0, spot["axis"])))

        print("\n  per stagione:")
        for s_ in ("inv", "pri", "est", "aut"):
            sub = [d for d, _p, _h, st, _c in windy if st == s_]
            if len(sub) < 20:
                continue
            m2 = circular_median(sub)
            _mu, r2 = circular_mean(sub)
            print("    %s  %4d gg   mediana %5.0f gradi   R=%.2f   scarto dall'asse %4.0f"
                  % (s_, len(sub), m2, r2, angle_diff(m2, spot["axis"])))

        # Il confronto che NON e' circolare: dentro e fuori dal settore attuale,
        # l'ora del picco e' la stessa cosa o due cose diverse?
        SET = regimes.settori_per_spot(spot)
        ax_r, half = SET.get(spot["regime"], (spot.get("axis_obs", spot["axis"]), 45.0))
        dentro = [(p, h) for d, p, h, _s, _c in windy
                  if angle_diff(d, ax_r) <= half and h is not None]
        fuori = [(p, h) for d, p, h, _s, _c in windy
                 if angle_diff(d, ax_r) > half and h is not None]
        if len(dentro) > 20 and len(fuori) > 20:
            print("\n  dentro il settore (%g +/-%g):  %4d gg  picco %.1f kn  "
                  "ora mediana %.1f" % (ax_r, half, len(dentro),
                                        median([p for p, _h in dentro]),
                                        median([h for _p, h in dentro])))
            print("  fuori:                            %4d gg  picco %.1f kn  "
                  "ora mediana %.1f" % (len(fuori), median([p for p, _h in fuori]),
                                        median([h for _p, h in fuori])))
            print("  (se l'ora mediana e' simile, fuori dal settore c'e' lo STESSO")
            print("   fenomeno e l'asse e' storto; se e' diversa, e' un ALTRO vento.)")

        # --- la domanda che decide COSA correggere -----------------------
        # Uno scarto costante di trenta gradi in tutte le stagioni ha due
        # spiegazioni molto diverse, e portano a due rimedi opposti:
        #
        #   banderuola storta   la centralina ruota TUTTE le direzioni della
        #                       stessa quantita'. Rimedio: correggere il dato.
        #   incanalamento       la valle piega il vento VERSO il proprio asse,
        #                       da qualunque parte arrivi. Rimedio: lasciare il
        #                       dato e spostare l'asse del regime.
        #
        # Si distinguono guardando la direzione OSSERVATA in funzione di quella
        # PREVISTA dai modelli. Una rotazione rigida da' uno scarto costante in
        # ogni settore; un incanalamento da' uno scarto che cambia segno attorno
        # all'asse locale, perche' tira tutto verso di se'.
        pt = store.point_key(spot["lat"], spot["lon"])
        arch = {r["valid"]: r["d10"] for r in store.archive_rows(
            pt, "2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z") if r["d10"] is not None}
        if len(arch) > 5000:
            from .util import vector_mean_direction
            from . import features as F
            coppie = []
            for giorno, r in cls.items():
                if r.get("dir") is None or r["peak"] < regimes.MIN_REGIME_KN:
                    continue
                keys = [k for k in F.window_hours(giorno, *spot["window"]) if k in arch]
                if len(keys) < 3:
                    continue
                dm, _c = vector_mean_direction([(1.0, arch[k]) for k in keys])
                if dm is not None:
                    coppie.append((dm, r["dir"]))
            if len(coppie) > 200:
                print("\n  osservato contro previsto (%d giornate):" % len(coppie))
                print("    previsto dai modelli   giorni   osservato   scarto")
                print("    " + "-" * 52)
                gruppi = {}
                for dm, do in coppie:
                    gruppi.setdefault(int((dm % 360) // 30) * 30, []).append((dm, do))
                scarti = []
                for k in sorted(gruppi):
                    v = gruppi[k]
                    if len(v) < 15:
                        continue
                    oss = circular_median([do for _dm, do in v])
                    # Scarto CON SEGNO: positivo se l'osservato e' ruotato in
                    # senso orario rispetto al previsto.
                    sc = ((oss - circular_median([dm for dm, _do in v]) + 180) % 360) - 180
                    scarti.append(sc)
                    print("    %3d-%3d                 %5d   %5.0f      %+5.0f"
                          % (k, k + 30, len(v), oss, sc))
                if len(scarti) >= 3:
                    amp = max(scarti) - min(scarti)
                    print("    scarto medio %+.0f gradi, escursione fra i settori %.0f gradi"
                          % (sum(scarti) / len(scarti), amp))
                    if amp < 40:
                        print("    --> lo scarto e' quasi COSTANTE: rotazione rigida.")
                        print("        Compatibile con una banderuola disallineata.")
                    else:
                        print("    --> lo scarto CAMBIA molto fra i settori: il vento")
                        print("        viene piegato verso un asse locale. Incanalamento.")
                    print("    (nota: questo distingue le due cause, non le dimostra.")
                    print("     Per il modello cambia poco - in ogni caso il bersaglio")
                    print("     e' cio' che quella centralina misura.)")

        if angle_diff(med, spot.get("axis_obs", spot["axis"])) > bin_deg:
            print("\n  --> la mediana e' a %.0f gradi dall'asse in uso."
                  % angle_diff(med, spot.get("axis_obs", spot["axis"])))
            print("      Correggere l'asse cambia la definizione di \"regime entrato\",")
            print("      quindi va fatto INSIEME alla rivalidazione, non prima.")


def cmd_bands(spot_name=None):
    """Confronto fra tagli di fascia alternativi, sul periodo di addestramento."""
    from . import engine, validate as V
    for name in ([spot_name] if spot_name else list(config.SPOT_ORDER)):
        by_lead = engine.samples_by_lead(name)
        if not by_lead:
            print("%s: nessun campione" % name)
            continue
        st = V.band_study(name, by_lead, "surface")
        print("\n%s" % name)
        for c in st["candidati"]:
            print("  %-38s Brier %s  MAE %s  guad. prob %s  int %s  punt. %s  %s"
                  % ("|".join("%s%d-%d" % (n, r[0], r[1]) for n, r in c["layout"]),
                     _f(c["brier_pesato"], 3), _f(c["mae_pesato"]),
                     _f(100 * c["guadagno_prob"], 0) + "%" if c["guadagno_prob"] is not None else "-",
                     _f(100 * c["guadagno_int"], 0) + "%" if c["guadagno_int"] is not None else "-",
                     _f(c["punteggio"], 3),
                     "completo" if c["completo"] else "parziale"))
        print("  criterio: %s" % st["criterio"])
        print("  scelto:   %s" % (st["scelto"] or "nessuno"))


def _open_browser(url):
    """Apre il cruscotto nel browser predefinito.

    Su macOS il modulo webbrowser puo' non fare nulla quando il processo non
    e' una vera applicazione con interfaccia (come qui: siamo uno script
    dentro un bundle .app dichiarato LSUIElement). Il comando `open` del
    sistema funziona sempre, quindi si prova prima quello.
    """
    if sys.platform == "darwin" and os.path.exists("/usr/bin/open"):
        try:
            subprocess.Popen(["/usr/bin/open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def cmd_nowcast_validazione():
    from . import nowcast as N
    rep = N.validation_report()
    print("\n" + "=" * 78)
    print("  NOWCAST INTRADAY - VALIDAZIONE, NON PRODUZIONE")
    print("  banco storico: lead1; correzione all'ora h usa solo lo scarto di h-1")
    print("=" * 78)
    for spot_name in N.REGIMES:
        r = rep["historical"][spot_name]
        print("\n  %s" % spot_name)
        if not r["folds"]:
            print("    nessun fold valutabile; stato CHIUSO (%s)" % r["reason"])
            continue
        for f in r["folds"]:
            m = f["metrics"]
            lo, hi = f["gain_mae_ci95"]
            print("    %d  n=%4d  alpha=%.2f" % (f["year"], f["n"], f["alpha"]))
            print("      MAE: raw %.2f  pers %.2f  bias %.2f  now %.2f"
                  % (m["base"]["mae"], m["persistence"]["mae"],
                     m["static_bias"]["mae"], m["corrected"]["mae"]))
            print("      best=%s  guadagno MAE %.2f kn  CI95 [%.2f, %.2f]  guadagno RMSE %.2f kn"
                  % (f["best_baseline"], f["gain_mae"], lo, hi, f["gain_rmse"]))
            sr, sn = f["split"]["regime"], f["split"]["no_regime"]
            print("      giorni-regime: n=%d MAE now %.2f / pers %.2f / bias %.2f"
                  % (sr["n"], sr["mae_nowcast"] or 0.0, sr["mae_persistence"] or 0.0,
                     sr["mae_static_bias"] or 0.0))
            print("      senza-regime:  n=%d MAE now %.2f / pers %.2f / bias %.2f"
                  % (sn["n"], sn["mae_nowcast"] or 0.0, sn["mae_persistence"] or 0.0,
                     sn["mae_static_bias"] or 0.0))
        print("    gate concettuale: %s (%s)" % (r["state"].upper(), r["reason"]))
    p = rep["production"]
    print("\n  gate prodotto realmente mostrato")
    print("    archivio issued_profile: %d righe, %d giorni; richiesti >=%d righe, >=%d giorni"
          % (p["n"], p["days"], N.PROD_MIN_TARGETS, N.PROD_MIN_DAYS))
    print("    stato: %s (%s)" % (p["state"].upper(), p["reason"]))
    print("\n  VERDETTO")
    print("  - il gate storico dice se lo scarto intraday persiste fuori campione;")
    print("  - il gate produttivo resta separato: finche' non apre, nessuna correzione")
    print("    nowcast modifica la curva o la UI mostrata all'utente.")



def cmd_analoghi_validazione():
    r = analogs.validation_report()
    if not r.get("usable"):
        analogs.promote_from_validation(r)
        print("analoghi: PORTA CHIUSA - %s" % r.get("reason", r.get("diagnostic", {})))
        return
    print("Analoghi Torbole: %d giornate comuni (%s -> %s)" % (r["n"], r["from"], r["to"]))
    RIGA = " %-8s %5.1f%%  %5.1f%%  %7.1f  %+6.1f    %5.2f      %5.2f"

    def blocco(titolo, chiave, quali):
        """Una tabella per finestra. Le due finestre hanno soglie diverse, e
        stampate insieme senza dirlo si leggerebbero come la stessa cosa."""
        print("\n%s" % titolo)
        print(" %-8s colpi   falsi   err.min   sbil.   ripidezza   vera"
              % "quale")
        for etichetta, m in quali:
            if not m:
                continue
            v = m if chiave is None else m.get("peler")
            if not v or v.get("hits") is None:
                print(" %-8s non misurata" % etichetta); continue
            print(RIGA % (etichetta, 100*v["hits"], 100*v["false_alarms"],
                          v["minute_error"], v["bias_minutes"], v["steepness"],
                          v["true_steepness"]))

    righe = ([("D+%d" % lead, r["leads"][lead]) for lead in (1, 2, 3)]
             + [("nullo", r.get("null")), ("liscia", r.get("liscia"))])
    blocco("ORA - finestra 11:00-20:00, soglia %.0f kn, persistenza %g'"
           % (analogs.SOGLIA_PORTA, analogs._persistenza_min()), None, righe)
    blocco("PELER - finestra utile del giorno, soglia %.0f kn, persistenza %g'"
           % (analogs.SOGLIA_PELER, analogs._persistenza_min()), "peler", righe)
    # Una riga di lettura, perche' i numeri della mattina si fraintendono: i
    # colpi del nullo sono quasi quelli del modello, e chi legge deve sapere
    # che non e' un errore ma il risultato.
    # Il vantaggio: colpi meno falsi allarmi. E' l'unico modo di mettere in
    # fila i tre concorrenti senza farsi ingannare da una sola colonna - i
    # colpi alti si comprano promettendo tutti i giorni, e con la sagoma
    # riportata a picco 1 anche il nullo ne prende l'84%.
    def vant(m):
        h, f = (m or {}).get("hits"), (m or {}).get("false_alarms")
        return None if h is None or f is None else 100.0 * (h - f)

    print("\nVANTAGGIO (colpi meno falsi allarmi), finestra dell'Ora:")
    for etichetta, m in (("D+1 analoghi", r["leads"][1]),
                         ("curva liscia", r.get("liscia")),
                         ("nullo", r.get("null"))):
        v = vant(m)
        print("  %-14s %s" % (etichetta,
                              "non misurato" if v is None else "%+.1f punti" % v))
    print("  la porta pretende almeno %.1f punti di vantaggio sul nullo"
          % analogs.GUADAGNO_MIN_SU_NULLO)

    n_p = (r.get("null") or {}).get("peler") or {}
    m_p = (r["leads"][1] or {}).get("peler") or {}
    if n_p.get("hits") is not None and m_p.get("hits") is not None:
        print("\n  Sul Peler la forma NON discrimina la giornata: il nullo"
              " prende %.1f%% di colpi contro %.1f%% del modello."
              % (100*n_p["hits"], 100*m_p["hits"]))
        print("  Quello che la forma porta e' la calibrazione: durata"
              " sbilanciata di %+.0f minuti contro %+.0f della curva liscia."
              % (m_p["bias_minutes"],
                 ((r.get("liscia") or {}).get("peler") or {})
                 .get("bias_minutes", float("nan"))))
        print("  Quale mattina sara' di Peler lo decide il LIVELLO, che viene"
              " dalla previsione della sessione.")
    opened, reasons, _ = analogs.promote_from_validation(r)
    print("  PORTA %s" % ("APERTA" if opened else "CHIUSA"))
    for reason in reasons:
        print("    - " + reason)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gardawind", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=config.RUNTIME_PORT)
    ap.add_argument("--backfill", action="store_true",
                    help="scarica gli archivi storici delle centraline e riaddestra")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="tabella per spot x regime x scadenza: giorni di prova, "
                         "MAE/bias, Brier e calibrazione, errore di orario, "
                         "riferimenti banali e intervalli bootstrap")
    ap.add_argument("--periodo-comune", action="store_true",
                    help="con --validate: misura tutte le scadenze sugli stessi "
                         "giorni, cosi' le righe sono confrontabili fra loro")
    ap.add_argument("--validate-json", metavar="FILE",
                    help="scrive il dettaglio completo della validazione in FILE")
    ap.add_argument("--spot", metavar="NOME", action="append",
                    help="limita --validate/--bands a uno spot (ripetibile)")
    ap.add_argument("--direzioni", action="store_true",
                    help="istogramma delle provenienze osservate: verifica se "
                         "l'asse del regime e' messo nel posto giusto")
    ap.add_argument("--distribuzione", action="store_true",
                    help="dentro la finestra utile: quanto vento, per quanto, "
                         "per ogni soglia candidata. Serve a scegliere le "
                         "soglie guardando i numeri veri.")
    ap.add_argument("--orari", action="store_true",
                    help="climatologia osservata dell'orario di ingresso: regime "
                         "e planata, con e senza filtro di direzione, per mese")
    ap.add_argument("--raffiche", action="store_true",
                    help="analisi descrittiva di media, raffica ricorrente e "
                         "raffica massima: serve a scegliere le soglie sui dati")
    ap.add_argument("--bands", action="store_true",
                    help="confronta tagli di fascia alternativi sul periodo di "
                         "addestramento")
    ap.add_argument("--poll-once", action="store_true",
                    help="interroga le centraline una volta sola ed esce "
                         "(usato dall'agente di raccolta in background)")
    ap.add_argument("--addicted", nargs="?", const=1, type=int, metavar="GIORNI",
                    help="legge la pagina di addicted-sports per Torbole e "
                         "salva la serie oraria misurata (GIORNI indietro, "
                         "compreso oggi; per difetto 1)")
    ap.add_argument("--addicted-audit", action="store_true",
                    help="sonda l'archivio addicted-sports stazione per "
                         "stazione: periodo, cadenza, buchi, unita', semantica "
                         "di mavg/mmax. Salva il grezzo e non ingerisce niente")
    ap.add_argument("--addicted-censimento", action="store_true",
                    help="cammina l'archivio addicted e conta quante giornate "
                         "complete si riesce davvero a scaricare, per stazione")
    ap.add_argument("--addicted-importa", action="store_true",
                    help="ingerisce i raw addicted gia' scaricati nella tabella "
                         "dedicata addicted_hour; non usa la rete")
    ap.add_argument("--addicted-validazione", action="store_true",
                    help="confronta Addicted con T0193 e segnala le parti sicure "
                         "e quelle che non devono ancora entrare nel modello")
    ap.add_argument("--nowcast-validazione", action="store_true",
                    help="valida persistenza intraday e gate del nowcast senza attivarlo")
    ap.add_argument("--analoghi-validazione", action="store_true",
                    help="riproduce la porta della forma analogica Torbole D+1..D+3")
    ap.add_argument("--massimo", type=int, metavar="N",
                    help="limita il censimento alle ultime N richieste "
                         "(per provare senza scaricare dodici anni)")
    ap.add_argument("--stazione", action="append", metavar="SLUG",
                    help="limita l'audit a queste stazioni (ripetibile)")
    ap.add_argument("--live-json", metavar="FILE",
                    help="legge le centraline e scrive SOLO il dato osservato "
                         "in FILE: nessun modello, nessuna previsione. E' il "
                         "processo veloce che tiene aggiornato l'\"adesso\"")
    ap.add_argument("--export", metavar="DIR",
                    help="scrive il cruscotto come pagine statiche in DIR")
    ap.add_argument("--ci", action="store_true",
                    help="ciclo completo non interattivo: raccogli, addestra, esporta "
                         "(pensato per girare in cloud senza il Mac acceso)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    store.init()

    if args.report:
        cmd_report()
        return 0

    if args.validate:
        cmd_validate(spots=args.spot, out_json=args.validate_json,
                     periodo_comune=args.periodo_comune)
        return 0

    if args.orari:
        cmd_orari(args.spot[0] if args.spot else None)
        return 0

    if args.distribuzione:
        cmd_distribuzione(args.spot[0] if args.spot else None)
        return 0

    if args.raffiche:
        cmd_raffiche(args.spot[0] if args.spot else None)
        return 0

    if args.direzioni:
        cmd_direzioni(args.spot[0] if args.spot else None)
        return 0

    if args.bands:
        cmd_bands(args.spot[0] if args.spot else None)
        return 0

    if args.poll_once:
        for line in engine.update_stations():
            print(line)
        return 0

    if args.addicted:
        cmd_addicted(args.addicted)
        return 0

    if args.addicted_censimento:
        cmd_addicted_censimento(stazioni=args.stazione, massimo=args.massimo)
        return 0

    if args.addicted_importa:
        cmd_addicted_importa(stazioni=args.stazione)
        return 0

    if args.nowcast_validazione:
        cmd_nowcast_validazione()
        return 0

    if args.analoghi_validazione:
        cmd_analoghi_validazione()
        return 0

    if args.addicted_validazione:
        cmd_addicted_validazione()
        return 0

    if args.addicted_audit:
        cmd_addicted_audit(stazioni=args.stazione)
        return 0

    if args.live_json:
        # Il processo veloce: legge le centraline e scrive il dato osservato.
        # Separato dalla previsione perche' hanno due tempi diversi - le
        # centraline ogni dieci minuti, i modelli globali ogni sei ore - e
        # finche' stavano insieme il numero dell'"adesso" invecchiava insieme
        # alla previsione, dicendo "adesso" quando erano passate cinque ore.
        from . import live as live_mod
        for line in engine.update_stations():
            print(line)
        dati = live_mod.scrivi(args.live_json)
        for nome, v in sorted(dati["luoghi"].items()):
            print("  %-10s %s  vento %s kn  raffica %s  ricorrente %s (%s)"
                  % (nome, v["ts"] or "-",
                     "-" if v["wind"] is None else "%.1f" % v["wind"],
                     "-" if v["gust"] is None else "%.1f kn" % v["gust"],
                     "-" if v["gust_rec"] is None else "%.1f kn" % v["gust_rec"],
                     v["gust_rec_stato"]))
        print("scritto %s" % args.live_json)
        return 0

    if args.ci:
        from . import export as exporter
        print("Ciclo completo non interattivo.", flush=True)
        engine.update_cycle(force=False, deep=True)
        for line in engine.backfill_station_history(
                force=False, on_progress=lambda m: print(m, flush=True)):
            print("  " + line, flush=True)
        for r in engine.train_all():
            print("  " + json.dumps(r, default=str, ensure_ascii=False), flush=True)
        # La forma analogica non entra nel sito per semplice presenza del codice:
        # il database cloud deve riprodurre il blocco cieco validato.
        ar = analogs.validation_report()
        opened, reasons, _ = analogs.promote_from_validation(ar)
        print("  analoghi: PORTA %s%s" %
              ("APERTA" if opened else "CHIUSA",
               "" if opened else " - " + "; ".join(reasons or [str(ar.get("diagnostic") or ar.get("reason"))])),
              flush=True)
        target = args.export or "site"
        for path in exporter.export(target):
            print("  scritto " + path, flush=True)
        if engine.STATE["errors"]:
            print("Errori durante il ciclo:", flush=True)
            for e in engine.STATE["errors"]:
                print("  " + e, flush=True)
        return 0

    if args.export:
        from . import export as exporter
        for path in exporter.export(args.export):
            print("scritto " + path)
        return 0

    if args.backfill:
        print("Scarico gli archivi storici delle centraline…")
        for line in engine.backfill_station_history(
                force=True, on_progress=lambda m: print(m, flush=True)):
            print("  " + line)
        print("Scarico i predittori storici…")
        for line in engine.backfill_archive_features():
            print("  " + line)
        print("Scarico la rianalisi ERA5 (piu' anni, sola superficie)…")
        for line in engine.backfill_era5_features():
            print("  " + line)
        print("Scarico i predittori per scadenza (run precedenti)…")
        for line in engine.backfill_lead_features():
            print("  " + line)
        print("Addestro…")
        for r in engine.train_all():
            print("  " + json.dumps(r, default=str, ensure_ascii=False))
        return 0

    if args.verify:
        print("Verificati %d accoppiamenti modello/scadenza" % engine.verify_all())
        return 0

    if args.train:
        for r in engine.train_all():
            print(json.dumps(r, default=str, ensure_ascii=False))
        return 0

    httpd = web.serve(args.port)
    threading.Thread(target=engine.poller_loop, daemon=True).start()
    engine.ensure_update(False)
    url = "http://127.0.0.1:%d/" % args.port
    print("%s %s in ascolto su %s" % (config.APP_NAME, config.APP_VERSION, url), flush=True)
    if not args.no_browser:
        _open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
