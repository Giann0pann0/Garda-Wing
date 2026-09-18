"""Un lettore solo per le due centraline Davis, e l'unita' dichiarata.

La Fraglia di Malcesine e il Consorzio di Limone pubblicano con lo stesso
pacchetto: stessi indirizzi, stesse colonne, stessi indici. Verificato
scaricando un giorno da entrambe - le due intestazioni vere stanno qui sotto.

Tre cose da difendere:

  1. il lettore e' uno: malcesine.py non ha piu' un parser suo;
  2. l'unita' e' un parametro OBBLIGATORIO, perche' le due non l'hanno uguale
     (nodi a Malcesine, km/h a Limone) e un fattore 1,852 preso al contrario
     lascia numeri plausibili e sbagliati;
  3. le differenze vere fra i due file - il mese a una cifra, l'accento
     nell'intestazione NOAA - sono gestite in un posto solo.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gardawind import config
from gardawind.sources import davis_csv, malcesine
from gardawind.util import parse_dt_any, to_local

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


# Le intestazioni VERE, copiate dallo scarico del 2026-09-18.
CSV_LIMONE = (
    'Data;Ora;Temp;Max;Min;Ur%;"Dew pt";Vento;Dir;Raffica;"Dir Raff.";Press;'
    'Pioggia;"Int Piog."\n'
    "15/9/2026;0:00;23.1;23.2;23.1;65;16.1;1.6;W;6.4;W;1022.4;0.0;0.0\n"
    "15/9/2026;14:30;25.0;25.2;24.9;60;16.0;18.52;SSW;37.04;SSW;1021.0;0.0;0.0\n"
)
CSV_MALCESINE = (
    'Data;Ora;Temp;Min;Max;Umid;"Dew pt";Vento;Dir;Raffica;"Dir Raff.";Press;'
    "Pioggia;Int.Pio.;Rad.Sol.\n"
    "15/09/2026;14:30;25.0;24.9;25.2;60;16.0;10.0;SSW;20.0;SSW;1021.0;0.0;0.0;500\n"
)
NOAA_LIMONE = (
    'Data;"Temp media";Min;"Ora Min";Max;"Ora Max";"UR media";Pioggia;'
    '"Vento medio";Raffica;"Dir Dom"\n'
    "1;27.0;24.8;8:00;29.4;15:15;55;0.0;18.52;37.04;WNW\n"
)

chiamate = []


def finto(testo):
    def _f(url, params=None, timeout=None):
        chiamate.append((url, dict(params or {})))
        return testo
    return _f


# ---- l'unita' e' obbligatoria ----------------------------------------------
davis_csv.fetch_text = finto(CSV_LIMONE)
try:
    davis_csv.fetch_intervallo(config.URL_LIMONE_BASE, dt.date(2026, 9, 15),
                               dt.date(2026, 9, 15), "nodi?")
    ok(False, "un'unita' sconosciuta deve fermare la lettura")
except ValueError as e:
    ok("unita'" in str(e), "un'unita' sconosciuta ferma la lettura: %s" % str(e)[:50])

# ---- km/h: i numeri si convertono, e si vede ------------------------------
righe = davis_csv.fetch_intervallo(config.URL_LIMONE_BASE, dt.date(2026, 9, 15),
                                   dt.date(2026, 9, 15), "kmh")
ok(len(righe) == 2, "due righe lette dal CSV di Limone (%d)" % len(righe))
ts, w, g, d = righe[-1]
ok(abs(w - 10.0) < 0.01 and abs(g - 20.0) < 0.01,
   "18,52 km/h diventano 10,0 kn e 37,04 diventano 20,0 (%.2f, %.2f)" % (w, g))
ok(abs(d - 202.5) < 0.01, "SSW diventa 202,5 gradi")
ok(to_local(parse_dt_any(ts)).strftime("%d/%m %H:%M") == "15/09 14:30",
   "e l'orario e' quello civile italiano, con il mese a una cifra sola")
ok(chiamate[-1][0].endswith("/csv.php")
   and chiamate[-1][1]["gg2"] == "15" and chiamate[-1][1]["aa"] == "26",
   "l'indirizzo e i parametri sono quelli del pacchetto: %s" % chiamate[-1][1])

# ---- nodi: gli stessi numeri restano ---------------------------------------
davis_csv.fetch_text = finto(CSV_MALCESINE)
righe = davis_csv.fetch_intervallo(config.URL_MALCESINE_BASE, dt.date(2026, 9, 15),
                                   dt.date(2026, 9, 15), "kn")
ts2, w2, g2, _d2 = righe[0]
ok(abs(w2 - 10.0) < 0.01 and abs(g2 - 20.0) < 0.01,
   "a Malcesine 10 kn restano 10 kn: stessa riga, unita' diversa, stesso esito")
ok(ts2 == ts, "e lo stesso istante, nonostante i due modi di scrivere la data")

# ---- il NOAA mensile, con l'intestazione di Limone -------------------------
davis_csv.fetch_text = finto(NOAA_LIMONE)
giorni = davis_csv.fetch_noaa(config.URL_LIMONE_BASE, 9, 2026, "kmh")
ok(len(giorni) == 1 and giorni[0][0] == "2026-09-01",
   "il report NOAA da' una riga per giorno, con la data intera")
ok(abs(giorni[0][1] - 10.0) < 0.01 and abs(giorni[0][2] - 20.0) < 0.01,
   "convertita anche qui (%.1f, %.1f)" % (giorni[0][1], giorni[0][2]))
ok(giorni[0][3] == 292.5, "e la direzione dominante letta dal punto cardinale")
ok(chiamate[-1][1]["mesi"] == "09-2026", "chiesto come vuole il pacchetto: mesi=MM-AAAA")

# L'intestazione NOAA e' l'unica differenza vera fra i due file: la Fraglia
# scrive "Avg Vento", Limone "Vento medio". Una chiave non riconosciuta qui
# vorrebbe dire un mese letto come vuoto, in silenzio.
NOAA_FRAGLIA = ('Data;Avg;Min;"Ora Min";Max;"Ora Max";"Avg UR";"Avg Rad";Pioggia;'
                '"Avg Vento";Raffica;"Dir Dom"\n'
                "1;27.7;21.4;6.0;32.9;16:00;65;;2.8;8.0;26.1;ENE\n")
davis_csv.fetch_text = finto(NOAA_FRAGLIA)
g2 = davis_csv.fetch_noaa(config.URL_MALCESINE_BASE, 8, 2026, "kn")
ok(g2 and g2[0][1] == 8.0 and g2[0][2] == 26.1,
   "l'intestazione della Fraglia viene letta come quella di Limone: %s" % (g2[0],))

# ---- un posto solo ---------------------------------------------------------
import inspect

src = inspect.getsource(malcesine)
ok("COL_WIND" not in src and "_RE_ROW" not in src,
   "malcesine.py non ha piu' un parser suo del CSV")
ok('davis_csv.fetch_intervallo(config.URL_MALCESINE_BASE' in src
   and 'davis_csv.fetch_noaa(config.URL_MALCESINE_BASE' in src,
   "e chiama il lettore comune, con il suo indirizzo e la sua unita'")
ok('"kn"' in src and '"kmh"' not in src,
   "dichiarando i nodi, che sono i suoi")
ok(config.LIMONE_UNITA == "kmh",
   "mentre Limone dichiara i km/h, come scrive la sua pagina")
ok(davis_csv.mesi_da((2026, 7), dt.date(2026, 9, 18)) == [(9, 2026), (8, 2026), (7, 2026)],
   "i mesi da coprire si contano all'indietro dal piu' recente")

# Limone non e' ancora una localita': prima la misura della scala.
ok("Limone" not in config.PLACES,
   "Limone non entra in pagina finche' il legame fra i due sensori non e' misurato")
print("%d controlli sul lettore Davis" % passati)
