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
    python3 -m gardawind --poll-once     legge le centraline una volta ed esce
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
    from gardawind.util import (covered_minutes, effective_window, median,
                                recurrent_gust, sampling_cadence,
                                sustained_onset, time_above)

    spots = [spot_name] if spot_name else [
        n for n in config.SPOT_ORDER if config.SPOTS[n]["target"] == "hourly"]
    MIN_GIORNI_Q = 30           # sotto, nessun quantile: vedi riga_q
    MIN_COPERTURA_MIN = 120.0   # due ore dentro la finestra del regime

    def q(xs, p):
        y = sorted(xs)
        return y[min(len(y) - 1, max(0, int(p * (len(y) - 1))))] if y else float("nan")

    def riga_q(etichetta, dati):
        if len(dati) < MIN_GIORNI_Q:
            return ("  %-22s   %d giornate: troppe poche per dei quantili"
                    % (etichetta, len(dati)))
        return ("  %-22s %7.1f %7.1f %7.1f %7.1f %7.1f"
                % (etichetta, q(dati, .10), q(dati, .50), q(dati, .75),
                   q(dati, .90), q(dati, .99)))

    for name in spots:
        spot = config.SPOTS[name]
        station = spot["station"]
        h0, h1 = spot["window"]
        print("")
        print("=" * 74)
        print("  %s  -  finestra %02d:00-%02d:00  -  centralina %s"
              % (name, h0, h1 + 1, station))
        print("=" * 74)

        per_giorno = {}
        tempi = []
        n_camp = n_gust = 0
        for s in store.samples_since(station, "0000"):
            dt_ = parse_dt_any(s["ts"])
            if dt_ is None or s["wind_kn"] is None:
                continue
            loc = to_local(dt_)
            minuti = loc.hour * 60.0 + loc.minute
            per_giorno.setdefault(local_day(dt_), []).append(
                (minuti, s["wind_kn"], s["gust_kn"]))
            tempi.append(dt_.timestamp() / 60.0)
            n_camp += 1
            if s["gust_kn"] is not None:
                n_gust += 1

        if not per_giorno:
            print("  nessun campione per questa centralina.")
            continue

        cadenza = sampling_cadence(tempi) or 0.0
        finestra = effective_window(cadenza)
        gg_con_raffica = sum(1 for v in per_giorno.values()
                             if any(g is not None for _m, _w, g in v))
        print("")
        print("  archivio: %d campioni su %d giornate, cadenza tipica %g min"
              % (n_camp, len(per_giorno), cadenza))
        print("  raffica presente su %d campioni (%.1f%%) e %d giornate"
              % (n_gust, 100.0 * n_gust / n_camp, gg_con_raffica))
        print("  finestra della mediana mobile: %g min (tre campioni a questa "
              "cadenza)" % finestra)
        if gg_con_raffica == 0:
            print("  -> raffica storica NON disponibile per questa centralina.")
        elif gg_con_raffica < 0.5 * len(per_giorno):
            print("  -> raffica storica disponibile solo di recente: il secondo")
            print("     blocco parla di %d giornate, non di %d."
                  % (gg_con_raffica, len(per_giorno)))

        # ---- livello 1: il vento medio, su TUTTO lo storico ----
        medie, durate_m = [], {}
        for t in (spot["min_kn"], spot["planing_kn"]):
            durate_m[t] = []
        gg_validi = 0
        for day in sorted(per_giorno):
            righe = sorted(per_giorno[day])
            sel = [(m, w, g) for m, w, g in righe if h0 * 60 <= m <= (h1 + 1) * 60]
            if covered_minutes([m for m, _w, _g in sel], cadenza) < MIN_COPERTURA_MIN:
                continue
            gg_validi += 1
            ws = [w for _m, w, _g in sel if w is not None]
            if ws:
                medie.append(max(ws))
            serie_w = [(m, w) for m, w, _g in sel if w is not None]
            for t in durate_m:
                durate_m[t].append(time_above(serie_w, float(t), cadenza))

        print("")
        print("  VENTO MEDIO  -  %d giornate con almeno due ore di copertura"
              % gg_validi)
        print("  %-22s %7s %7s %7s %7s %7s"
              % ("picco del giorno", "q10", "mediana", "q75", "q90", "q99"))
        print(riga_q("vento medio", medie))
        for t in sorted(durate_m):
            d = [x for x in durate_m[t] if x > 0]
            etichetta = ("soglia di regime" if abs(t - spot["min_kn"]) < 1e-9
                         else "soglia di planata")
            if d:
                print("  sopra %2g kn (%s): %d giornate (%.0f%%), mediana %.0f min"
                      % (t, etichetta, len(d), 100.0 * len(d) / max(1, gg_validi),
                         median(d) or 0))

        # ---- livello 2: la raffica, solo dove c'e' ----
        ric, massime, rapporti = [], [], []
        durate_g = {t: [] for t in soglie}
        ingressi = {t: [] for t in soglie}
        gg_raffica = 0
        for day in sorted(per_giorno):
            righe = sorted(per_giorno[day])
            if not any(g is not None for _m, _w, g in righe):
                continue
            serie_ric = recurrent_gust([(m, g) for m, _w, g in righe],
                                       window_min=30.0, centered=True,
                                       cadence_min=cadenza)
            sel = [(m, w, g, r) for (m, w, g), (_m2, r) in zip(righe, serie_ric)
                   if h0 * 60 <= m <= (h1 + 1) * 60]
            if covered_minutes([m for m, _w, _g, _r in sel], cadenza) < MIN_COPERTURA_MIN:
                continue
            gg_raffica += 1
            gs = [g for _m, _w, g, _r in sel if g is not None]
            rs = [r for _m, _w, _g, r in sel if r is not None]
            ws = [w for _m, w, _g, _r in sel if w is not None]
            if gs:
                massime.append(max(gs))
            if rs:
                ric.append(max(rs))
                if ws and max(ws) > 0.5:
                    rapporti.append(max(rs) / max(ws))
            sr = [(m, r) for m, _w, _g, r in sel if r is not None]
            for t in soglie:
                durate_g[t].append(time_above(sr, float(t), cadenza))
                ing = sustained_onset(sr, float(t), persist_min=30.0,
                                      cadence_min=cadenza)
                if ing is not None:
                    ingressi[t].append(ing)

        print("")
        if gg_raffica == 0:
            print("  RAFFICA  -  non disponibile su questa centralina.")
            print("  Non e' vento assente: e' misura assente. Si accumula da")
            print("  qui in avanti, e questo blocco comparira' da solo.")
            continue

        print("  RAFFICA  -  %d giornate (finestra ricorrente %g min)"
              % (gg_raffica, finestra))
        print("  %-22s %7s %7s %7s %7s %7s"
              % ("picco del giorno", "q10", "mediana", "q75", "q90", "q99"))
        print(riga_q("raffica ricorrente", ric))
        print(riga_q("raffica massima", massime))
        if len(rapporti) >= MIN_GIORNI_Q:
            print("  rapporto ricorrente/media   mediana %.2f   q10 %.2f   q90 %.2f"
                  % (q(rapporti, .5), q(rapporti, .1), q(rapporti, .9)))
        elif rapporti:
            print("  rapporto ricorrente/media: %d giornate, troppe poche"
                  % len(rapporti))

        if not ric:
            print("")
            print("  Tabella delle durate non prodotta: la raffica ricorrente non")
            print("  e' calcolabile a questa cadenza. Ogni riga direbbe \"0\",")
            print("  che si legge \"non c'e' mai vento\" e invece vuol dire")
            print("  \"non l'abbiamo misurato\".")
            continue

        print("")
        print("  quanto durano le soglie, sulla RAFFICA RICORRENTE")
        print("  %6s %9s %11s %12s %12s %14s"
              % ("soglia", "giornate", "% giornate", "durata med.", "durata q75",
                 "ingresso >=30'"))
        for t in soglie:
            d = [x for x in durate_g[t] if x > 0]
            perc = 100.0 * len(d) / gg_raffica if gg_raffica else 0.0
            ing = ingressi[t]
            if ing:
                mm = median(ing) or 0
                ora = "%02d:%02d" % (int(mm // 60) % 24, int(mm % 60))
            else:
                ora = "-"
            print("  %6d %9d %10.0f%% %8.0f min %8.0f min %14s"
                  % (t, len(d), perc, median(d) or 0,
                     q(d, .75) if d else 0, ora))
        print("")
        print("  Le soglie qui NON sono decise: sono candidate. La colonna che")
        print("  conta e' la durata - una soglia superata per venti minuti e'")
        print("  un colpo di vento, non una sessione.")


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
    ap.add_argument("--raffiche", action="store_true",
                    help="analisi descrittiva di media, raffica ricorrente e "
                         "raffica massima: serve a scegliere le soglie sui dati")
    ap.add_argument("--bands", action="store_true",
                    help="confronta tagli di fascia alternativi sul periodo di "
                         "addestramento")
    ap.add_argument("--poll-once", action="store_true",
                    help="interroga le centraline una volta sola ed esce "
                         "(usato dall'agente di raccolta in background)")
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
