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
    python3 -m gardawind --export DIR    scrive il cruscotto come sito statico
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser

from . import config, engine, store, web
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
                ing = sustained_onset(sr, float(t), persist_min=30.0,
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

        tot = C["n_giorni"] + C["n_non_stimabili"]
        print("")
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
