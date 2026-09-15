"""Persistenza SQLite.

Principi:
  - tutti gli istanti sono chiavi UTC ("YYYY-MM-DDTHH:MM:SSZ");
  - le osservazioni grezze non vengono mai perse: l'aggregazione oraria e'
    una tabella DERIVATA, ricostruibile in qualsiasi momento;
  - nessuna riga con valori "riempiti": un dato mancante resta NULL, perche'
    assenza di misura non e' assenza di vento.
"""

import json
import os
import sqlite3
import threading

from . import config
from .util import iso_utc, utc_now

_LOCAL = threading.local()


def support_dir():
    base = os.environ.get("GARDAWIND_HOME")
    if base:
        path = os.path.expanduser(base)
    elif os.path.isdir(os.path.expanduser("~/Library")):
        path = os.path.expanduser("~/Library/Application Support/Garda Wind")
    else:
        path = os.path.expanduser("~/.gardawind")
    os.makedirs(path, exist_ok=True)
    return path


def db_path():
    return os.path.join(support_dir(), config.DB_FILENAME)


SCHEMA = """
-- Campioni grezzi delle centraline, alla loro frequenza nativa.
CREATE TABLE IF NOT EXISTS obs_sample(
  station   TEXT NOT NULL,
  ts        TEXT NOT NULL,          -- UTC
  wind_kn   REAL,
  gust_kn   REAL,
  dir_deg   REAL,
  source    TEXT NOT NULL,
  PRIMARY KEY(station, ts, source)
);
CREATE INDEX IF NOT EXISTS ix_obs_sample_ts ON obs_sample(station, ts);

-- Aggregato orario derivato dai campioni grezzi.
CREATE TABLE IF NOT EXISTS obs_hour(
  station     TEXT NOT NULL,
  hour        TEXT NOT NULL,        -- UTC, troncata all'ora
  wind_mean   REAL,
  wind_max    REAL,
  gust_max    REAL,
  gust_rec    REAL,               -- raffica ricorrente: mediana mobile a 30'
  dir_deg     REAL,
  dir_const   REAL,
  n_samples   INTEGER,
  PRIMARY KEY(station, hour)
);

-- Aggregato giornaliero: usato per gli archivi che espongono solo il giorno
-- (report NOAA di Malcesine) e per i riassunti.
CREATE TABLE IF NOT EXISTS obs_day(
  station    TEXT NOT NULL,
  day        TEXT NOT NULL,         -- giorno LOCALE
  wind_avg   REAL,
  gust_max   REAL,
  dir_dom    REAL,
  source     TEXT,
  PRIMARY KEY(station, day, source)
);

-- Previsioni correnti, una riga per (punto, modello, run, istante valido).
CREATE TABLE IF NOT EXISTS fc_hour(
  point   TEXT NOT NULL,
  model   TEXT NOT NULL,
  run     TEXT NOT NULL,
  valid   TEXT NOT NULL,
  t2m REAL, rh REAL, dew REAL, precip REAL, cloud REAL, cloud_low REAL,
  mslp REAL, rad REAL, w10 REAL, d10 REAL, g10 REAL,
  t925 REAL, w925 REAL, d925 REAL, t850 REAL, w850 REAL, d850 REAL,
  w700 REAL, d700 REAL,
  PRIMARY KEY(point, model, run, valid)
);
CREATE INDEX IF NOT EXISTS ix_fc_valid ON fc_hour(point, valid);

-- Archivio storico delle previsioni (historical-forecast-api, best_match):
-- la sorgente dei predittori usati in addestramento.
CREATE TABLE IF NOT EXISTS arch_hour(
  point   TEXT NOT NULL,
  valid   TEXT NOT NULL,
  t2m REAL, rh REAL, dew REAL, precip REAL, cloud REAL, cloud_low REAL,
  mslp REAL, rad REAL, w10 REAL, d10 REAL, g10 REAL,
  t925 REAL, w925 REAL, d925 REAL, t850 REAL, w850 REAL, d850 REAL,
  w700 REAL, d700 REAL,
  PRIMARY KEY(point, valid)
);

-- Contesto sinottico (punti di pianura e di valle), corrente e storico.
CREATE TABLE IF NOT EXISTS ctx_hour(
  place   TEXT NOT NULL,
  valid   TEXT NOT NULL,
  kind    TEXT NOT NULL,            -- 'live' | 'arch'
  mslp REAL, t2m REAL, cloud REAL, rad REAL,
  PRIMARY KEY(place, valid, kind)
);

-- Verifica per modello e lead, SEMPRE contro osservazioni di centralina.
CREATE TABLE IF NOT EXISTS model_skill(
  spot TEXT NOT NULL, model TEXT NOT NULL, lead INTEGER NOT NULL,
  n INTEGER, mae REAL, bias REAL, rmse REAL, slope REAL, weight REAL,
  updated TEXT,
  PRIMARY KEY(spot, model, lead)
);

-- Modelli appresi (serializzati) e le loro metriche out-of-fold.
CREATE TABLE IF NOT EXISTS learned(
  spot TEXT NOT NULL, kind TEXT NOT NULL,    -- 'occurrence' | 'intensity' | 'hourly_bias'
  tier TEXT, n INTEGER, payload TEXT, metrics TEXT, updated TEXT,
  PRIMARY KEY(spot, kind)
);

-- Registro degli aggiornamenti: cosa e' andato storto e quando.
CREATE TABLE IF NOT EXISTS events(
  ts TEXT NOT NULL, level TEXT, scope TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);

-- Provenienza di ogni lettura da una fonte che si LEGGE invece di essere
-- interrogata: le pagine web. Un parser su HTML e' vero finche' il markup non
-- cambia, e quando cambia non da' errore: da' silenzio, o peggio un numero
-- preso dal posto sbagliato. Perche' quel momento sia riconoscibile serve
-- tenere traccia di cosa si e' letto, quando, e con quale versione del parser.
--
--   sha256        impronta del corpo INTERO. Su una pagina che contiene
--                 numeri vivi cambia a ogni lettura: serve all'audit, non
--                 come sentinella.
--   struct_sha256 impronta della sola STRUTTURA (i tag, senza i valori). Non
--                 cambia mentre il vento cambia: cambia quando il sito viene
--                 rifatto. E' questa la sentinella.
--   body          il corpo grezzo, tenuto SOLO quando serve davvero: quando
--                 il parser ha fallito, o quando la struttura e' cambiata.
--                 Tenerlo sempre vorrebbe dire scrivere qualche decina di
--                 megabyte al giorno per riletture identiche.
CREATE TABLE IF NOT EXISTS raw_fetch(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,
  station       TEXT,
  channel       TEXT,                -- "json", "html", ...
  url           TEXT NOT NULL,
  fetched_at    TEXT NOT NULL,       -- UTC
  ok            INTEGER,
  bytes         INTEGER,
  sha256        TEXT,
  struct_sha256 TEXT,
  parser_version TEXT,
  n_rows        INTEGER,
  note          TEXT,
  body          TEXT
);
CREATE INDEX IF NOT EXISTS ix_raw_fetch ON raw_fetch(source, channel, fetched_at);
"""

FC_COLS = ["t2m", "rh", "dew", "precip", "cloud", "cloud_low", "mslp", "rad",
           "w10", "d10", "g10", "t925", "w925", "d925", "t850", "w850", "d850",
           "w700", "d700"]

# Mappa nome Open-Meteo -> colonna
OM_TO_COL = {
    "temperature_2m": "t2m", "relative_humidity_2m": "rh", "dew_point_2m": "dew",
    "precipitation": "precip", "cloud_cover": "cloud", "cloud_cover_low": "cloud_low",
    "pressure_msl": "mslp", "shortwave_radiation": "rad",
    "wind_speed_10m": "w10", "wind_direction_10m": "d10", "wind_gusts_10m": "g10",
    "temperature_925hPa": "t925", "wind_speed_925hPa": "w925", "wind_direction_925hPa": "d925",
    "temperature_850hPa": "t850", "wind_speed_850hPa": "w850", "wind_direction_850hPa": "d850",
    "wind_speed_700hPa": "w700", "wind_direction_700hPa": "d700",
}


def connect():
    """Una connessione per thread, con WAL attivo."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        _migra(conn)
        conn.commit()
        _LOCAL.conn = conn
    return conn


# Colonne aggiunte dopo la prima versione dello schema. CREATE TABLE IF NOT
# EXISTS non tocca una tabella che esiste gia', quindi su un database vissuto -
# quello sul Mac, quello nella cache di Actions - una colonna nuova non
# comparirebbe mai e l'aggregazione andrebbe in errore. Qui si aggiunge una
# volta, in modo idempotente, senza ricostruire niente.
MIGRAZIONI = (
    ("obs_hour", "gust_rec", "REAL"),
)


def _migra(conn):
    for tabella, colonna, tipo in MIGRAZIONI:
        presenti = {r["name"] for r in
                    conn.execute("PRAGMA table_info(%s)" % tabella)}
        if presenti and colonna not in presenti:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                         % (tabella, colonna, tipo))


def close():
    """Chiude la connessione di QUESTO thread.

    Il server HTTP crea un thread per richiesta: senza questa chiamata ogni
    richiesta lascerebbe aperto un handle su SQLite finche' il processo vive.
    """
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _LOCAL.conn = None


def init():
    connect()


# --------------------------------------------------------------------------
# meta / eventi
# --------------------------------------------------------------------------

def meta_get(key, default=None):
    r = connect().execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return r["v"] if r else default


def meta_set(key, value):
    c = connect()
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (key, str(value)))
    c.commit()


def log_event(level, scope, message):
    c = connect()
    c.execute("INSERT INTO events(ts, level, scope, message) VALUES(?,?,?,?)",
              (iso_utc(utc_now()), level, scope, str(message)[:500]))
    c.execute("DELETE FROM events WHERE ts < (SELECT ts FROM events "
              "ORDER BY ts DESC LIMIT 1 OFFSET 400)")
    c.commit()


def recent_events(limit=60, level=None):
    q = "SELECT ts, level, scope, message FROM events"
    args = []
    if level:
        q += " WHERE level=?"
        args.append(level)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in connect().execute(q, args)]


# --------------------------------------------------------------------------
# Osservazioni
# --------------------------------------------------------------------------

def save_samples(station, rows, source):
    """rows: iterabile di (ts_utc_iso, wind_kn, gust_kn, dir_deg). Ritorna n inseriti."""
    c = connect()
    payload = [(station, ts, w, g, d, source) for ts, w, g, d in rows if ts]
    if not payload:
        return 0
    c.executemany(
        "INSERT OR REPLACE INTO obs_sample(station, ts, wind_kn, gust_kn, dir_deg, source) "
        "VALUES(?,?,?,?,?,?)", payload)
    c.commit()
    return len(payload)


# Quanti corpi grezzi tenere per ogni (fonte, canale). Servono a capire un
# guasto, non a fare un archivio del sito: i piu' vecchi si buttano.
MAX_CORPI_GREZZI = 12


def log_raw_fetch(source, url, fetched_at, channel=None, station=None,
                  ok=True, body=None, sha256=None, struct_sha256=None,
                  parser_version=None, n_rows=None, note=None,
                  tieni_corpo=None):
    """Registra una lettura grezza. Ritorna (id, struttura_cambiata).

    tieni_corpo: None = decidi qui (si tiene se il parser ha fallito o se la
    struttura e' cambiata rispetto all'ultima lettura buona); True/False per
    forzare.

    "struttura_cambiata" e' l'informazione che vale: dice che il sito e' stato
    rifatto, ed e' il momento in cui un parser su HTML va guardato - prima che
    cominci a restituire numeri sbagliati invece di errori.
    """
    c = connect()
    prec = c.execute(
        "SELECT struct_sha256 FROM raw_fetch WHERE source=? AND channel=? "
        "AND struct_sha256 IS NOT NULL ORDER BY id DESC LIMIT 1",
        (source, channel)).fetchone()
    cambiata = bool(prec and struct_sha256 and prec["struct_sha256"] != struct_sha256)
    if tieni_corpo is None:
        tieni_corpo = (not ok) or cambiata or prec is None
    cur = c.execute(
        "INSERT INTO raw_fetch(source, station, channel, url, fetched_at, ok, "
        "bytes, sha256, struct_sha256, parser_version, n_rows, note, body) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (source, station, channel, url, fetched_at, 1 if ok else 0,
         len(body) if body is not None else None, sha256, struct_sha256,
         parser_version, n_rows, note, body if tieni_corpo else None))
    # Si tengono gli ultimi MAX_CORPI_GREZZI corpi per fonte e canale; delle
    # letture piu' vecchie resta la riga (impronta, esito, versione), che e'
    # cio' che serve per ricostruire una storia.
    c.execute(
        "UPDATE raw_fetch SET body=NULL WHERE body IS NOT NULL AND source=? "
        "AND channel=? AND id NOT IN (SELECT id FROM raw_fetch WHERE "
        "body IS NOT NULL AND source=? AND channel=? ORDER BY id DESC LIMIT ?)",
        (source, channel, source, channel, MAX_CORPI_GREZZI))
    c.commit()
    return cur.lastrowid, cambiata


def raw_fetches(source=None, channel=None, limit=20):
    """Le ultime letture grezze registrate, dalla piu' recente."""
    q = ("SELECT id, source, station, channel, url, fetched_at, ok, bytes, "
         "sha256, struct_sha256, parser_version, n_rows, note, "
         "(body IS NOT NULL) AS ha_corpo FROM raw_fetch")
    dove, par = [], []
    if source:
        dove.append("source=?")
        par.append(source)
    if channel:
        dove.append("channel=?")
        par.append(channel)
    if dove:
        q += " WHERE " + " AND ".join(dove)
    q += " ORDER BY id DESC LIMIT ?"
    par.append(int(limit))
    return [dict(r) for r in connect().execute(q, par)]


def raw_body(raw_id):
    r = connect().execute("SELECT body FROM raw_fetch WHERE id=?",
                          (raw_id,)).fetchone()
    return r["body"] if r else None


def save_day_obs(station, rows, source):
    """rows: iterabile di (day, wind_avg_kn, gust_max_kn, dir_dom_deg)."""
    c = connect()
    payload = [(station, d, w, g, dd, source) for d, w, g, dd in rows if d]
    if not payload:
        return 0
    c.executemany(
        "INSERT OR REPLACE INTO obs_day(station, day, wind_avg, gust_max, dir_dom, source) "
        "VALUES(?,?,?,?,?,?)", payload)
    c.commit()
    return len(payload)


def samples_since(station, since_iso):
    """I campioni grezzi, CON la fonte.

    La fonte serve: la chiave e' (stazione, istante, fonte), quindi lo stesso
    istante puo' arrivare due volte - dall'archivio validato e dal canale
    realtime - e chi unisce i due deve sapere quale sta guardando per poter
    dichiarare un conflitto invece di scegliere in silenzio.
    """
    return [dict(r) for r in connect().execute(
        "SELECT ts, wind_kn, gust_kn, dir_deg, source FROM obs_sample "
        "WHERE station=? AND ts>=? ORDER BY ts, source", (station, since_iso))]


def upsert_obs_hours(station, rows):
    """rows: iterabile di dict con hour, wind_mean, wind_max, gust_max,
    gust_rec, dir_deg, dir_const, n_samples."""
    c = connect()
    c.executemany(
        "INSERT OR REPLACE INTO obs_hour(station, hour, wind_mean, wind_max, gust_max,"
        " gust_rec, dir_deg, dir_const, n_samples) VALUES(?,?,?,?,?,?,?,?,?)",
        [(station, r["hour"], r["wind_mean"], r["wind_max"], r["gust_max"],
          r.get("gust_rec"), r["dir_deg"], r["dir_const"], r["n_samples"])
         for r in rows])
    c.commit()
    return c.total_changes


def obs_hours(station, start_hour=None, end_hour=None):
    q = "SELECT hour, wind_mean, wind_max, gust_max, gust_rec, dir_deg, " \
        "dir_const, n_samples FROM obs_hour WHERE station=?"
    args = [station]
    if start_hour:
        q += " AND hour>=?"
        args.append(start_hour)
    if end_hour:
        q += " AND hour<=?"
        args.append(end_hour)
    return [dict(r) for r in connect().execute(q + " ORDER BY hour", args)]


def obs_days(station):
    return [dict(r) for r in connect().execute(
        "SELECT day, wind_avg, gust_max, dir_dom, source FROM obs_day "
        "WHERE station=? ORDER BY day", (station,))]


def obs_stats(station):
    r = connect().execute(
        "SELECT COUNT(*) n, MIN(hour) a, MAX(hour) b FROM obs_hour WHERE station=?",
        (station,)).fetchone()
    rd = connect().execute(
        "SELECT COUNT(*) n, MIN(day) a, MAX(day) b FROM obs_day WHERE station=?",
        (station,)).fetchone()
    rs = connect().execute(
        "SELECT COUNT(*) n FROM obs_sample WHERE station=?", (station,)).fetchone()
    return {"hours": r["n"], "hour_from": r["a"], "hour_to": r["b"],
            "days": rd["n"], "day_from": rd["a"], "day_to": rd["b"],
            "samples": rs["n"]}


# --------------------------------------------------------------------------
# Previsioni
# --------------------------------------------------------------------------

def point_key(lat, lon, source="forecast"):
    """Chiave del punto, con la sorgente dei predittori nel prefisso.

    Archivio previsioni e rianalisi ERA5 convivono nella stessa tabella ma non
    devono MAI mescolarsi: sono grandezze diverse (stato previsto vs stato
    ricostruito) e confonderle renderebbe insensato il confronto fra i due.
    """
    base = "%.4f,%.4f" % (lat, lon)
    return base if source == "forecast" else "%s|%s" % (source, base)


def _insert_rows(table, fixed_cols, fixed_vals, rows):
    cols = fixed_cols + ["valid"] + FC_COLS
    ph = ",".join("?" * len(cols))
    sql = "INSERT OR REPLACE INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ph)
    payload = []
    for valid, values in rows:
        payload.append(tuple(fixed_vals) + (valid,) + tuple(values.get(c) for c in FC_COLS))
    if not payload:
        return 0
    c = connect()
    c.executemany(sql, payload)
    c.commit()
    return len(payload)


def save_forecast(point, model, run, rows):
    return _insert_rows("fc_hour", ["point", "model", "run"], [point, model, run], rows)


def save_archive(point, rows):
    return _insert_rows("arch_hour", ["point"], [point], rows)


def latest_runs(point):
    """Ultimo run disponibile per ciascun modello su un punto."""
    return {r["model"]: r["run"] for r in connect().execute(
        "SELECT model, MAX(run) run FROM fc_hour WHERE point=? GROUP BY model", (point,))}


def forecast_rows(point, model, run):
    cols = ",".join(FC_COLS)
    return [dict(r) for r in connect().execute(
        "SELECT valid,%s FROM fc_hour WHERE point=? AND model=? AND run=? ORDER BY valid" % cols,
        (point, model, run))]


def archive_rows(point, start_valid, end_valid):
    cols = ",".join(FC_COLS)
    return [dict(r) for r in connect().execute(
        "SELECT valid,%s FROM arch_hour WHERE point=? AND valid>=? AND valid<=? ORDER BY valid" % cols,
        (point, start_valid, end_valid))]


def archive_span(point):
    r = connect().execute(
        "SELECT MIN(valid) a, MAX(valid) b, COUNT(*) n FROM arch_hour WHERE point=?",
        (point,)).fetchone()
    return r["a"], r["b"], r["n"]


def save_context(place, kind, rows):
    """rows: iterabile di (valid, dict(mslp,t2m,cloud,rad))."""
    payload = [(place, valid, kind, v.get("mslp"), v.get("t2m"), v.get("cloud"), v.get("rad"))
               for valid, v in rows]
    if not payload:
        return 0
    c = connect()
    c.executemany("INSERT OR REPLACE INTO ctx_hour(place, valid, kind, mslp, t2m, cloud, rad) "
                  "VALUES(?,?,?,?,?,?,?)", payload)
    c.commit()
    return len(payload)


def context_map(kind, start_valid=None, end_valid=None):
    """Ritorna {valid: {place: {mslp,t2m,cloud,rad}}}."""
    q = "SELECT place, valid, mslp, t2m, cloud, rad FROM ctx_hour WHERE kind=?"
    args = [kind]
    if start_valid:
        q += " AND valid>=?"
        args.append(start_valid)
    if end_valid:
        q += " AND valid<=?"
        args.append(end_valid)
    out = {}
    for r in connect().execute(q, args):
        out.setdefault(r["valid"], {})[r["place"]] = {
            "mslp": r["mslp"], "t2m": r["t2m"], "cloud": r["cloud"], "rad": r["rad"]}
    return out


def context_span(kind):
    r = connect().execute(
        "SELECT MIN(valid) a, MAX(valid) b, COUNT(DISTINCT valid) n FROM ctx_hour WHERE kind=?",
        (kind,)).fetchone()
    return r["a"], r["b"], r["n"]


# --------------------------------------------------------------------------
# Skill e modelli appresi
# --------------------------------------------------------------------------

def save_skill(spot, model, lead, stats):
    c = connect()
    c.execute("INSERT OR REPLACE INTO model_skill(spot, model, lead, n, mae, bias, rmse,"
              " slope, weight, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (spot, model, lead, stats.get("n"), stats.get("mae"), stats.get("bias"),
               stats.get("rmse"), stats.get("slope"), stats.get("weight"),
               iso_utc(utc_now())))
    c.commit()


def skills(spot):
    return {(r["model"], r["lead"]): dict(r) for r in connect().execute(
        "SELECT * FROM model_skill WHERE spot=?", (spot,))}


def save_learned(spot, kind, tier, n, payload, metrics):
    c = connect()
    c.execute("INSERT OR REPLACE INTO learned(spot, kind, tier, n, payload, metrics, updated)"
              " VALUES(?,?,?,?,?,?,?)",
              (spot, kind, tier, n, json.dumps(payload), json.dumps(metrics),
               iso_utc(utc_now())))
    c.commit()


def load_learned(spot, kind):
    r = connect().execute("SELECT * FROM learned WHERE spot=? AND kind=?",
                          (spot, kind)).fetchone()
    if not r:
        return None
    return {"tier": r["tier"], "n": r["n"], "payload": json.loads(r["payload"]),
            "metrics": json.loads(r["metrics"]), "updated": r["updated"]}


def all_learned():
    return [{"spot": r["spot"], "kind": r["kind"], "tier": r["tier"], "n": r["n"],
             "metrics": json.loads(r["metrics"]), "updated": r["updated"]}
            for r in connect().execute("SELECT * FROM learned ORDER BY spot, kind")]


def prune_forecasts(keep_runs=4):
    """Tiene solo gli ultimi run per (punto, modello): il resto e' zavorra."""
    c = connect()
    rows = c.execute("SELECT DISTINCT point, model FROM fc_hour").fetchall()
    removed = 0
    for r in rows:
        runs = [x["run"] for x in c.execute(
            "SELECT DISTINCT run FROM fc_hour WHERE point=? AND model=? "
            "ORDER BY run DESC", (r["point"], r["model"]))]
        for old in runs[keep_runs:]:
            c.execute("DELETE FROM fc_hour WHERE point=? AND model=? AND run=?",
                      (r["point"], r["model"], old))
            removed += 1
    c.commit()
    return removed
