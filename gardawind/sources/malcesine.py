"""Centralina Fraglia Vela Malcesine (MeteoProject).

Due canali:

  live       la pagina pubblica espone la media a 10 minuti, la direzione e la
             raffica giornaliera. Interrogandola a intervalli regolari si
             costruisce una serie a 10 minuti.
  archivio   i report NOAA mensili in CSV (csvnoaa.php?mesi=MM-YYYY) coprono
             da agosto 2024: sono GIORNALIERI (media vento, raffica massima,
             direzione dominante) e alimentano direttamente il modello
             giornaliero, che e' il livello su cui ragiona questa app.

La pagina pubblica l'orologio civile italiano, non un offset esplicito:
va interpretata come ora locale e convertita in UTC.
"""

import csv
import datetime as _dt
import html as _html
import io
import re

from .. import config
from ..util import iso_utc, local_naive_to_utc, num, parse_dt_any
from .http import FetchError, fetch_text

STATION = "malcesine"

MAX_WIND_KN = 60.0
MAX_GUST_KN = 85.0

COMPASS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SO": 202.5,
    "SW": 225.0, "WSW": 247.5, "OSO": 247.5, "W": 270.0, "O": 270.0,
    "WNW": 292.5, "NW": 315.0, "NO": 315.0, "NNW": 337.5,
}

_RE_UPDATED = re.compile(
    r"Dati aggiornati il\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*alle ore\s*(\d{1,2}[.:]\d{2})", re.I)
_RE_MEAN = re.compile(r"Media:?\s*([0-9]+(?:[.,][0-9]+)?)\s*kts", re.I)
_RE_NOW = re.compile(
    r"Velocit[aà]\s*attuale:?\s*([0-9]+(?:[.,][0-9]+)?)\s*kts\s*([A-Z]{1,3}|-)?", re.I)
_RE_GUST_DAY = re.compile(r"Raffica giornaliera:?\s*([0-9]+(?:[.,][0-9]+)?)\s*kts", re.I)
_RE_DIR = re.compile(r"Direzione\s*(?:da)?\s*([A-Z]{1,3})\b")


def _text(url):
    raw = fetch_text(url, timeout=45)
    stripped = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return _html.unescape(re.sub(r"\s+", " ", stripped))


def fetch_live():
    """Un campione: (timestamp_utc, vento_kn, raffica_kn|None, direzione|None).

    Usa la MEDIA a 10 minuti, non la velocita' istantanea: e' la grandezza
    confrontabile con i modelli e con l'archivio di Torbole.
    """
    page = _text(config.URL_MALCESINE_LIVE)

    m = _RE_UPDATED.search(page)
    if m:
        day = m.group(1)
        year = day.split("/")[-1]
        if len(year) == 2:
            day = day[: -2] + "20" + year
        naive = parse_dt_any(day + " " + m.group(2).replace(".", ":"))
        # parse_dt_any restituisce UTC per un input senza offset: qui il dato
        # e' ora locale, quindi va reinterpretato.
        if naive is not None:
            stamp = local_naive_to_utc(naive.replace(tzinfo=None))
        else:
            stamp = None
    else:
        stamp = None
    if stamp is None:
        stamp = _dt.datetime.now(_dt.timezone.utc).replace(second=0, microsecond=0)

    wind = None
    mm = _RE_MEAN.search(page)
    if mm:
        wind = num(mm.group(1))
    direction = None
    mn = _RE_NOW.search(page)
    if mn:
        if wind is None:
            wind = num(mn.group(1))
        if mn.group(2):
            direction = COMPASS.get(mn.group(2).upper())
    if direction is None:
        md = _RE_DIR.search(page)
        if md:
            direction = COMPASS.get(md.group(1).upper())

    if wind is None or not (0.0 <= wind <= MAX_WIND_KN):
        # Include un estratto della pagina: se il sito cambia impaginazione,
        # il registro dice subito cosa e' arrivato invece di un "non trovata".
        raise FetchError("velocita' non trovata a Malcesine; pagina: %s"
                         % page[:160].strip())

    gust = None
    mg = _RE_GUST_DAY.search(page)
    if mg:
        g = num(mg.group(1))
        # E' la raffica MASSIMA DEL GIORNO, non dei 10 minuti: la teniamo solo
        # come aggregato giornaliero, mai come raffica del campione.
        gust_day = g if (g is not None and 0 <= g <= MAX_GUST_KN) else None
    else:
        gust_day = None

    return (iso_utc(stamp), wind, gust, direction), gust_day


def available_months(today=None):
    """Elenco (mese, anno) coperti dall'archivio NOAA, dal piu' recente."""
    today = today or _dt.date.today()
    y0, m0 = config.MALCESINE_ARCHIVE_START
    out = []
    y, m = today.year, today.month
    while (y, m) >= (y0, m0):
        out.append((m, y))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def fetch_month(month, year):
    """Report NOAA mensile -> [(giorno_locale, vento_medio_kn, raffica_kn, dir_deg)].

    Le unita' sono dichiarate dalla pagina dell'archivio: vento in nodi,
    temperature in gradi, precipitazioni in millimetri.
    """
    text = fetch_text(config.URL_MALCESINE_NOAA_CSV, {"mesi": "%02d-%04d" % (month, year)},
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
        wind = num(rec.get("avg vento"))
        gust = num(rec.get("raffica"))
        if wind is not None and not (0 <= wind <= MAX_WIND_KN):
            wind = None
        if gust is not None and not (0 <= gust <= MAX_GUST_KN):
            gust = None
        direction = COMPASS.get((rec.get("dir dom") or "").upper())
        if wind is None and gust is None:
            continue
        out.append((day, wind, gust, direction))
    return out


# --------------------------------------------------------------------------
# Archivio intraday (Davis Vantage Pro2)
# --------------------------------------------------------------------------

_RE_ROW = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4});(\d{1,2}):(\d{2});")

# Indici di colonna del CSV, che ha intestazione:
# Data;Ora;Temp;Min;Max;Umid;"Dew pt";Vento;Dir;Raffica;"Dir Raff.";Press;
# Pioggia;Int.Pio.;Rad.Sol.
COL_WIND, COL_DIR, COL_GUST, COL_GUSTDIR = 7, 8, 9, 10


def intraday_months(today=None):
    """Mesi coperti dall'archivio intraday, dal piu' recente."""
    today = today or _dt.date.today()
    y0, m0 = config.MALCESINE_INTRADAY_START
    out = []
    y, m = today.year, today.month
    while (y, m) >= (y0, m0):
        out.append((m, y))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def fetch_intraday(month, year):
    """Un mese di misure a 15-30 minuti.

    Ritorna la stessa forma di fetch_live: (timestamp_utc, vento_kn,
    raffica_kn, direzione). Le unita' sono dichiarate dal CSV stesso
    ("Vento: kts"), quindi nessuna conversione.
    """
    import calendar
    last = calendar.monthrange(year, month)[1]
    return fetch_intraday_intervallo(_dt.date(year, month, 1),
                                     _dt.date(year, month, last))


def fetch_intraday_giorno(giorno):
    """Le misure di UN giorno locale (ISO). E' la strada per la raffica di
    Malcesine in tempo reale: la pagina live da' solo la raffica massima del
    giorno, l'archivio intraday da' quella dei 30 minuti - e accetta un
    intervallo, quindi si chiede solo oggi, a ogni giro."""
    d = _dt.date.fromisoformat(giorno)
    return fetch_intraday_intervallo(d, d)


def fetch_intraday_intervallo(dal, al):
    params = {
        "gg2": "%02d" % dal.day, "mm2": "%02d" % dal.month, "aa2": "%02d" % (dal.year % 100),
        "gg": "%02d" % al.day, "mm": "%02d" % al.month, "aa": "%02d" % (al.year % 100),
    }
    text = fetch_text(config.URL_MALCESINE_CSV, params, timeout=90)
    if not text or text.lstrip().startswith("<"):
        raise FetchError("archivio intraday %s..%s non disponibile" % (dal, al))

    out = []
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
        stamp = local_naive_to_utc(naive)

        wind = num(parts[COL_WIND])
        gust = num(parts[COL_GUST])
        if wind is None or not (0.0 <= wind <= MAX_WIND_KN):
            continue
        if gust is not None and not (0.0 <= gust <= MAX_GUST_KN):
            gust = None
        # La direzione arriva come punto cardinale, non in gradi.
        direction = COMPASS.get((parts[COL_DIR] or "").strip().upper())
        out.append((iso_utc(stamp), wind, gust, direction))
    out.sort()
    return out
