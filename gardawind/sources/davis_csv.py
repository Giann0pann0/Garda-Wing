"""Le centraline Davis con l'impianto CSV: un lettore solo, due clienti.

La Fraglia Vela di Malcesine (MeteoProject) e la centralina del Consorzio
Turistico di Limone (MeteoSystem) pubblicano con lo STESSO pacchetto: stessi
indirizzi - csv.php con le date, csvnoaa.php?mesi=MM-AAAA - e stesse colonne,
negli stessi posti:

    Data;Ora;Temp;Max;Min;Ur%;"Dew pt";Vento;Dir;Raffica;"Dir Raff.";Press;...
                                          7    8     9        10

Verificato scaricando un giorno da entrambe. Quindi il lettore e' uno, e i due
posti sono due chiamate con un indirizzo diverso. Scriverne due avrebbe voluto
dire correggere due volte ogni difetto trovato - e il difetto trovato finora,
la data col mese a una cifra (15/9/2026 a Limone, 15/09/2026 a Malcesine), e'
esattamente il genere di cosa che in due copie si sistema in una sola.

L'UNITA' non e' la stessa e non si indovina: Malcesine dichiara i nodi,
Limone i km/h. E' un parametro obbligatorio, dichiarato da chi chiama, perche'
un fattore 1,852 preso per buono al contrario e' il modo piu' silenzioso di
sbagliare di tutto - il numero resta plausibile e nessuno se ne accorge.
"""

import csv
import datetime as _dt
import io
import re

from ..util import KN_PER_KMH, iso_utc, num, serie_locale_to_utc
from .http import FetchError, fetch_text

MAX_WIND_KN = 60.0
MAX_GUST_KN = 85.0

# Le colonne dell'intraday, per indice: sono le stesse nei due impianti.
COL_WIND, COL_DIR, COL_GUST, COL_GUSTDIR = 7, 8, 9, 10

# "15/9/2026;0:15;..." oppure "15/09/2026;00:15;...": il mese e l'ora possono
# avere una cifra sola.
_RE_ROW = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4});(\d{1,2}):(\d{2});")

COMPASS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SO": 202.5,
    "SW": 225.0, "WSW": 247.5, "OSO": 247.5, "W": 270.0, "O": 270.0,
    "WNW": 292.5, "NW": 315.0, "NO": 315.0, "NNW": 337.5,
}

UNITA = {"kn": 1.0, "kmh": KN_PER_KMH}


def _fattore(unita):
    if unita not in UNITA:
        raise ValueError("unita' non dichiarata: %r (attese: %s)"
                         % (unita, ", ".join(sorted(UNITA))))
    return UNITA[unita]


def fetch_intervallo(base_url, dal, al, unita):
    """Le misure fra due giorni locali (date). Stessa forma di fetch_live:
    (timestamp_utc, vento_kn, raffica_kn, direzione)."""
    f = _fattore(unita)
    params = {
        "gg2": "%02d" % dal.day, "mm2": "%02d" % dal.month,
        "aa2": "%02d" % (dal.year % 100),
        "gg": "%02d" % al.day, "mm": "%02d" % al.month,
        "aa": "%02d" % (al.year % 100),
    }
    text = fetch_text(base_url + "csv.php", params, timeout=90)
    if not text or text.lstrip().startswith("<"):
        raise FetchError("archivio intraday %s..%s non disponibile" % (dal, al))

    # Prima gli orologi da parete, TUTTI INSIEME: l'ultima domenica di ottobre
    # le 02:00-02:59 italiane esistono due volte e il file le scrive due volte
    # uguali. Convertite una per una finirebbero sullo stesso istante UTC, e
    # con INSERT OR REPLACE la seconda cancellerebbe la prima. In serie,
    # l'ordine delle righe dice qual e' il secondo passaggio.
    grezze = []
    for line in text.splitlines():
        m = _RE_ROW.match(line.strip())
        if not m:
            continue
        parts = line.split(";")
        if len(parts) <= COL_GUSTDIR:
            continue
        d, mo, y, hh, mi = (int(x) for x in m.groups())
        naive = _dt.datetime(y, mo, d, hh % 24, mi)
        if hh >= 24:
            naive += _dt.timedelta(days=1)
        grezze.append((naive, parts))
    istanti = serie_locale_to_utc([n for n, _p in grezze])

    out = []
    for (naive, parts), stamp in zip(grezze, istanti):
        if stamp is None:
            continue
        wind = num(parts[COL_WIND])
        gust = num(parts[COL_GUST])
        wind = wind * f if wind is not None else None
        gust = gust * f if gust is not None else None
        if wind is None or not (0.0 <= wind <= MAX_WIND_KN):
            continue
        if gust is not None and not (0.0 <= gust <= MAX_GUST_KN):
            gust = None
        # La direzione arriva come punto cardinale, non in gradi.
        direction = COMPASS.get((parts[COL_DIR] or "").strip().upper())
        out.append((iso_utc(stamp), wind, gust, direction))
    out.sort()
    return out


def fetch_noaa(base_url, month, year, unita):
    """Il report NOAA mensile: una riga per GIORNO.
    [(giorno_locale, vento_medio_kn, raffica_kn, dir_deg)]."""
    f = _fattore(unita)
    text = fetch_text(base_url + "csvnoaa.php", {"mesi": "%02d-%04d" % (month, year)},
                      timeout=60)
    if not text or text.lstrip().startswith("<"):
        raise FetchError("il report NOAA %02d-%d non e' disponibile" % (month, year))

    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = None
    out = []
    for row in reader:
        if not row:
            continue
        if header is None:
            header = [c.strip().strip('"').lower() for c in row]
            continue
        if len(row) < len(header):
            continue
        rec = dict(zip(header, [c.strip().strip('"') for c in row]))
        day_num = num(rec.get("data"))
        if day_num is None or not (1 <= day_num <= 31):
            continue
        try:
            day = _dt.date(year, month, int(day_num)).isoformat()
        except ValueError:
            continue
        # Le due intestazioni NON sono uguali, ed e' l'unica differenza vera
        # fra i due file: la Fraglia scrive "Avg Vento", Limone "Vento medio".
        # Si accetta la prima chiave che esiste invece di pretenderne una -
        # e una chiave in meno qui non e' un dettaglio: significherebbe un
        # mese di vento letto come vuoto, in silenzio.
        wind = num(_prima(rec, "vento medio", "avg vento", "vento med.",
                          "media vento"))
        gust = num(_prima(rec, "raffica", "raffica max", "raffica massima",
                          "avg raffica"))
        wind = wind * f if wind is not None else None
        gust = gust * f if gust is not None else None
        if wind is not None and not (0 <= wind <= MAX_WIND_KN):
            wind = None
        if gust is not None and not (0 <= gust <= MAX_GUST_KN):
            gust = None
        direction = COMPASS.get((_prima(rec, "dir dom", "dir. dom", "dir dominante")
                                 or "").upper())
        if wind is None and gust is None:
            continue
        out.append((day, wind, gust, direction))
    return out


def _prima(rec, *chiavi):
    for k in chiavi:
        if rec.get(k):
            return rec[k]
    return None


def mesi_da(inizio, oggi=None):
    """[(mese, anno)] dal piu' recente fino al primo mese coperto."""
    oggi = oggi or _dt.date.today()
    y0, m0 = inizio
    out = []
    y, m = oggi.year, oggi.month
    while (y, m) >= (y0, m0):
        out.append((m, y))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out
