"""Limone: quanto vale la centralina viva, misurato contro quella morta.

Da lanciare UNA volta, sul Mac di Gian:

    cd ~/Downloads/garda-wind && python3 strumenti/estrai-limone.py

Cosa fa, e perche'.

A Limone abbiamo due sensori e nessuno dei due basta da solo. Capo Reamol
(Addicted) ha undici anni di storico ed e' morta a marzo 2025. Il Consorzio
Turistico (MeteoSystem) e' viva ma il suo archivio parte da settembre 2022.
In mezzo ci sono due anni e mezzo in cui hanno misurato ENTRAMBE lo stesso
vento: e' li' che si misura il legame fra le due, una volta sola.

Tre domande, in quest'ordine, e nessuna si risponde a occhio:

  1. l'UNITA'. La pagina di Limone dice km/h, quella di Malcesine nodi. Se
     fosse sbagliata, il rapporto fra i due sensori verrebbe fuori vicino a
     1,85 (o a 0,54) invece che vicino a 1: il numero lo dice da se'.
  2. la SCALA. Come per Addicted contro Meteotrentino: un fattore per
     livello di vento, non un numero secco, perche' i sensori riparati
     perdono di piu' quando tira.
  3. la COPERTURA: quante ore, quanti buchi, e se il ciclo diurno di Limone
     somiglia a quello del resto dell'alto lago.

Scarica solo i mesi che servono, uno per richiesta, e li tiene in archivio
(obs_sample, fonte "meteosystem-intraday"): rilanciandolo non riscarica
quello che ha gia'.
"""
import datetime as dt
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gardawind import aggregate, config, store
from gardawind.sources import davis_csv
from gardawind.sources.http import FetchError
from gardawind.util import local_hour, parse_dt_any

STAZIONE = "limone"
FONTE = "meteosystem-intraday"
# La sovrapposizione con Capo Reamol: da quando esiste l'archivio di Limone a
# quando la centralina di Capo Reamol ha smesso.
DAL = (2022, 9)
AL = (2025, 3)


def scarica():
    store.init()
    gia = set()
    for r in store.connect().execute(
            "SELECT DISTINCT substr(ts,1,7) FROM obs_sample WHERE station=?",
            (STAZIONE,)):
        gia.add(r[0])
    mesi = []
    y, m = DAL
    while (y, m) <= AL:
        mesi.append((m, y))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    fatti = 0
    for m, y in mesi:
        if "%04d-%02d" % (y, m) in gia:
            continue
        try:
            import calendar
            ultimo = calendar.monthrange(y, m)[1]
            righe = davis_csv.fetch_intervallo(
                config.URL_LIMONE_BASE, dt.date(y, m, 1), dt.date(y, m, ultimo),
                config.LIMONE_UNITA)
        except FetchError as e:
            print("  %02d/%d: non disponibile (%s)" % (m, y, str(e)[:60]))
            continue
        store.save_samples(STAZIONE, righe, FONTE)
        fatti += 1
        print("  %02d/%d: %d misure" % (m, y, len(righe)))
    if fatti:
        aggregate.aggregate_station(STAZIONE)
    return fatti


def ore(stazione, tabella="obs_hour"):
    if tabella == "obs_hour":
        q = ("SELECT hour, wind_mean, gust_max FROM obs_hour WHERE station=? "
             "AND wind_mean IS NOT NULL")
    else:
        q = ("SELECT hour, wind_mean_kn, hourly_max_kn FROM addicted_hour "
             "WHERE station=? AND wind_mean_kn IS NOT NULL")
    return {r[0][:13]: (r[1], r[2]) for r in store.connect().execute(q, (stazione,))}


def loc(h):
    d = parse_dt_any(h + ":00:00Z")
    return local_hour(d) if d else None


def q(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))] if v else float("nan")


def main():
    print("=" * 72)
    print("  LIMONE - la centralina viva misurata contro quella morta")
    print("=" * 72)
    print("\nScarico l'archivio MeteoSystem (%02d/%d -> %02d/%d), un mese per volta."
          % (DAL[1], DAL[0], AL[1], AL[0]))
    scarica()

    L = ore(STAZIONE)
    C = ore("caporeamol", "addicted_hour")
    comuni = [h for h in L if h in C]
    print("\nCOPERTURA")
    print("  MeteoSystem Limone : %6d ore  %s -> %s"
          % (len(L), min(L)[:10] if L else "-", max(L)[:10] if L else "-"))
    print("  Capo Reamol        : %6d ore  %s -> %s"
          % (len(C), min(C)[:10] if C else "-", max(C)[:10] if C else "-"))
    print("  in comune          : %6d ore" % len(comuni))
    if len(comuni) < 200:
        print("\n  Troppo poche per misurare: mi fermo qui.")
        return 1

    forti = [h for h in comuni if C[h][0] >= 8]
    rap = [L[h][0] / C[h][0] for h in forti if C[h][0] > 0.5 and L[h][0] > 0.5]
    print("\n1. L'UNITA'")
    print("  rapporto Limone/CapoReamol sopra gli 8 kn: mediana %.2f  [25-75%%: %.2f-%.2f]"
          % (st.median(rap), q(rap, .25), q(rap, .75)))
    print("  atteso ~1 se l'unita' dichiarata (%s) e' giusta;" % config.LIMONE_UNITA)
    print("  ~1,85 o ~0,54 se e' sbagliata di un fattore km/h-nodi.")

    print("\n2. LA SCALA (lettura Limone -> mediana di Capo Reamol, gia' in nodi)")
    print("   scalino    n      Limone   CapoReamol   fattore")
    for lo, hi in ((0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 99)):
        r = [(L[h][0], C[h][0]) for h in comuni if lo <= L[h][0] < hi]
        if len(r) < 40:
            continue
        print("   %2d-%2d  %5d   %6.1f     %6.1f       x%.2f"
              % (lo, min(hi, 30), len(r), st.median([a for a, _ in r]),
                 st.median([b for _, b in r]),
                 st.median([b / a for a, b in r if a > 0.5])))
    print("\n   curva a scalini di 2 kn, come per la scala comune:")
    punti, m = [], 0.0
    for lo in range(0, 24, 2):
        r = [C[h][0] for h in comuni if lo <= L[h][0] < lo + 2]
        if len(r) >= 60:
            m = max(m, st.median(r))
            punti.append((lo + 1.0, round(m, 1), len(r)))
    print("   SCALA_LIMONE = (" + ", ".join("(%.1f, %.1f)" % (a, b) for a, b, _ in punti) + ")")
    print("   n per punto: " + ", ".join(str(n) for _, _, n in punti))

    print("\n3. IL CICLO DIURNO (mediana del vento per ora locale, mesi 4-10)")
    for nome, S in (("Limone (MeteoSystem)", L), ("Capo Reamol (Addicted)", C)):
        per_ora = {}
        for h, (w, _g) in S.items():
            if 4 <= int(h[5:7]) <= 10:
                per_ora.setdefault(loc(h), []).append(w)
        riga = " ".join("%02d:%4.1f" % (o, st.median(v))
                        for o, v in sorted(per_ora.items())
                        if o is not None and 5 <= o <= 20 and len(v) >= 20)
        print("  %-22s %s" % (nome, riga))

    buchi = {}
    for h in L:
        buchi.setdefault(h[:7], 0)
        buchi[h[:7]] += 1
    scarsi = sorted(k for k, v in buchi.items() if v < 500)
    print("\n4. I MESI INCOMPLETI (meno di 500 ore su ~720): %s"
          % (", ".join(scarsi) if scarsi else "nessuno"))
    print("\nFine. Incolla tutto a Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
