"""Aggregazione dei campioni grezzi in valori orari.

E' un passaggio separato e ricostruibile: i campioni a 10 minuti restano in
archivio, e l'aggregato puo' essere ricalcolato in qualsiasi momento se
cambiamo idea su come farlo. La versione precedente di questo progetto teneva
invece "l'ultimo campione capitato dentro l'ora", che e' un sottocampionamento
casuale e inietta rumore direttamente nel bersaglio dell'addestramento.
"""

from . import store
from .util import (iso_hour_utc, parse_dt_any, recurrent_gust,
                   vector_mean_direction)

# Un'ora con troppi pochi campioni non e' una media: la teniamo, ma il numero
# di campioni viaggia con il dato cosi' che il modello possa scartarla.
MIN_SAMPLES_FULL = 4

# La finestra della raffica ricorrente. Trenta minuti su campioni a dieci
# minuti vuol dire mediana di tre valori: un colpo isolato viene scartato, un
# livello che si ripete resta.
FINESTRA_RIC_MIN = 30.0


def aggregate_station(station, since_iso=None):
    """Ricalcola obs_hour per una stazione. Ritorna il numero di ore scritte."""
    samples = store.samples_since(station, since_iso or "0000")
    if not samples:
        return 0

    buckets = {}
    serie = []
    for s in samples:
        dt = parse_dt_any(s["ts"])
        if dt is None:
            continue
        buckets.setdefault(iso_hour_utc(dt), []).append(s)
        if s["gust_kn"] is not None:
            serie.append((dt.timestamp() / 60.0, s["gust_kn"], iso_hour_utc(dt)))

    # La raffica ricorrente si calcola sulla serie CONTINUA e solo dopo si
    # taglia per ora. Calcolarla dentro il secchio orario userebbe una finestra
    # che si accorcia ai bordi dell'ora, e produrrebbe un salto artificiale
    # ogni sessanta minuti in una grandezza che non sa niente delle ore.
    ric_per_ora = {}
    if serie:
        serie.sort()
        valori = recurrent_gust([(t, v) for t, v, _h in serie],
                                window_min=FINESTRA_RIC_MIN, centered=True)
        for (_t, v), (_t2, _v2, hour) in zip(valori, serie):
            if v is not None:
                prev = ric_per_ora.get(hour)
                if prev is None or v > prev:
                    ric_per_ora[hour] = v

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
            # Dentro l'ora si tiene il MASSIMO della ricorrente: e' "il miglior
            # livello che si e' sostenuto per mezz'ora in quell'ora", che e' la
            # domanda del wing. La mediana della ricorrente sarebbe una mediana
            # di mediane, e non risponderebbe a niente in particolare.
            "gust_rec": ric_per_ora.get(hour),
            "dir_deg": direction,
            "dir_const": constancy,
            "n_samples": len(winds),
        })
    if rows:
        store.upsert_obs_hours(station, rows)
    return len(rows)
