"""Centralina T0193 Torbole (Belvedere), Meteotrentino.

Due canali, entrambi pubblici:

  realtime   datiRealtimeUnaStazione, GeoJSON, ultime 168 ore, passo 10 minuti
  archivio   Hydstra/WEB (storico.meteotrentino.it): l'INTERA serie a 10 minuti
             dal 04/07/2012, in un solo ZIP

Entrambi marcano i dati in ora solare CET (UTC+1) tutto l'anno, anche in
estate. Qui vengono convertiti in UTC una volta sola, all'ingresso.
"""

import io
import re
import zipfile

from .. import config
from ..util import KN_PER_MS, iso_utc, num, parse_dt_any
from .http import FetchError, fetch, fetch_json, fetch_text

STATION = "T0193"
_OFF = config.METEOTRENTINO_UTC_OFFSET_HOURS

# Limiti di plausibilita': oltre questi valori il dato e' un errore di unita'
# o un guasto, non un evento meteorologico.
MAX_WIND_KN = 70.0
MAX_GUST_KN = 95.0


def _clean(wind_ms, gust_ms, direction):
    wind = num(wind_ms)
    gust = num(gust_ms)
    direction = num(direction)
    if wind is None:
        return None
    wind *= KN_PER_MS
    if not (0.0 <= wind <= MAX_WIND_KN):
        return None
    if gust is not None:
        gust *= KN_PER_MS
        if not (0.0 <= gust <= MAX_GUST_KN) or gust < wind * 0.8:
            gust = None
    if direction is not None:
        direction = direction % 360.0
    return wind, gust, direction


def fetch_realtime(hours=168):
    """Campioni a 10 minuti delle ultime `hours` ore. Ritorna lista di tuple."""
    data = fetch_json(config.URL_METEOTRENTINO,
                      {"stazione": STATION, "h": str(int(hours))}, timeout=90)
    feats = data.get("features") or []
    out = []
    for f in feats:
        p = (f or {}).get("properties") or {}
        # L'offset e' scritto nel timestamp ("+01"): parse_dt_any lo gestisce
        # anche nella forma a due cifre che fromisoformat di Python 3.9 rifiuta.
        dt = parse_dt_any(p.get("datetime"), assume_offset_hours=_OFF)
        if dt is None:
            continue
        cleaned = _clean(p.get("vvmed(m/s)"), p.get("vvmax(m/s)"), p.get("dvmed(gN)"))
        if cleaned is None:
            continue
        wind, gust, direction = cleaned
        out.append((iso_utc(dt), wind, gust, direction))
    return out


# --------------------------------------------------------------------------
# Archivio Hydstra
# --------------------------------------------------------------------------

_USERID_RE = re.compile(r"Cookies\.create\(\s*['\"]userid['\"]\s*,\s*['\"](\d+)['\"]")
_ZIP_RE = re.compile(r"(https?://[^\s'\"\\]+\.zip)")
_ROW_RE = re.compile(r"^(\d{2}:\d{2}:\d{2}) (\d{2}/\d{2}/\d{4})\s*,\s*([-\d.]+)\s*,\s*(\d+)")

# Codici di qualita' Hydstra: 255 = nessun dato. Gli altri sono dati validi
# o telemetrati non validati, che per il nostro uso vanno bene.
QUALITY_NO_DATA = 255


def _hydstra_userid():
    page = fetch_text(config.URL_HYDSTRA_MAIN, timeout=60, encoding="iso-8859-1")
    m = _USERID_RE.search(page)
    if not m:
        raise FetchError("userid anonimo non trovato nella pagina Hydstra")
    return m.group(1)


def _hydstra_extract(variable_key, start_day, end_day):
    """Chiede l'estrazione e ritorna il testo CSV decompresso."""
    var_id, var_name = config.HYDSTRA_VARS[variable_key]
    d1 = "%s/%s/%s" % (start_day[8:10], start_day[5:7], start_day[0:4])
    d2 = "%s/%s/%s" % (end_day[8:10], end_day[5:7], end_day[0:4])
    params = {
        "co": STATION,
        "v": var_id,
        "vn": var_name,
        "p": "Altro,1,1,custom,1",
        "o": "Download,download",
        "i": "Tutte le misure,Point,1",
        "cat": "rs",
        "d1": d1,
        "d2": d2,
    }
    # La generazione dello ZIP lato server puo' richiedere parecchio tempo
    # sull'intero archivio: il timeout e' volutamente generoso.
    page = fetch_text(config.URL_HYDSTRA_APP, params, timeout=300, encoding="iso-8859-1")
    m = _ZIP_RE.search(page.replace("\\'", "'"))
    if not m:
        raise FetchError("Hydstra non ha prodotto un file (intervallo vuoto?)")
    blob = fetch(m.group(1), timeout=300)
    if blob[:2] != b"PK":
        raise FetchError("il download Hydstra non e' uno ZIP")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise FetchError("ZIP Hydstra senza CSV")
        return z.read(names[0]).decode("iso-8859-1", "replace")


def _parse_hydstra_csv(text):
    """Ritorna {timestamp_utc: valore}. Le righe con qualita' 255 sono scartate."""
    out = {}
    for line in text.splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        hhmmss, ddmmyyyy, value, quality = m.groups()
        if int(quality) == QUALITY_NO_DATA:
            continue
        v = num(value)
        if v is None:
            continue
        dt = parse_dt_any("%s-%s-%s %s" % (ddmmyyyy[6:10], ddmmyyyy[3:5], ddmmyyyy[0:2], hhmmss),
                          assume_offset_hours=config.HYDSTRA_UTC_OFFSET_HOURS)
        if dt is not None:
            out[iso_utc(dt)] = v
    return out


def fetch_archive(start_day=None, end_day=None, on_year=None, from_year=None):
    """Serie storica a 10 minuti: velocita' (m/s) e direzione.

    Scarica un anno per volta e consegna ogni anno al chiamante via `on_year`
    appena e' pronto, cosi' che possa salvarlo subito. L'intero archivio in
    una sola richiesta funziona, ma la generazione lato server e' lenta e
    un'interruzione a meta' butterebbe via tutto: a blocchi annuali si perde
    al massimo un anno, e la volta dopo si riparte da li'.

    Le raffiche non sono in archivio (la variabile non e' esposta): restano
    None. Il bersaglio del modello e' comunque la media oraria, e le raffiche
    si accumulano dal canale realtime da qui in avanti.
    """
    import datetime as _d
    start_day = start_day or config.HYDSTRA_ARCHIVE_START
    end_day = end_day or _d.date.today().isoformat()

    # Visita preliminare: apre la sessione anonima lato server, da cui poi si
    # scarica il file generato.
    try:
        _hydstra_userid()
    except FetchError:
        pass

    collected = []
    y0 = max(int(start_day[:4]), int(from_year or 0))
    y1 = int(end_day[:4])
    for year in range(y0, y1 + 1):
        a = max(start_day, "%d-01-01" % year)
        b = min(end_day, "%d-12-31" % year)
        try:
            speeds = _parse_hydstra_csv(_hydstra_extract("wind", a, b))
        except FetchError as exc:
            if on_year:
                on_year(year, [], str(exc)[:140])
            continue
        try:
            dirs = _parse_hydstra_csv(_hydstra_extract("dir", a, b))
        except FetchError:
            dirs = {}

        rows = []
        for ts, ms in speeds.items():
            kn = ms * KN_PER_MS
            if not (0.0 <= kn <= MAX_WIND_KN):
                continue
            d = dirs.get(ts)
            rows.append((ts, kn, None, (d % 360.0) if d is not None else None))
        rows.sort()
        if on_year:
            on_year(year, rows, None)
        else:
            collected.extend(rows)
    return collected


def consistency_check(archive_rows, realtime_rows, tolerance_kn=0.6):
    """Confronta archivio e realtime sugli istanti in comune.

    Se le due sorgenti fossero su fusi diversi, i valori non coinciderebbero:
    questo controllo lo rende evidente invece di lasciarlo sepolto nei dati.
    Ritorna (n_confronti, frazione_coincidente, scostamento_medio).
    """
    a = {ts: w for ts, w, _g, _d in archive_rows}
    common = [(a[ts], w) for ts, w, _g, _d in realtime_rows if ts in a]
    if not common:
        return 0, None, None
    diffs = [abs(x - y) for x, y in common]
    agree = sum(1 for d in diffs if d <= tolerance_kn) / len(diffs)
    return len(common), agree, sum(diffs) / len(diffs)
