"""Orchestrazione: raccolta dati, addestramento, produzione della previsione."""

import datetime as _dt
import math
import threading
import time

from . import (aggregate, config, confidence as CONF, features as F,
               model as M, store, validate as V, verify)
from .sources import malcesine, meteotrentino, openmeteo
from .sources.http import FetchError
from .util import (angle_diff, clamp, day_shift, iso_utc, local_day, local_hour,
                   mean, parse_dt_any, pstdev, utc_now, vector_mean_direction)

STATE = {
    "running": False,
    "phase": "",
    "started": None,
    "finished": None,
    "errors": [],
}
_LOCK = threading.Lock()


def _note(level, scope, message):
    store.log_event(level, scope, message)
    if level == "error":
        STATE["errors"] = (STATE["errors"] + ["%s: %s" % (scope, message)])[-10:]


def _points():
    seen = {}
    for name, s in config.SPOTS.items():
        seen.setdefault(store.point_key(s["lat"], s["lon"]), (s["lat"], s["lon"]))
    return seen


# ==========================================================================
# Raccolta previsioni
# ==========================================================================

def update_forecasts():
    run = iso_utc(utc_now())
    okc = 0
    for point, (lat, lon) in _points().items():
        for name, m in config.MODELS.items():
            try:
                rows, _elev = openmeteo.fetch_forecast(lat, lon, m["id"], m["levels"])
                if rows:
                    store.save_forecast(point, name, run, rows)
                    okc += 1
            except FetchError as e:
                _note("warn", "forecast/%s" % name, str(e)[:160])
    store.meta_set("last_forecast_run", run)
    store.prune_forecasts(keep_runs=3)
    return okc


def update_context():
    run = iso_utc(utc_now())
    n = 0
    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        try:
            rows = openmeteo.fetch_context(lat, lon)
            n += store.save_context(place, "live", rows)
        except FetchError as e:
            _note("warn", "context/%s" % place, str(e)[:160])
    store.meta_set("last_context_run", run)
    return n


# ==========================================================================
# Centraline
# ==========================================================================

def update_stations():
    done = []
    try:
        rows = meteotrentino.fetch_realtime(hours=168)
        store.save_samples("T0193", rows, "meteotrentino-realtime")
        # Il servizio restituisce i campioni dal piu' recente: la finestra da
        # riaggregare parte dal piu' VECCHIO, non dal primo della lista.
        aggregate.aggregate_station("T0193",
                                    since_iso=min(r[0] for r in rows) if rows else None)
        done.append("Torbole %d campioni" % len(rows))
    except FetchError as e:
        _note("error", "centralina/Torbole", str(e)[:160])

    try:
        sample, gust_day = malcesine.fetch_live()
        store.save_samples("malcesine", [sample], "meteoproject-live")
        aggregate.aggregate_station("malcesine", since_iso=day_shift(sample[0][:10], -2))
        if gust_day is not None:
            store.save_day_obs("malcesine", [(local_day(parse_dt_any(sample[0])),
                                              None, gust_day, None)],
                               "meteoproject-live")
        done.append("Malcesine 1 campione")
    except FetchError as e:
        _note("error", "centralina/Malcesine", str(e)[:160])
    return done


def refresh_malcesine_intraday(months=2):
    """Riscarica gli ultimi mesi dell'archivio intraday di Malcesine.

    Serve solo in cloud, e li' serve parecchio. Il backfill completo gira una
    volta e poi si marca come fatto; da quel momento gli unici campioni nuovi
    arrivano da fetch_live(), che pesca UN istante per esecuzione. Sul Mac non
    e' un problema, perche' l'agente in background legge ogni quindici minuti.
    Su GitHub Actions, che gira quattro volte al giorno, vorrebbe dire quattro
    campioni al giorno invece di una novantina: il modello di Malcesine, che
    gia' soffre per mancanza di storico, resterebbe affamato per sempre.

    L'archivio CSV della stazione pubblica pero' tutte le letture a 15-30
    minuti, anche all'indietro. Due richieste per ciclo (il mese corrente e il
    precedente, per non perdere il cambio mese) recuperano tutto quello che la
    lettura istantanea non ha visto. INSERT OR REPLACE rende l'operazione
    idempotente: riscaricare lo stesso mese non duplica niente.
    """
    import datetime as _d
    oggi = _d.date.today()
    got = 0
    coppie = []
    for k in range(months):
        m = oggi.month - k
        y = oggi.year
        while m <= 0:
            m += 12
            y -= 1
        coppie.append((m, y))
    for month, year in coppie:
        try:
            rows = malcesine.fetch_intraday(month, year)
        except FetchError as e:
            _note("warn", "intraday/Malcesine",
                  "aggiornamento %02d/%d: %s" % (month, year, str(e)[:90]))
            continue
        if rows:
            store.save_samples("malcesine", rows, "meteoproject-intraday")
            got += len(rows)
    if got:
        aggregate.aggregate_station("malcesine",
                                    since_iso=day_shift(oggi.isoformat(), -70))
    return got


def backfill_station_history(force=False, on_progress=None):
    """Scarica una volta sola gli archivi storici pubblici delle due centraline."""
    out = []

    if force or not store.meta_get("backfill_torbole"):
        try:
            # Si salva anno per anno, appena arriva: se lo scaricamento si
            # interrompe a meta' (rete, chiusura dell'app, timeout del
            # servizio) quello gia' preso resta a terra e la volta dopo si
            # riparte da dove si era rimasti.
            saved = {"n": 0, "years": 0}

            def on_year(year, rows, err):
                if err:
                    _note("warn", "archivio/Torbole", "%d: %s" % (year, err))
                    return
                store.save_samples("T0193", rows, "meteotrentino-archivio")
                saved["n"] += len(rows)
                saved["years"] += 1
                store.meta_set("backfill_torbole_last_year", year)
                if on_progress:
                    on_progress("  Torbole %d: %d misure (totale %d)"
                                % (year, len(rows), saved["n"]))

            resume = store.meta_get("backfill_torbole_last_year")
            meteotrentino.fetch_archive(
                on_year=on_year,
                from_year=(int(resume) + 1) if resume else None)
            aggregate.aggregate_station("T0193")
            rows = []
            store.meta_set("backfill_torbole", iso_utc(utc_now()))
            out.append("Torbole: %d misure a 10 minuti su %d anni"
                       % (saved["n"], saved["years"]))
            # Controllo incrociato fra archivio e realtime: se le due sorgenti
            # fossero su fusi diversi lo si vedrebbe qui, non fra sei mesi.
            try:
                live = meteotrentino.fetch_realtime(hours=48)
                stored = [(r["hour"], r["wind_mean"], None, None)
                          for r in store.obs_hours("T0193")]
                n, agree, gap = meteotrentino.consistency_check(stored, live)
                if n and agree is not None and agree < 0.8:
                    _note("warn", "coerenza/Torbole",
                          "archivio e realtime divergono su %d istanti comuni "
                          "(accordo %.0f%%, scarto medio %.2f kn)" % (n, agree * 100, gap))
                else:
                    store.meta_set("torbole_consistency", "%d/%s" % (n, agree))
            except FetchError:
                pass
        except FetchError as e:
            _note("error", "archivio/Torbole", str(e)[:200])

    # Archivio INTRADAY di Malcesine: e' quello che permette di separare il
    # Peler dall'Ora. Il report NOAA giornaliero da' un solo numero al giorno
    # e non dice a che ora e' successo.
    if force or not store.meta_get("backfill_malcesine_intraday"):
        got = 0
        for month, year in malcesine.intraday_months():
            try:
                rows = malcesine.fetch_intraday(month, year)
            except FetchError as e:
                _note("warn", "intraday/Malcesine",
                      "%02d/%d: %s" % (month, year, str(e)[:90]))
                continue
            if not rows:
                continue
            store.save_samples("malcesine", rows, "meteoproject-intraday")
            got += len(rows)
            if on_progress:
                on_progress("  Malcesine %02d/%d: %d misure intraday" % (month, year, len(rows)))
        if got:
            aggregate.aggregate_station("malcesine")
            store.meta_set("backfill_malcesine_intraday", iso_utc(utc_now()))
            out.append("Malcesine: %d misure intraday" % got)
        else:
            _note("warn", "intraday/Malcesine", "nessun mese intraday scaricabile")

    if force or not store.meta_get("backfill_malcesine"):
        total = 0
        for month, year in malcesine.available_months():
            try:
                rows = malcesine.fetch_month(month, year)
                total += store.save_day_obs("malcesine", rows, "meteoproject-noaa")
            except FetchError:
                continue
            if on_progress and total:
                on_progress("  Malcesine %02d/%d: %d giorni finora" % (month, year, total))
        if total:
            store.meta_set("backfill_malcesine", iso_utc(utc_now()))
            out.append("Malcesine: %d giorni di archivio" % total)
        else:
            _note("warn", "archivio/Malcesine", "nessun report mensile scaricabile")
    return out


# ==========================================================================
# Predittori storici
# ==========================================================================

def _obs_span(station):
    st = store.obs_stats(station)
    days = [d for d in (st["hour_from"], st["day_from"]) if d]
    if not days:
        return None, None
    start = min(d[:10] for d in days)
    ends = [d for d in (st["hour_to"], st["day_to"]) if d]
    return start, max(d[:10] for d in ends)


def backfill_era5_features(chunk_days=730):
    """Rianalisi ERA5 di superficie, dall'inizio delle osservazioni.

    E' cio' che permette di addestrare su quattordici anni invece che su
    cinque: l'archivio delle previsioni non risale oltre, ma le osservazioni
    di Torbole partono dal 2012. Il prezzo e' la mancanza dei livelli
    isobarici, e il confronto fra i due addestramenti lo arbitra il modello.
    """
    today = _dt.date.today()
    end_day = (today - _dt.timedelta(days=6)).isoformat()   # ERA5 ha ~5 gg di ritardo

    starts = []
    for station in {s["station"] for s in config.SPOTS.values()}:
        a, _b = _obs_span(station)
        if a:
            starts.append(a)
    if not starts:
        return ["nessuna osservazione: niente da allineare"]
    start_day = max(min(starts), config.ERA5_START)

    out = []
    for _key, (lat, lon) in _points().items():
        point = store.point_key(lat, lon, "era5")
        _a, have_b, _n = store.archive_span(point)
        cursor = start_day
        if have_b and have_b[:10] >= start_day:
            cursor = day_shift(have_b[:10], 1)
        got = 0
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_era5(lat, lon, cursor, stop)
                store.save_archive(point, rows)
                got += len(rows)
            except FetchError as e:
                _note("warn", "era5", "%s %s: %s" % (point, cursor, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
        if got:
            out.append("%s: %d ore ERA5" % (point, got))

    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        row = store.connect().execute(
            "SELECT MAX(valid) v FROM ctx_hour WHERE kind='era5' AND place=?",
            (place,)).fetchone()
        cursor = start_day
        if row and row["v"] and row["v"][:10] >= start_day:
            cursor = day_shift(row["v"][:10], 1)
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_era5_context(lat, lon, cursor, stop)
                store.save_context(place, "era5", rows)
            except FetchError as e:
                _note("warn", "era5-contesto", "%s: %s" % (place, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
    return out


def backfill_lead_features(leads=None, chunk_days=180):
    """Predittori COME ERANO all'emissione, una copia per scadenza.

    Senza questo archivio non esiste alcun modo onesto di dire quanto vale la
    previsione a D+3: l'archivio ordinario (historical-forecast) contiene le
    prime ore di ogni run, cioe' una scadenza di poche ore, e un modello
    addestrato su quello e applicato a D+3 promette un'accuratezza che a D+3
    non ha. Qui ogni scadenza ha il proprio archivio, i propri campioni e le
    proprie metriche.

    L'archivio delle run precedenti parte dal 2024, quindi le scadenze lunghe
    avranno sempre meno giornate delle corte. E' un limite dei dati, non un
    difetto da nascondere: dove le giornate non bastano, la scadenza resta
    dichiarata non validata.
    """
    leads = leads or config.PREV_RUN_LEADS
    today = _dt.date.today()
    end_day = (today - _dt.timedelta(days=1)).isoformat()

    starts = []
    for station in {s["station"] for s in config.SPOTS.values()}:
        a, _b = _obs_span(station)
        if a:
            starts.append(a)
    if not starts:
        return ["nessuna osservazione: niente da allineare"]
    start_day = max(min(starts), config.PREV_RUN_START)

    out = []
    for lead in leads:
        source = "lead%d" % lead
        for _key, (lat, lon) in _points().items():
            point = store.point_key(lat, lon, source)
            _a, have_b, _n = store.archive_span(point)
            cursor = start_day
            if have_b and have_b[:10] >= start_day:
                cursor = day_shift(have_b[:10], 1)
            got = 0
            while cursor <= end_day:
                stop = min(day_shift(cursor, chunk_days - 1), end_day)
                try:
                    rows = openmeteo.fetch_lead_features(lat, lon, lead, cursor, stop)
                    store.save_archive(point, rows)
                    got += len(rows)
                except FetchError as e:
                    _note("warn", source, "%s %s: %s" % (point, cursor, str(e)[:100]))
                    break
                cursor = day_shift(stop, 1)
            if got:
                out.append("%s %s: %d ore" % (source, point, got))

        for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
            row = store.connect().execute(
                "SELECT MAX(valid) v FROM ctx_hour WHERE kind=? AND place=?",
                (source, place)).fetchone()
            cursor = start_day
            if row and row["v"] and row["v"][:10] >= start_day:
                cursor = day_shift(row["v"][:10], 1)
            while cursor <= end_day:
                stop = min(day_shift(cursor, chunk_days - 1), end_day)
                try:
                    rows = openmeteo.fetch_lead_features(
                        lat, lon, lead, cursor, stop, context=True)
                    store.save_context(place, source, rows)
                except FetchError as e:
                    _note("warn", source + "-contesto", "%s: %s" % (place, str(e)[:100]))
                    break
                cursor = day_shift(stop, 1)
    return out


def backfill_archive_features(max_years=5, chunk_days=180):
    """Scarica i predittori storici (historical-forecast, best_match).

    Si ferma al periodo effettivamente coperto dalle osservazioni: scaricare
    predittori per giorni senza bersaglio e' solo traffico sprecato.
    """
    today = _dt.date.today()
    horizon = (today - _dt.timedelta(days=int(365.25 * max_years))).isoformat()

    starts = []
    for station in {s["station"] for s in config.SPOTS.values()}:
        a, _b = _obs_span(station)
        if a:
            starts.append(a)
    if not starts:
        return ["nessuna osservazione: niente da allineare"]
    start_day = max(min(starts), horizon)
    end_day = (today - _dt.timedelta(days=1)).isoformat()

    out = []
    for point, (lat, lon) in _points().items():
        have_a, have_b, _n = store.archive_span(point)
        cursor = start_day
        if have_b and have_b[:10] >= start_day:
            cursor = day_shift(have_b[:10], 1)
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_archive(lat, lon, cursor, stop)
                store.save_archive(point, rows)
            except FetchError as e:
                _note("warn", "archivio-feature", "%s %s: %s" % (point, cursor, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
        out.append("%s fino a %s" % (point, cursor))

    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        have_a, have_b, _n = store.context_span("arch")
        cursor = start_day
        row = store.connect().execute(
            "SELECT MAX(valid) v FROM ctx_hour WHERE kind='arch' AND place=?",
            (place,)).fetchone()
        if row and row["v"] and row["v"][:10] >= start_day:
            cursor = day_shift(row["v"][:10], 1)
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_archive_context(lat, lon, cursor, stop)
                store.save_context(place, "arch", rows)
            except FetchError as e:
                _note("warn", "archivio-contesto", "%s: %s" % (place, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
    return out


# ==========================================================================
# Costruzione del campione di addestramento
# ==========================================================================

_TARGET_CACHE = {}


def _targets(spot_name, use_cache=True):
    """Bersaglio giornaliero osservato: {giorno: (valore, instaurato)}."""
    if use_cache:
        hit = _TARGET_CACHE.get(spot_name)
        if hit and time.time() - hit[0] < PRODUCT_TTL_S:
            return hit[1]
    result = _compute_targets(spot_name)
    _TARGET_CACHE[spot_name] = (time.time(), result)
    return result


def _compute_targets(spot_name):
    spot = config.SPOTS[spot_name]
    out = {}

    if spot["target"] == "daily_gust":
        for row in store.obs_days(spot["station"]):
            g = row["gust_max"]
            if g is None:
                continue
            out[row["day"]] = (g, g >= spot["min_kn"], None, None)
        return out

    h0, h1 = spot["window"]
    need = max(3, int(config.MIN_WINDOW_COVERAGE * (h1 - h0 + 1)))
    by_day = {}
    for row in store.obs_hours(spot["station"]):
        dt = parse_dt_any(row["hour"])
        if dt is None or row["wind_mean"] is None:
            continue
        if not (h0 <= local_hour(dt) <= h1):
            continue
        # Un'ora ricostruita da pochissimi campioni non e' una media oraria.
        if (row["n_samples"] or 0) < 2:
            continue
        by_day.setdefault(local_day(dt), []).append(
            (local_hour(dt), row["wind_mean"], row["dir_deg"]))

    for day, vals in by_day.items():
        if len(vals) < need:
            continue                 # copertura insufficiente: giorno ESCLUSO,
                                     # non messo a zero. Dato mancante non e'
                                     # assenza di vento.
        vals.sort()
        peak_hour, peak, peak_dir = max(vals, key=lambda x: x[1])

        # "Instaurato" richiede la direzione giusta, non solo l'intensita'.
        # Quindici nodi da sud alle otto del mattino a Torbole sono vento,
        # ma non sono il Peler: per il modello del Peler quel giorno e' un
        # NEGATIVO corretto, non un positivo.
        #
        # Il confronto si fa contro l'asse OSSERVATO, non contro quello
        # geometrico. Sono trenta gradi di differenza sul Peler di Torbole
        # (vedi config.OBS_AXIS), e giudicare una direzione misurata dalla
        # centralina con un riferimento preso dalla mappa significa spostare
        # il bersaglio di trenta gradi rispetto a cio' che la centralina vede.
        axis_obs = spot.get("axis_obs", spot["axis"])
        in_sector = (peak_dir is None or
                     angle_diff(peak_dir, axis_obs) <= config.REGIME_SECTOR_DEG)
        established = peak >= spot["min_kn"] and in_sector

        onset = next((h for h, v, d in vals
                      if v >= spot["min_kn"]
                      and (d is None or angle_diff(d, axis_obs)
                           <= config.REGIME_SECTOR_DEG)), None)
        out[day] = (peak, established, float(peak_hour),
                    float(onset) if onset is not None else None)
    return out


def source_lead(source):
    """Scadenza in giorni implicata da una sorgente di predittori.

    "lead3" -> 3. "forecast" ed "era5" non hanno una scadenza dichiarata: le
    prime ore di ogni run e la rianalisi descrivono lo stato quasi-attuale,
    quindi valgono come scadenza zero. Dichiararlo qui, in un posto solo,
    evita che la stessa assunzione venga fatta in modo diverso altrove.
    """
    if source.startswith("lead"):
        try:
            return int(source[4:])
        except ValueError:
            return 0
    return 0


def _ctx_kind(source):
    if source == "forecast":
        return "arch"
    return source                      # "era5", "lead1".. usano il proprio


def build_samples(spot_name, source="forecast"):
    """Coppie (predittori storici, bersaglio osservato) pronte per l'addestramento.

    `source` sceglie l'archivio dei predittori:
      "forecast"  archivio delle previsioni, con i livelli isobarici, ~5 anni
      "era5"      rianalisi di sola superficie, ma dal 2012
      "leadN"     previsione come era N giorni prima del bersaglio, dal 2024

    La memoria (`persist_obs`) viene sempre presa all'eta' che avrebbe avuto
    all'emissione: per la scadenza N l'ultimo giorno interamente osservato e'
    N+1 giorni prima del bersaglio. Lo stesso conto lo fa `forecast_days` in
    esercizio, ed e' la ragione per cui le due strade ora combaciano.
    """
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"], source)
    targets = _targets(spot_name)
    if not targets:
        return []
    lead = source_lead(source)
    age = lead + 1

    days = sorted(targets)
    lo, hi = days[0], days[-1]
    rows = store.archive_rows(point, day_shift(lo, -2) + "T00:00:00Z",
                              day_shift(hi, 1) + "T23:00:00Z")
    hours = {r["valid"]: {k: r[k] for k in store.FC_COLS} for r in rows}
    if not hours:
        return []
    ctx = store.context_map(_ctx_kind(source),
                            day_shift(lo, -2) + "T00:00:00Z",
                            day_shift(hi, 1) + "T23:00:00Z")

    samples = []
    for day in days:
        prev = targets.get(day_shift(day, -age))
        feats = F.daily_features(spot_name, day, hours, ctx,
                                 persist=prev[0] if prev else None,
                                 persist_age=age)
        if feats is None:
            continue
        peak, established, peak_hour, onset = targets[day]
        samples.append({"day": day, "features": feats, "peak": peak,
                        "established": established, "lead": lead,
                        "peak_hour": peak_hour, "onset_hour": onset})
    return samples


def samples_by_lead(spot_name):
    """{scadenza: campioni}. La scadenza 0 viene dall'archivio ordinario."""
    out = {}
    fc = build_samples(spot_name, "forecast")
    if fc:
        out[0] = fc
    for lead in config.PREV_RUN_LEADS:
        got = build_samples(spot_name, "lead%d" % lead)
        if got:
            out[lead] = got
    return out


def train_bands(spot_name, tier="surface", by_lead=None, bands=None):
    """Un modello per fascia di scadenza, ognuno validato a se'.

    Il livello e' "surface" perche' l'archivio delle run precedenti non espone
    i livelli isobarici: mettere insieme fasce addestrate su vettori diversi
    renderebbe il confronto fra scadenze privo di significato, ed e' proprio il
    confronto fra scadenze la cosa da misurare.
    """
    by_lead = by_lead if by_lead is not None else samples_by_lead(spot_name)
    report = []
    for name, (a, b) in (bands or config.LEAD_BANDS):
        pooled = []
        for lead in range(a, b + 1):
            pooled.extend(by_lead.get(lead) or [])
        if len(pooled) < 120:
            report.append({"band": name, "n": len(pooled),
                           "leads": [l for l in range(a, b + 1) if by_lead.get(l)],
                           "status": "dati insufficienti"})
            continue
        r = V.fit_band(spot_name, pooled, tier, name)
        if not r:
            report.append({"band": name, "n": len(pooled),
                           "status": "periodo troppo corto per il forward chaining"})
            continue
        metrics = {k: v for k, v in r.items() if k != "payload"}
        # Nomi che model.predict conosce gia', per non avere due vocabolari.
        # "usable" qui vuol dire esattamente "ha superato le porte a QUESTA
        # fascia": nessuna promozione ereditata da un'altra scadenza.
        metrics.update({
            "lead_band": name,
            # Una porta per stadio: "usable" e' l'intensita', "usable_occurrence"
            # la probabilita'. Si promuovono separatamente (vedi model.predict).
            "usable": r["gain_int"]["significativo"],
            "usable_occurrence": r["gain_prob"]["significativo"],
            "base_rate": (r["prob"] or {}).get("base_rate"),
            "brier": (r["prob"] or {}).get("brier"),
            "brier_base": (r["prob"] or {}).get("brier_base"),
            "mae": (r["intensity"] or {}).get("mae"),
            "mae_base": (r["intensity"] or {}).get("mae_raw"),
        })
        store.save_learned(spot_name, "daily@" + name, tier, r["n"],
                           r["payload"], metrics)
        report.append({"band": name, "n": r["n"], "n_test": r["n_test"],
                       "leads": r["leads"], "status": "ok",
                       "validata": r["validated"],
                       "brier": (r["prob"] or {}).get("brier"),
                       "brier_base": (r["prob"] or {}).get("brier_base"),
                       "mae": (r["intensity"] or {}).get("mae"),
                       "mae_raw": (r["intensity"] or {}).get("mae_raw")})
    return report


def learned_by_band(spot_name):
    """{fascia: modello appreso}. Assente = quella fascia non e' validata."""
    out = {}
    for name, _rng in config.LEAD_BANDS:
        got = store.load_learned(spot_name, "daily@" + name)
        if got:
            out[name] = got
    return out


def train_all():
    report = []
    for spot_name in config.SPOTS:
        sources = {}
        for src in ("forecast", "era5"):
            got = build_samples(spot_name, src)
            if got:
                sources[src] = got
        fc = sources.get("forecast") or []
        if len(fc) < 30:
            report.append({"spot": spot_name, "n": len(fc), "status": "pochi dati"})
            continue

        chosen, candidates = M.train(spot_name, sources)
        if chosen is None:
            report.append({"spot": spot_name, "n": len(fc),
                           "status": "nessun candidato adottabile"})
            continue
        metrics = M.metrics_of(chosen)
        learned = {"payload": M.serialize(chosen), "metrics": metrics}
        cov, ncov = M.verify_intervals(fc, learned)
        metrics["coverage"] = cov
        metrics["coverage_n"] = ncov
        metrics["candidates"] = [
            {"source": c.get("source"), "tier": c["tier"], "n": c["n"],
             "brier": c["brier"], "mae": c["mae"], "usable": c["usable"]}
            for c in candidates]
        store.save_learned(spot_name, "daily", chosen["tier"], chosen["n"],
                           M.serialize(chosen), metrics)

        # Terzo stadio: l'orario. Si addestra sul set piu' ampio disponibile
        # che abbia i livelli isobarici, perche' il livello "timing" li usa.
        line = {"spot": spot_name, "n": chosen["n"], "status": "ok",
                "source": chosen.get("source"), "tier": chosen["tier"],
                "usable": chosen["usable"], "mae": chosen["mae"],
                "brier": chosen["brier"]}
        if config.SPOTS[spot_name]["target"] == "hourly":
            t = M.train_timing(fc)
            if t:
                store.save_learned(spot_name, "timing", t["tier"], t["n"],
                                   t["payload"],
                                   {k: v for k, v in t.items() if k != "payload"})
                line["timing_min"] = t["mae_minutes"]
                line["timing_usable"] = t["usable"]

        # Un modello per fascia di scadenza, dove l'archivio per-lead lo
        # consente. Le fasce senza dati restano senza modello, e la previsione
        # a quelle scadenze esce dichiarata non validata.
        try:
            line["fasce"] = train_bands(spot_name)
        except Exception as e:                       # pragma: no cover
            _note("warn", "fasce", "%s: %s" % (spot_name, str(e)[:140]))
            line["fasce"] = [{"status": "errore: %s" % str(e)[:80]}]
        report.append(line)
    store.meta_set("last_training", iso_utc(utc_now()))
    return report


def verify_all(days=420):
    """Misura la skill di ogni modello contro le osservazioni."""
    today = _dt.date.today()
    end = (today - _dt.timedelta(days=2)).isoformat()
    start = (today - _dt.timedelta(days=days)).isoformat()
    done = 0
    for spot_name, spot in config.SPOTS.items():
        if spot["target"] != "hourly":
            continue
        observed = verify.observed_daily_peaks(spot_name)
        if len(observed) < verify.MIN_DAYS_FOR_SKILL:
            continue
        for model_name in config.MODELS:
            for lead in config.VERIFY_LEADS:
                try:
                    stats = verify.verify_model(
                        spot_name, model_name, lead, openmeteo.fetch_previous_run,
                        start, end, observed)
                except FetchError as e:
                    _note("warn", "verifica/%s" % model_name, str(e)[:120])
                    continue
                if stats:
                    store.save_skill(spot_name, model_name, lead, stats)
                    done += 1
    store.meta_set("last_verification", iso_utc(utc_now()))
    return done


# ==========================================================================
# Ensemble
# ==========================================================================

def ensemble_hours(spot_name):
    """Media pesata dei modelli, ora per ora, piu' la dispersione.

    I pesi vengono dalla verifica contro centralina quando esiste, altrimenti
    da un prior sulla risoluzione. Ogni famiglia di modelli entra una volta
    sola: contare ICON-EU, ICON Global e ICON Seamless come tre pareri
    indipendenti restringe artificialmente la dispersione e fa sembrare la
    previsione piu' sicura di quanto sia.
    """
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"])
    runs = store.latest_runs(point)
    if not runs:
        return {}, {}, 0, "nessuna"

    newest = max(runs.values())
    fresh = {m: r for m, r in runs.items()
             if (parse_dt_any(newest) - parse_dt_any(r)).total_seconds() <= 6 * 3600}
    if not fresh:
        fresh = runs

    today = local_day(utc_now())
    per_model = {}
    for m, run in fresh.items():
        per_model[m] = {r["valid"]: r for r in store.forecast_rows(point, m, run)}

    weights_cache = {}

    def weights_for(lead):
        if lead not in weights_cache:
            weights_cache[lead] = verify.compute_weights(spot_name, clamp(lead, 1, 3))
        return weights_cache[lead]

    all_valid = sorted({v for rows in per_model.values() for v in rows})
    out, spread = {}, {}
    origin = "prior"
    for valid in all_valid:
        dt = parse_dt_any(valid)
        lead = max(0, (_dt.date.fromisoformat(local_day(dt))
                       - _dt.date.fromisoformat(today)).days)
        wmap, origin = weights_for(lead)

        members = []
        for m, rows in per_model.items():
            r = rows.get(valid)
            if not r or r["w10"] is None:
                continue
            bias = verify.model_bias(spot_name, m, int(clamp(lead, 1, 3)))
            members.append((m, wmap.get(m, 0.0), r, bias))
        if not members:
            continue
        total = sum(w for _m, w, _r, _b in members) or 1.0

        agg = {}
        for col in store.FC_COLS:
            if col in ("d10", "d925", "d850", "d700"):
                continue
            num = den = 0.0
            for _m, w, r, bias in members:
                v = r[col]
                if v is None:
                    continue
                if col == "w10":
                    v = max(0.0, v - bias)
                num += w * v
                den += w
            agg[col] = (num / den) if den > 0 else None

        for dcol, scol in (("d10", "w10"), ("d925", "w925"),
                           ("d850", "w850"), ("d700", "w700")):
            pairs = [(r[scol] or 1.0, r[dcol]) for _m, _w, r, _b in members
                     if r[dcol] is not None]
            agg[dcol] = vector_mean_direction(pairs)[0]

        out[valid] = agg
        vals = [max(0.0, r["w10"] - b) for _m, _w, r, b in members if r["w10"] is not None]
        spread[valid] = pstdev(vals, 0.0)

    return out, spread, len(per_model), origin


# ==========================================================================
# Prodotto finale
# ==========================================================================

GRADES = (
    (22, "ECCEZIONALE"),
    (18, "MOLTO BUONO"),
    (14, "BUONO"),
    (11, "SI PLANA A TRATTI"),
    (8, "MARGINALE"),
    (0, "TROPPO POCO"),
)


def grade(speed, prob=None):
    """Giudizio sintetico: unisce quanto tira e quanto e' probabile che tiri.

    Tenere separati i due numeri porta a schede incoerenti del tipo "90% di
    probabilita'" accanto a "6 nodi". Il giudizio deve dire una cosa sola.
    """
    label = GRADES[-1][1]
    for threshold, name in GRADES:
        if speed >= threshold:
            label = name
            break
    if prob is None:
        return label
    if prob < 0.25:
        return "IMPROBABILE"
    if prob < 0.45:
        return label + " · INCERTO"
    return label


def last_observed_peak(spot_name, today=None):
    """Ultimo picco osservato con la finestra GIA' CHIUSA, e la sua data.

    E' l'unica memoria che un utente possiede al mattino: il giorno di ieri.
    Vale identica per tutte le scadenze dell'orizzonte; cio' che cambia con la
    scadenza e' solo la sua eta'. Si tollera un buco di qualche giorno
    (centralina muta) risalendo indietro, perche' un ricordo di tre giorni
    dichiarato tale e' meglio di uno zero.
    """
    targets = _targets(spot_name)
    today = today or local_day(utc_now())
    for back in range(1, 5):
        day = day_shift(today, -back)
        hit = targets.get(day)
        if hit:
            return hit[0], day
    return None, None


def forecast_days(spot_name, horizon=None):
    """Previsione giorno per giorno per uno spot-regime."""
    horizon = horizon or config.MAX_LEAD_DAYS
    hours, spread, nmodels, weight_origin = ensemble_hours(spot_name)
    if not hours:
        return []

    ctx = store.context_map("live")
    learned = store.load_learned(spot_name, "daily")
    by_band = learned_by_band(spot_name)
    timing = store.load_learned(spot_name, "timing")
    today = local_day(utc_now())
    mem_peak, mem_day = last_observed_peak(spot_name, today)

    spot = config.SPOTS[spot_name]
    days = sorted({local_day(parse_dt_any(v)) for v in hours})
    out = []
    for day in days:
        if day < today:
            continue
        lead = (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(today)).days
        if lead > horizon:
            continue
        # La memoria e' la stessa per tutto l'orizzonte (l'ultimo giorno
        # osservato), quello che cambia e' quanto e' vecchia rispetto al
        # bersaglio. Esattamente il conto che fa build_samples.
        age = (_dt.date.fromisoformat(day)
               - _dt.date.fromisoformat(mem_day)).days if mem_day else lead + 1
        feats = F.daily_features(spot_name, day, hours, ctx,
                                 persist=mem_peak, persist_age=age)
        if feats is None:
            continue

        win_keys = [k for k in F.window_hours(day, *config.SPOTS[spot_name]["window"])
                    if k in hours]
        sp = mean([spread.get(k) for k in win_keys])
        sp = 3.0 if sp is None else sp
        # Con pochi membri la dispersione non misura l'incertezza, misura solo
        # quanti modelli hanno risposto: non puo' valere come rassicurazione.
        if nmodels < 3:
            sp = max(sp, 4.0)
        win_pairs = [(hours[k].get("w10") or 0.0, hours[k].get("d10")) for k in win_keys]
        dir_pred, dir_const = vector_mean_direction(win_pairs)
        # Il modello di QUESTA fascia, se e' stato validato; altrimenti quello
        # generale, che pero' esce marcato come non validato a questa scadenza.
        band = config.band_for_lead(lead)
        use = by_band.get(band) or learned
        pred = M.predict(spot_name, feats, use, lead, sp, direction=dir_pred)

        peak_hour, peak_hour_src = M.predict_timing(
            feats, timing, day, fallback=feats.get("raw_peak_hour"))
        pred["peak_hour"] = peak_hour
        pred["peak_hour_source"] = peak_hour_src
        pred["peak_hour_mae_min"] = (timing or {}).get("metrics", {}).get("mae_minutes")

        # Affidabilita': non dalla scadenza, dalle misure fatte A QUESTA
        # scadenza su QUESTO spot. Se la fascia non e' stata misurata,
        # metrics_lead resta None e l'etichetta scende a "outlook" da se'.
        per_lead = ((use or {}).get("metrics") or {}).get("per_lead") or {}
        metrics_lead = per_lead.get(lead) or per_lead.get(str(lead))
        off = angle_diff(dir_pred, spot["axis"]) if dir_pred is not None else None
        pred["affidabilita"] = CONF.assess(
            spot_name, lead, metrics_lead, spread_kn=sp,
            dir_penalty=pred.get("dir_penalty"), dir_offset=off,
            ambiguo=bool(off is not None
                         and config.REGIME_SECTOR_DEG - 15 <= off <= config.REGIME_SECTOR_DEG + 15))

        shape = F.hourly_shape(spot_name, day, hours)
        profile = []
        for key, rel in shape:
            dt = parse_dt_any(key)
            gust_ratio = 1.0
            g = hours[key].get("g10")
            w = hours[key].get("w10")
            if g and w and w > 0.5:
                gust_ratio = clamp(g / w, 1.0, 2.2)
            value = pred["speed"] * rel
            profile.append({
                "hour_local": local_hour(dt),
                "key": key,
                "wind": value,
                "gust": value * gust_ratio,
                "spread": spread.get(key) if spread.get(key) is not None else 0.0,
            })

        in_sector = (dir_pred is None or
                     angle_diff(dir_pred, spot["axis"]) <= config.REGIME_SECTOR_DEG)

        # Se il vento previsto NON viene dal settore del regime, la previsione
        # del regime non e' la risposta giusta: il modello e' addestrato sui
        # giorni in cui quel regime c'era. Si dichiara l'altro vento per quello
        # che e', con il valore grezzo dei modelli e senza correzione appresa.
        other = None
        if not in_sector:
            raw = feats.get("w10_max") or feats.get("w10_win") or 0.0
            other = {
                "speed": raw,
                "dir": dir_pred,
                "steady": dir_const,
                "usable": raw >= spot["planing_kn"] * 0.8,
                "along_lake": angle_diff(dir_pred, config.LAKE_AXIS_ORA) <= 55
                or angle_diff(dir_pred, config.LAKE_AXIS_PELER) <= 55,
            }

        best = _best_window(profile, config.SPOTS[spot_name])
        out.append({
            "spot": spot_name,
            "day": day,
            "lead": lead,
            "prob": pred["prob"],
            "speed": pred["speed"],
            "lo": pred["lo"],
            "hi": pred["hi"],
            "source": pred["source"],
            "source_prob": pred["source_prob"],
            "source_int": pred["source_int"],
            "band_source": pred["band_source"],
            "lead_band": pred["lead_band"],
            "validata": pred["validata"],
            "validata_prob": pred["validata_prob"],
            "validata_int": pred["validata_int"],
            "affidabilita": pred["affidabilita"],
            "tier": pred["tier"],
            "mae": pred["mae"],
            "brier": pred["brier"],
            "brier_base": pred["brier_base"],
            "n_train": pred["n"],
            "dir": dir_pred,
            "dir_steady": dir_const,
            "in_sector": in_sector,
            "other_wind": other,
            "peak_hour": pred["peak_hour"],
            "peak_hour_source": pred["peak_hour_source"],
            "peak_hour_mae_min": pred["peak_hour_mae_min"],
            "spread": sp,
            "n_models": nmodels,
            "weights": weight_origin,
            "grade": grade(pred["speed"], pred["prob"]),
            "profile": profile,
            "window": best,
            "features": feats,
        })
    return out


def _best_window(profile, spot):
    """Fascia oraria contigua con il vento piu' utilizzabile."""
    usable = [p for p in profile if spot["window"][0] <= p["hour_local"] <= spot["window"][1]]
    if not usable:
        return None
    peak = max(usable, key=lambda p: p["wind"])
    threshold = max(spot["min_kn"] * 0.85, peak["wind"] * 0.75)
    runs, cur = [], []
    for p in usable:
        if p["wind"] >= threshold and (not cur or p["hour_local"] == cur[-1]["hour_local"] + 1):
            cur.append(p)
        elif p["wind"] >= threshold:
            if cur:
                runs.append(cur)
            cur = [p]
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        runs = [[peak]]
    best = max(runs, key=lambda r: (peak in r, mean([p["wind"] for p in r]) * len(r)))

    # Minuti per interpolazione, non per invenzione. Il profilo e' orario, ma la
    # curva del vento e' continua: l'istante in cui attraversa la soglia si
    # stima interpolando fra l'ora sotto e l'ora sopra. Non aggiunge
    # informazione, rende leggibile quella che c'e' - la differenza fra "dalle
    # 8" e "dalle 8:40" e' dentro i dati orari, basta non buttarla via
    # arrotondando.
    #
    # Resta un secondo limite, molto piu' grande di questo: l'errore sull'ORA
    # del picco, che si misura in decine di minuti. Per questo i minuti si
    # mostrano solo dove lo stadio dell'orario e' stato validato a quella
    # scadenza; altrove si dichiara che l'orario e' incerto (vedi web.py). Un
    # 08:10 accanto a un'incertezza di due ore sarebbe precisione finta.
    byh = {p["hour_local"]: p["wind"] for p in usable}

    def cross(h, prev_h):
        """Minuto in cui la curva passa per `threshold` fra prev_h e h."""
        a, b = byh.get(prev_h), byh.get(h)
        if a is None or b is None or a == b:
            return h * 60.0
        t = clamp((threshold - a) / (b - a), 0.0, 1.0)
        return (prev_h + t) * 60.0

    h0, h1 = best[0]["hour_local"], best[-1]["hour_local"]
    start_min = cross(h0, h0 - 1) if (h0 - 1) in byh else h0 * 60.0
    end_min = cross(h1 + 1, h1) if (h1 + 1) in byh else (h1 + 1) * 60.0
    return {
        "from": h0,
        "to": h1 + 1,
        "from_min": start_min,
        "to_min": max(end_min, start_min + 20.0),
        "mean": mean([p["wind"] for p in best]),
        "peak": peak["wind"],
        "peak_hour": peak["hour_local"],
        "gust": max(p["gust"] for p in best),
    }


_PRODUCT_CACHE = {"at": 0.0, "value": None}
PRODUCT_TTL_S = 90


def full_product(force=False):
    """Previsione completa, con una breve cache.

    Ogni ricostruzione rilegge tutte le osservazioni orarie e ricalcola
    l'ensemble per cinque coppie spot/regime: senza cache un semplice
    aggiornamento di pagina rifarebbe tutto il lavoro.
    """
    now = time.time()
    if not force and _PRODUCT_CACHE["value"] is not None \
            and now - _PRODUCT_CACHE["at"] < PRODUCT_TTL_S:
        return _PRODUCT_CACHE["value"]
    value = {name: forecast_days(name) for name in config.SPOT_ORDER}
    _PRODUCT_CACHE.update({"at": now, "value": value})
    return value


def invalidate_product():
    _PRODUCT_CACHE["value"] = None


# ==========================================================================
# Cicli di aggiornamento
# ==========================================================================

def _age_minutes(key):
    v = store.meta_get(key)
    if not v:
        return 1e9
    dt = parse_dt_any(v)
    return 1e9 if dt is None else (utc_now() - dt).total_seconds() / 60.0


def update_cycle(force=False, deep=True):
    if not _LOCK.acquire(False):
        return False
    STATE.update({"running": True, "started": iso_utc(utc_now()),
                  "phase": "previsioni", "errors": []})
    try:
        update_forecasts()
        STATE["phase"] = "contesto"
        update_context()
        STATE["phase"] = "centraline"
        update_stations()

        if deep:
            STATE["phase"] = "archivio centraline"
            backfill_station_history(force=False)
            # Gli ultimi due mesi di Malcesine a ogni ciclo: recupera cio' che
            # la lettura istantanea non ha visto. Due richieste, idempotenti.
            try:
                n_intra = refresh_malcesine_intraday()
                if n_intra:
                    store.meta_set("last_malcesine_refresh", iso_utc(utc_now()))
            except Exception as e:                      # pragma: no cover
                _note("warn", "intraday/Malcesine", str(e)[:140])
            STATE["phase"] = "predittori storici"
            if force or _age_minutes("last_archive_backfill") > 24 * 60:
                backfill_archive_features()
                store.meta_set("last_archive_backfill", iso_utc(utc_now()))
            STATE["phase"] = "rianalisi ERA5"
            if force or _age_minutes("last_era5_backfill") > 7 * 24 * 60:
                backfill_era5_features()
                store.meta_set("last_era5_backfill", iso_utc(utc_now()))
            STATE["phase"] = "predittori per scadenza"
            if force or _age_minutes("last_lead_backfill") > 24 * 60:
                backfill_lead_features()
                store.meta_set("last_lead_backfill", iso_utc(utc_now()))
            STATE["phase"] = "verifica modelli"
            if force or _age_minutes("last_verification") > 7 * 24 * 60:
                verify_all()
            STATE["phase"] = "addestramento"
            if force or _age_minutes("last_training") > 12 * 60:
                train_all()

        store.meta_set("last_update", iso_utc(utc_now()))
        invalidate_product()
        STATE["phase"] = "pronto"
        return True
    except Exception as e:                                   # pragma: no cover
        _note("error", "ciclo", "%s: %s" % (type(e).__name__, e))
        return False
    finally:
        STATE.update({"running": False, "finished": iso_utc(utc_now())})
        _LOCK.release()


def ensure_update(force=False):
    if force or _age_minutes("last_update") > config.UPDATE_INTERVAL_MIN:
        if not STATE["running"]:
            threading.Thread(target=update_cycle, args=(force, True), daemon=True).start()
            return True
    return False


def poller_loop():
    """Interroga le centraline di continuo finche' l'app e' aperta.

    Torbole ha una finestra scorrevole di 168 ore, quindi basta aprire l'app
    una volta a settimana per non perdere nulla. Malcesine espone solo
    l'istante corrente: li' ogni passaggio del poller e' un dato che
    altrimenti sarebbe perso per sempre.
    """
    while True:
        try:
            update_stations()
        except Exception as e:                               # pragma: no cover
            _note("warn", "poller", str(e)[:120])
        time.sleep(config.POLL_INTERVAL_MIN * 60)


# ==========================================================================
# Lettura in tempo reale e profilo di giornata
# ==========================================================================

def live_reading(station):
    """Ultimo campione disponibile dalla centralina.

    E' il numero che chi va in acqua guarda per primo: non una previsione,
    ma quanto sta tirando adesso. Viaggia con la sua eta', perche' un dato
    di quaranta minuti fa non e' "adesso".
    """
    row = store.connect().execute(
        "SELECT ts, wind_kn, gust_kn, dir_deg FROM obs_sample "
        "WHERE station=? ORDER BY ts DESC LIMIT 1", (station,)).fetchone()
    if not row:
        return None
    dt = parse_dt_any(row["ts"])
    age = (utc_now() - dt).total_seconds() / 60.0 if dt else None
    # Molte stazioni pubblicano la raffica come massimo GIORNALIERO: se il
    # campione non ne ha una propria si preferisce non inventarla.
    return {
        "wind": row["wind_kn"], "gust": row["gust_kn"], "dir": row["dir_deg"],
        "ts": row["ts"], "age_min": age, "stale": (age is None or age > 45),
    }


def day_profile(place, day, sessions):
    """Andamento orario dell'intera giornata per un luogo, gia' corretto.

    Il modello lavora sulla giornata, non sull'ora: qui la forma oraria viene
    dall'ensemble e l'ampiezza dalla previsione. Fra una sessione e l'altra il
    fattore di correzione si interpola, cosi' la curva resta continua invece
    di spezzarsi a meta' mattina.
    """
    spot_names = [s for s in config.SPOT_ORDER
                  if config.SPOTS[s]["place"] == place
                  and config.SPOTS[s]["target"] == "hourly"]
    if not spot_names:
        return []
    hours, spread, _n, _o = ensemble_hours(spot_names[0])
    if not hours:
        return []

    keys = [k for k in F.window_hours(day, 3, 21) if k in hours]
    if not keys:
        return []

    # Per ciascuna sessione due correzioni: di quanto il modello alza o abbassa
    # il vento grezzo (fattore), e di quanto sposta l'ora del massimo (shift).
    anchors = []
    for name in spot_names:
        data = sessions.get(name)
        if not data:
            continue
        h0, h1 = config.SPOTS[name]["window"]
        win = [(local_hour(parse_dt_any(k)), hours[k].get("w10"))
               for k in F.window_hours(day, h0, h1) if k in hours]
        win = [(h, v) for h, v in win if v is not None]
        if not win:
            continue
        raw_hour, raw_peak = max(win, key=lambda hv: hv[1])
        if raw_peak <= 0.5:
            continue
        shift = 0.0
        if data.get("peak_hour") is not None:
            shift = clamp(data["peak_hour"] - raw_hour, -4.0, 4.0)
        anchors.append(((h0 + h1) / 2.0,
                        clamp(data["speed"] / raw_peak, 0.35, 3.0), shift))
    if not anchors:
        anchors = [(12.0, 1.0, 0.0)]

    by_hour = {}
    for k in keys:
        h = local_hour(parse_dt_any(k))
        if hours[k].get("w10") is not None:
            by_hour[h] = k

    def sample(h):
        """Vento grezzo a un'ora anche frazionaria, per interpolazione."""
        lo_h = int(math.floor(h))
        hi_h = lo_h + 1
        a = by_hour.get(lo_h)
        b = by_hour.get(hi_h)
        if a is None and b is None:
            return None, None
        if a is None:
            return hours[b].get("w10"), hours[b]
        if b is None:
            return hours[a].get("w10"), hours[a]
        t = h - lo_h
        va, vb = hours[a].get("w10"), hours[b].get("w10")
        return va * (1 - t) + vb * t, hours[a]

    out = []
    for k in keys:
        dt = parse_dt_any(k)
        h = local_hour(dt)
        weights = [1.0 / (1.0 + abs(h - hc) ** 2) for hc, _f, _s in anchors]
        total = sum(weights) or 1.0
        factor = sum(wt * f for wt, (_hc, f, _s) in zip(weights, anchors)) / total
        shift = sum(wt * sh for wt, (_hc, _f, sh) in zip(weights, anchors)) / total

        # Si legge il vento grezzo all'ora SPOSTATA: se il modello dell'orario
        # dice che il picco arriva un'ora dopo, tutta la curva scorre con lui.
        w, src = sample(clamp(h - shift, min(by_hour), max(by_hour)))
        if w is None:
            continue
        wind = max(0.0, w * factor)
        g = (src or {}).get("g10")
        ratio = clamp(g / w, 1.0, 2.1) if (g and w > 0.5) else 1.35
        sp = spread.get(k)
        sp = 2.0 if sp is None else sp * factor
        out.append({
            "hour": h, "key": k, "wind": wind, "gust": wind * ratio,
            "lo": max(0.0, wind - sp), "hi": wind + sp,
            "dir": hours[k].get("d10"),
            # Aria e cielo viaggiano con il profilo invece di essere ripescati
            # da una seconda passata sull'ensemble: sono gia' qui, e una
            # chiamata in meno per luogo e per giorno si sente all'avvio.
            "t2m": hours[k].get("t2m"),
            "cloud": hours[k].get("cloud"),
            "precip": hours[k].get("precip"),
        })
    return out


def by_day(product=None):
    """Riorganizza la previsione PER GIORNO.

    E' il modo in cui si decide davvero: prima si sceglie il giorno, poi si
    guarda dove e a che ora. La struttura precedente, un blocco per luogo con
    i giorni nascosti dentro, costringeva a confrontare due schede diverse
    per rispondere a "domani dove vado".
    """
    product = product or full_product()
    days = {}
    for spot_name, entries in product.items():
        for e in entries:
            days.setdefault(e["day"], {})[spot_name] = e
    out = []
    for day in sorted(days):
        sessions = days[day]
        lead = min(e["lead"] for e in sessions.values())
        places = {}
        for place in config.PLACES:
            places[place] = {"profile": day_profile(place, day, sessions),
                             "live": live_reading(
                                 next(config.SPOTS[s]["station"]
                                      for s in config.SPOTS
                                      if config.SPOTS[s]["place"] == place))}
        out.append({"day": day, "lead": lead, "sessions": sessions, "places": places})
    return out


# Taglie indicative di wing per un rider intorno agli 80 kg su foil.
# Sono un punto di partenza, non un consiglio: dipendono da tavola, ala,
# livello e da quanto e' rafficato.
WING_SIZES = (
    (27, "3.0 m o meno"),
    (23, "3.0-3.5 m"),
    (19, "3.5-4.0 m"),
    (16, "4.0-4.5 m"),
    (13, "4.5-5.0 m"),
    (10, "5.5-6.5 m"),
)


def wing_hint(speed):
    for threshold, label in WING_SIZES:
        if speed >= threshold:
            return label
    return None
