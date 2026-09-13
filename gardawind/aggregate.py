"""Aggregazione dei campioni grezzi in valori orari.

E' un passaggio separato e ricostruibile: i campioni a 10 minuti restano in
archivio, e l'aggregato puo' essere ricalcolato in qualsiasi momento se
cambiamo idea su come farlo. La versione precedente di questo progetto teneva
invece "l'ultimo campione capitato dentro l'ora", che e' un sottocampionamento
casuale e inietta rumore direttamente nel bersaglio dell'addestramento.
"""

from . import store
from .util import iso_hour_utc, parse_dt_any, vector_mean_direction

# Un'ora con troppi pochi campioni non e' una media: la teniamo, ma il numero
# di campioni viaggia con il dato cosi' che il modello possa scartarla.
MIN_SAMPLES_FULL = 4


def aggregate_station(station, since_iso=None):
    """Ricalcola obs_hour per una stazione. Ritorna il numero di ore scritte."""
    samples = store.samples_since(station, since_iso or "0000")
    if not samples:
        return 0

    buckets = {}
    for s in samples:
        dt = parse_dt_any(s["ts"])
        if dt is None:
            continue
        buckets.setdefault(iso_hour_utc(dt), []).append(s)

    rows = []
    for hour, group in buckets.items():
        winds = [g["wind_kn"] for g in group if g["wind_kn"] is not None]
        if not winds:
            continue
        gusts = [g["gust_kn"] for g in group if g["gust_kn"] is not None]
        direction, constancy = vector_mean_direction(
            [(g["wind_kn"], g["dir_deg"]) for g in group])
        rows.append({
            "hour": hour,
            "wind_mean": sum(winds) / len(winds),
            "wind_max": max(winds),
            "gust_max": max(gusts) if gusts else None,
            "dir_deg": direction,
            "dir_const": constancy,
            "n_samples": len(winds),
        })
    if rows:
        store.upsert_obs_hours(station, rows)
    return len(rows)
