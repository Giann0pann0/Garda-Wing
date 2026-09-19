#!/usr/bin/env python3
"""Quanto sbaglia la previsione di Addicted, sul NOSTRO bersaglio.

Gian: "quanto siamo efficaci rispetto ai competitors?". Non si sapeva, perche'
non era mai stato misurato: i numeri della diagnostica dicono quanto siamo
meglio di noi stessi senza modello, non di qualcun altro.

Addicted rende il confronto possibile come nessun altro: nella stessa risposta
pubblicano la LORO previsione oraria ("avg") e la MISURA della stessa ora
("mavg"), giorno per giorno, anche all'indietro. Questo strumento le scarica e
calcola il loro errore sul bersaglio che usiamo noi.

QUATTRO SCELTE, dichiarate prima di guardare i numeri:

  1. IL BERSAGLIO e' il picco della media oraria dentro la finestra del
     regime, non la media di tutte le 24 ore. Il loro MAE dichiarato (1,3 kn a
     Torbole) e' su tutte le ore, notte compresa: le ore facili, quelle in cui
     il vento e' 0-2 kn e sbagliare e' difficile. Un confronto su quel numero
     sarebbe un confronto fra un esame facile e uno difficile.

  2. SOLO LE GIORNATE ENTRATE, cioe' quelle in cui il vento c'e' stato
     davvero. Sbagliare una giornata senza vento non interessa a nessuno.

  3. TUTTO SULLA SCALA METEOTRENTINO, con la curva misurata su 62.847 ore con
     i due strumenti fianco a fianco a Torbole. Serve perche' i nostri numeri
     sono su quella scala. Il BIAS pero' si stampa anche sulla loro scala
     grezza: e' l'unico modo di dire "sottostimano" senza che la nostra
     conversione possa essere la causa di quello che troviamo.

  4. IL BIAS TOLTO IN LEAVE-ONE-OUT: per ogni giornata si corregge con la
     mediana degli errori di TUTTE LE ALTRE. Correggere con la mediana che
     include il giorno che si sta prevedendo sarebbe sbirciare la risposta, ed
     e' il modo piu' comune di far sembrare bravo un modello che non lo e'.

QUELLO CHE QUESTO STRUMENTO NON DICE, e va scritto accanto a ogni numero che
produce: non e' ancora un confronto diretto con noi. Il nostro MAE pubblicato
e' misurato su circa 1.800 giornate che comprendono l'inverno e sulla finestra
UTILE; questo e' su un'estate e sulla finestra del regime. L'estate e' la
stagione facile. Per il confronto stretto servono le stesse giornate e la
stessa definizione - vedi docs/CONFRONTO-ADDICTED.md.

E non sappiamo a quale SCADENZA fosse emessa la previsione che loro
ripubblicano per i giorni passati. Il confronto a prova di obiezione si fa in
avanti, archiviando ogni giorno la loro previsione a scadenza dichiarata.

Uso:
    python3 strumenti/confronto-addicted.py                     # ultimi 100 giorni
    python3 strumenti/confronto-addicted.py --da 2026-06-15 --a 2026-09-18
    python3 strumenti/confronto-addicted.py --json coppie.json  # salva i dati grezzi
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gardawind import config                                     # noqa: E402
from gardawind.sources import addicted                           # noqa: E402
from gardawind.sources.http import FetchError, fetch_text        # noqa: E402
from gardawind.util import riscala                               # noqa: E402

# La soglia del "si plana" e la finestra di ogni regime vengono da config: se
# un domani cambiano li', questo strumento cambia con loro.
PLANA_KN = 14.0
PAUSA_S = 0.4          # fra una richiesta e l'altra: non e' il nostro server


def spot_di(slug):
    """[(nome dello spot, finestra, soglia)] per la stazione Addicted `slug`."""
    out = []
    for nome, s in config.SPOTS.items():
        if s.get("addicted_slug") == slug or (slug == "torbole"
                                              and s["station"] == "T0193"):
            if s["target"] != "hourly":
                continue
            out.append((nome, s["window"], s["min_kn"]))
    return out


def scarica(slug, dal, al):
    """{giorno: {ora: [(h, previsto, misurato)]}} dalla pagina di Addicted."""
    per_giorno = {}
    cursore = dal
    while cursore <= al:
        url = addicted.url_json(cursore.isoformat(), slug)
        try:
            dati = json.loads(fetch_text(url, timeout=45))
        except (ValueError, FetchError) as e:
            print("  ! %s %s: %s" % (slug, cursore, str(e)[:80]))
            cursore += dt.timedelta(days=3)
            time.sleep(PAUSA_S)
            continue
        tempi = dati.get("time") or []
        prev = dati.get("avg") or []
        mis = dati.get("mavg") or []
        for i, etichetta in enumerate(tempi):
            gg = _giorno_e_ora(etichetta, cursore.year)
            if not gg:
                continue
            giorno, ora = gg
            p = prev[i] if i < len(prev) else None
            m = mis[i] if i < len(mis) else None
            if p is None and m is None:
                continue
            per_giorno.setdefault(giorno, []).append((ora, p, m))
        cursore += dt.timedelta(days=3)
        time.sleep(PAUSA_S)
    return per_giorno


def _giorno_e_ora(etichetta, anno):
    """"sab 12.09. 10:00" -> ("2026-09-12", 10). L'orario e' quello civile."""
    try:
        pezzi = etichetta.split()
        gm = pezzi[1].strip(".").split(".")
        return "%04d-%02d-%02d" % (anno, int(gm[1]), int(gm[0])), int(pezzi[2].split(":")[0])
    except (AttributeError, IndexError, ValueError):
        return None


def picchi(per_giorno, finestra):
    """[(giorno, picco previsto, picco misurato)] dentro la finestra."""
    h0, h1 = finestra
    out = []
    for giorno, righe in sorted(per_giorno.items()):
        dentro = [(p, m) for h, p, m in righe if h0 <= h <= h1]
        pp = [p for p, _m in dentro if p is not None]
        mm = [m for _p, m in dentro if m is not None]
        if not pp or not mm:
            continue
        out.append((giorno, max(pp), max(mm)))
    return out


def su_scala(coppie):
    curva = config.SCALA_ADDICTED_A_MT
    return [(g, riscala(curva, p), riscala(curva, m)) for g, p, m in coppie]


def _loo_mediana(valori, i):
    altri = [v for j, v in enumerate(valori) if j != i]
    return statistics.median(altri) if altri else 0.0


def misura(coppie_scala, soglia_ingresso, coppie_grezze):
    """I numeri, con il bias tolto in leave-one-out."""
    ent = [(g, p, m) for g, p, m in coppie_scala if m >= soglia_ingresso]
    if len(ent) < 20:
        return None
    err = [p - m for _g, p, m in ent]
    giorni_ent = {g for g, _p, _m in ent}
    grezzi = [(p, m) for g, p, m in coppie_grezze if g in giorni_ent]
    senza_bias = [abs((p - _loo_mediana(err, i)) - m)
                  for i, (_g, p, m) in enumerate(ent)]
    misurati = [m for _g, _p, m in ent]
    clim = [abs(_loo_mediana(misurati, i) - m) for i, m in enumerate(misurati)]
    buone = [(p, m) for _g, p, m in ent if m >= PLANA_KN]
    return {
        "n": len(ent),
        "mae": statistics.mean(abs(e) for e in err),
        "bias": statistics.mean(err),
        "bias_grezzo": (statistics.mean(p - m for p, m in grezzi)
                        if grezzi else None),
        "mae_senza_bias": statistics.mean(senza_bias),
        "mae_clim": statistics.mean(clim),
        "buone": len(buone),
        "mancate": sum(1 for p, m in buone if p < PLANA_KN),
        "falsi": sum(1 for _g, p, m in ent if p >= PLANA_KN and m < PLANA_KN),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    oggi = dt.date.today()
    ap.add_argument("--da", default=(oggi - dt.timedelta(days=100)).isoformat())
    ap.add_argument("--a", default=(oggi - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--json", help="salva le coppie grezze in questo file")
    args = ap.parse_args()
    dal, al = dt.date.fromisoformat(args.da), dt.date.fromisoformat(args.a)

    slug = []
    for s in config.SPOTS.values():
        k = s.get("addicted_slug") or ("torbole" if s["station"] == "T0193" else None)
        if k and k not in slug:
            slug.append(k)

    raccolto = {}
    print("Dal %s al %s, stazioni: %s" % (dal, al, ", ".join(slug)))
    for k in slug:
        print("  scarico %s..." % k, flush=True)
        raccolto[k] = scarica(k, dal, al)

    print("\n%-12s %-7s %4s  %5s %6s %7s  %6s %6s   %s"
          % ("stazione", "regime", "n", "MAE", "bias", "b.grezzo",
             "s.bias", "clim", "buone mancate / falsi"))
    tutto = {}
    for k in slug:
        for nome, finestra, minkn in spot_di(k):
            grezze = picchi(raccolto[k], finestra)
            if not grezze:
                continue
            m = misura(su_scala(grezze), minkn, grezze)
            tutto[nome] = {"coppie": grezze, "misura": m}
            if not m:
                print("%-12s %-7s  poche giornate" % (k, nome))
                continue
            print("%-12s %-7s %4d  %5.2f %+6.2f %+7.2f  %6.2f %6.2f   %d/%d, %d falsi"
                  % (k, nome.split("-")[1], m["n"], m["mae"], m["bias"],
                     m["bias_grezzo"] if m["bias_grezzo"] is not None else float("nan"),
                     m["mae_senza_bias"], m["mae_clim"],
                     m["mancate"], m["buone"], m["falsi"]))
    print("\nMAE e bias in nodi sulla scala Meteotrentino; 'b.grezzo' e' il bias\n"
          "sulla scala loro, che non passa dalla nostra conversione.\n"
          "'s.bias' e' il MAE dopo aver tolto il bias in leave-one-out: e' la\n"
          "loro abilita' separata dalla loro taratura.\n"
          "'buone mancate' = giornate misurate sopra i %g kn che la loro\n"
          "previsione dava sotto." % PLANA_KN)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({n: v["coppie"] for n, v in tutto.items()}, fh)
        print("scritte le coppie grezze in %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
