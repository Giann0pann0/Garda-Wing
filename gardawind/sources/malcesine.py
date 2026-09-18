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
from . import davis_csv
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
    return davis_csv.mesi_da(config.MALCESINE_ARCHIVE_START, today)


def fetch_month(month, year):
    """Report NOAA mensile -> [(giorno_locale, vento_medio_kn, raffica_kn, dir_deg)].

    Il lavoro lo fa davis_csv: la Fraglia e Limone pubblicano con lo stesso
    pacchetto, stessi indirizzi e stesse colonne. Qui restano l'indirizzo e
    l'unita', che le due NON hanno uguale: la pagina dell'archivio della
    Fraglia dichiara il vento in NODI.
    """
    return davis_csv.fetch_noaa(config.URL_MALCESINE_BASE, month, year, "kn")


# --------------------------------------------------------------------------
# Archivio intraday (Davis Vantage Pro2)
# --------------------------------------------------------------------------

def intraday_months(today=None):
    """Mesi coperti dall'archivio intraday, dal piu' recente."""
    return davis_csv.mesi_da(config.MALCESINE_INTRADAY_START, today)


def fetch_intraday(month, year):
    """Un mese di misure a 15-30 minuti, nella forma di fetch_live."""
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
    return davis_csv.fetch_intervallo(config.URL_MALCESINE_BASE, dal, al, "kn")
