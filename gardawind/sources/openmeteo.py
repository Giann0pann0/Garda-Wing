"""Open-Meteo: previsione corrente, archivio storico delle previsioni, run precedenti.

Tre endpoint diversi con capacita' diverse, verificate una per una:

  forecast                 tutti i modelli, superficie + livelli isobarici
  historical-forecast      best_match con archivio profondo E livelli isobarici
                           -> e' la sorgente dei predittori di addestramento
  previous-runs            SOLO superficie, per modello, per lead 1-4
                           -> serve a misurare la skill di ciascun modello

Tutte le richieste usano timezone=UTC: l'ora locale e' un problema di
presentazione, non di archiviazione, e mescolare i due e' la via piu' rapida
per sbagliare di un'ora a ogni cambio di ora legale.
"""

from .. import config
from ..store import OM_TO_COL
from ..util import iso_hour_utc, num, parse_dt_any
from .http import FetchError, fetch_json


def _hourly_rows(payload, strip_suffix=None):
    """Da payload Open-Meteo a [(valid_utc, {colonna: valore})]."""
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    out = []
    for i, t in enumerate(times):
        dt = parse_dt_any(t)
        if dt is None:
            continue
        values = {}
        for key, series in h.items():
            if key == "time" or not isinstance(series, list):
                continue
            name = key
            if strip_suffix and name.endswith(strip_suffix):
                name = name[: -len(strip_suffix)]
            col = OM_TO_COL.get(name)
            if col is None:
                continue
            values[col] = num(series[i]) if i < len(series) else None
        out.append((iso_hour_utc(dt), values))
    return out


def _base_params(lat, lon):
    return {
        "latitude": lat,
        "longitude": lon,
        "timezone": "UTC",
        "wind_speed_unit": "kn",
        "cell_selection": "land",
    }


def fetch_forecast(lat, lon, model_id, with_levels, days=None):
    """Previsione corrente di un singolo modello. Ritorna (righe, elevazione)."""
    variables = list(config.SURFACE_VARS)
    if with_levels:
        variables += config.LEVEL_VARS
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(variables)
    params["forecast_days"] = days or config.FORECAST_DAYS
    if model_id and model_id != "best_match":
        params["models"] = model_id
    data = fetch_json(config.URL_FORECAST, params, timeout=60)
    return _hourly_rows(data), data.get("elevation")


def fetch_archive(lat, lon, start_day, end_day):
    """Archivio delle previsioni a breve scadenza (best_match, livelli inclusi).

    E' il set di predittori con cui il modello impara: e' un'analisi di
    previsione, non una rianalisi, quindi allenarci sopra e' coerente con il
    modo in cui poi verra' usato.
    """
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(config.SURFACE_VARS + config.LEVEL_VARS)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = config.ARCHIVE_MODEL
    data = fetch_json(config.URL_ARCHIVE_FC, params, timeout=180)
    return _hourly_rows(data)


def fetch_era5(lat, lon, start_day, end_day):
    """Rianalisi ERA5: SOLO variabili di superficie, ma decenni di profondita'.

    E' lo stato atmosferico ricostruito a posteriori, non una previsione.
    Addestrarci sopra e' la tecnica classica del "perfect prog": si impara il
    legame fra stato sinottico VERO e vento locale, e poi lo si applica a uno
    stato PREVISTO. Il guadagno e' la profondita' storica; il prezzo e' che in
    addestramento gli ingressi sono piu' puliti di quelli che avra' in
    esercizio. Per questo il confronto con il modello addestrato sulle
    previsioni va fatto dando a entrambi gli stessi ingressi previsti
    (vedi model.cross_source_eval), non sui rispettivi dati di addestramento.
    """
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(config.SURFACE_VARS)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = config.ERA5_MODEL
    data = fetch_json(config.URL_ARCHIVE_ERA5, params, timeout=180)
    return _hourly_rows(data)


def fetch_era5_context(lat, lon, start_day, end_day):
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(config.CONTEXT_VARS)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = config.ERA5_MODEL
    data = fetch_json(config.URL_ARCHIVE_ERA5, params, timeout=180)
    return _hourly_rows(data)


def fetch_archive_context(lat, lon, start_day, end_day):
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(config.CONTEXT_VARS)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = config.ARCHIVE_MODEL
    data = fetch_json(config.URL_ARCHIVE_FC, params, timeout=180)
    return _hourly_rows(data)


def fetch_context(lat, lon, days=None):
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(config.CONTEXT_VARS)
    params["forecast_days"] = days or config.FORECAST_DAYS
    data = fetch_json(config.URL_FORECAST, params, timeout=60)
    return _hourly_rows(data)


def fetch_lead_features(lat, lon, lead, start_day, end_day, context=False):
    """Predittori COME ERANO all'emissione, `lead` giorni prima del bersaglio.

    E' l'unica sorgente che permette di addestrare e validare una previsione a
    D+3 usando cio' che era davvero disponibile a D+0. L'archivio delle
    previsioni (historical-forecast) contiene solo le prime ore di ogni run,
    cioe' una scadenza di poche ore: addestrarci sopra e poi applicarlo a D+3
    significa promettere un'accuratezza che a quella scadenza non c'e'.

    Solo variabili di superficie: i livelli isobarici non sono esposti qui.
    """
    suffix = "_previous_day%d" % lead
    base = config.PREV_RUN_CONTEXT_VARS if context else config.PREV_RUN_VARS
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(v + suffix for v in base)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = config.ARCHIVE_MODEL
    data = fetch_json(config.URL_PREV_RUNS, params, timeout=240)
    return _hourly_rows(data, strip_suffix=suffix)


def fetch_previous_run(lat, lon, model_id, lead, start_day, end_day):
    """Vento a 10 m come lo vedeva quel modello `lead` giorni prima.

    Solo variabili di superficie: i livelli isobarici NON sono esposti da
    questo endpoint (verificato: restituisce un errore di variabile non valida).
    """
    suffix = "_previous_day%d" % lead
    variables = [v + suffix for v in ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")]
    params = _base_params(lat, lon)
    params["hourly"] = ",".join(variables)
    params["start_date"] = start_day
    params["end_date"] = end_day
    params["models"] = model_id
    data = fetch_json(config.URL_PREV_RUNS, params, timeout=180)
    return _hourly_rows(data, strip_suffix=suffix)


__all__ = ["fetch_forecast", "fetch_archive", "fetch_archive_context",
           "fetch_era5", "fetch_era5_context", "fetch_lead_features",
           "fetch_context", "fetch_previous_run", "FetchError"]
