"""Aggregazione dei campioni grezzi in valori orari.

E' un passaggio separato e ricostruibile: i campioni a 10 minuti restano in
archivio, e l'aggregato puo' essere ricalcolato in qualsiasi momento se
cambiamo idea su come farlo. La versione precedente di questo progetto teneva
invece "l'ultimo campione capitato dentro l'ora", che e' un sottocampionamento
casuale e inietta rumore direttamente nel bersaglio dell'addestramento.
"""

import datetime as _dt

from . import store
from .util import (FINESTRA_RICORRENTE_MIN, iso_hour_utc, merge_by_instant,
                   parse_dt_any, recurrent_gust, sampling_cadence,
                   vector_mean_direction, window_estimable)

# Un'ora con troppi pochi campioni non e' una media: la teniamo, ma il numero
# di campioni viaggia con il dato cosi' che il modello possa scartarla.
MIN_SAMPLES_FULL = 4

# La finestra della raffica ricorrente sta in util, una volta sola: trenta
# minuti. Su campioni a dieci minuti e' la mediana di tre valori - un colpo
# isolato viene scartato, un livello che si ripete resta. Dove la cadenza non
# lo permette, gust_rec resta NULL: e' "non stimabile", non zero.


def aggregate_station(station, since_iso=None):
    """Ricalcola obs_hour per una stazione. Ritorna il numero di ore scritte."""
    samples = store.samples_since(station, since_iso or "0000")
    if not samples:
        return 0

    # La chiave dei campioni e' (stazione, istante, FONTE): lo stesso istante
    # puo' arrivare due volte, dall'archivio storico e dal canale realtime, e
    # sulle giornate recenti succede davvero. Senza unirli, n_samples
    # raddoppia - ed e' il numero con cui il modello decide se un'ora e' una
    # media o rumore - e wind_mean diventa la media fra due fonti invece della
    # misura di un istante. Si uniscono per istante, campo per campo, tenendo
    # il valore presente.
    pronti = []
    for s in samples:
        dt = parse_dt_any(s["ts"])
        if dt is None:
            continue
        r = dict(s)
        r["_key"] = dt.timestamp()
        pronti.append(r)
    per_istante, conflitti = merge_by_instant(pronti)

    # I disaccordi fra due fonti sullo stesso istante non si nascondono: vanno
    # nel registro, dove la diagnostica li mostra. La regola di scelta e'
    # dichiarata in util (vince l'archivio validato sul realtime), ma "ho
    # scelto" e "erano d'accordo" sono due cose diverse.
    if conflitti:
        peggiore = max(conflitti, key=lambda c: c["differenza"])
        store.log_event(
            "warn", "qc/%s" % station,
            "%d conflitti fra fonti sullo stesso istante; il maggiore: %s "
            "%.1f (%s) contro %.1f (%s)"
            % (len(conflitti), peggiore["campo"], peggiore["tenuto"],
               peggiore["fonte_tenuta"], peggiore["scartato"],
               peggiore["fonte_scartata"]))

    buckets = {}
    serie = []
    for ts_sec in sorted(per_istante):
        u = per_istante[ts_sec]
        dt = _dt.datetime.fromtimestamp(ts_sec, _dt.timezone.utc)
        hour = iso_hour_utc(dt)
        buckets.setdefault(hour, []).append(
            {"wind_kn": u["wind"], "gust_kn": u["gust"], "dir_deg": u["dir"]})
        if u["gust"] is not None:
            serie.append((ts_sec / 60.0, u["gust"], hour))

    # La raffica ricorrente si calcola sulla serie CONTINUA e solo dopo si
    # taglia per ora. Calcolarla dentro il secchio orario userebbe una finestra
    # che si accorcia ai bordi dell'ora, e produrrebbe un salto artificiale
    # ogni sessanta minuti in una grandezza che non sa niente delle ore.
    ric_per_ora = {}
    if serie:
        serie.sort()
        cadenza = sampling_cadence([t for t, _v, _h in serie])
        if not window_estimable(cadenza, FINESTRA_RICORRENTE_MIN):
            # Cadenza troppo rada per una mediana su mezz'ora. Non si allarga
            # la finestra tenendo il nome: si lascia NULL e chi legge sa che
            # per questa centralina la grandezza non e' stimabile.
            valori = []
            serie = []
        else:
            valori = recurrent_gust([(t, v) for t, v, _h in serie],
                                    centered=True, cadence_min=cadenza)
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
        # Solo le coppie complete: dopo l'unione per istante puo' esistere un
        # campione con la raffica e senza vento, e pesare una direzione con un
        # vento assente non vuol dire niente.
        direction, constancy = vector_mean_direction(
            [(g["wind_kn"], g["dir_deg"]) for g in group
             if g["wind_kn"] is not None and g["dir_deg"] is not None])
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
