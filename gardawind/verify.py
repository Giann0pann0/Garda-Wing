"""Verifica dei singoli modelli CONTRO LE OSSERVAZIONI di centralina.

Punto non negoziabile: la "verita'" e' la centralina. Misurare quanto un
modello assomiglia a un altro modello (o a un archivio di previsioni) non dice
nulla sull'accuratezza, e sull'alto Garda e' particolarmente ingannevole
perche' tutti i modelli sbagliano nella stessa direzione: la cella di griglia
cade sul versante, non sul lago, e la brezza non e' risolta.

La verifica e' GIORNALIERA e sulla finestra del regime: il confronto ora per
ora premierebbe i modelli che azzeccano la fase, non l'intensita', ed e' la
fase la cosa che tutti sbagliano di piu'.
"""

import math

from . import config, store
from .util import iso_hour_utc, local_day, local_hour, mean, median, parse_dt_any

# Peso a priori, usato finche' non ci sono abbastanza osservazioni verificate.
# La risoluzione conta molto su un lago largo due chilometri dentro una valle
# profonda: un modello a 2 km vede il solco, uno a 25 km vede una montagna.
PRIOR_QUALITY_BONUS = {"ECMWF IFS": 1.30, "ECMWF AIFS": 1.10, "ICON-2I": 1.10,
                       "ICON-D2": 1.10}

MIN_DAYS_FOR_SKILL = 25
SHRINK_PSEUDO_DAYS = 25


def prior_weights():
    raw = {}
    for name, m in config.MODELS.items():
        w = (1.0 / m["res_km"]) ** 0.35
        raw[name] = w * PRIOR_QUALITY_BONUS.get(name, 1.0)
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def observed_daily_peaks(spot_name):
    """Picco della media oraria nella finestra, per giorno locale."""
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    need = max(3, int(config.MIN_WINDOW_COVERAGE * (h1 - h0 + 1)))
    by_day = {}
    for row in store.obs_hours(spot["station"]):
        dt = parse_dt_any(row["hour"])
        if dt is None or row["wind_mean"] is None:
            continue
        if not (h0 <= local_hour(dt) <= h1):
            continue
        by_day.setdefault(local_day(dt), []).append(row["wind_mean"])
    return {d: max(v) for d, v in by_day.items() if len(v) >= need}


def _forecast_daily_peaks(rows, spot_name):
    """Stessa riduzione applicata alla previsione, cosi' si confrontano pari."""
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    by_day = {}
    for valid, values in rows:
        dt = parse_dt_any(valid)
        if dt is None:
            continue
        w = values.get("w10")
        if w is None or not (h0 <= local_hour(dt) <= h1):
            continue
        by_day.setdefault(local_day(dt), []).append(w)
    return {d: max(v) for d, v in by_day.items() if len(v) >= 3}


def verify_model(spot_name, model_name, lead, fetch_prev, start_day, end_day, observed):
    """Confronta un modello a una scadenza con le osservazioni. Ritorna stats o None."""
    spot = config.SPOTS[spot_name]
    model_id = config.MODELS[model_name]["id"]
    rows = fetch_prev(spot["lat"], spot["lon"], model_id, lead, start_day, end_day)
    fc = _forecast_daily_peaks(rows, spot_name)

    pairs = [(fc[d], observed[d]) for d in fc if d in observed]
    if len(pairs) < MIN_DAYS_FOR_SKILL:
        return None

    errs = [f - o for f, o in pairs]
    fs = [f for f, _ in pairs]
    os_ = [o for _, o in pairs]
    fm, om = mean(fs), mean(os_)
    cov = sum((f - fm) * (o - om) for f, o in pairs)
    varf = sum((f - fm) ** 2 for f in fs)
    slope = (cov / varf) if varf > 1e-9 else 1.0

    return {
        "n": len(pairs),
        "mae": mean([abs(e) for e in errs]),
        "bias": mean(errs),
        "rmse": math.sqrt(mean([e * e for e in errs])),
        "slope": slope,
    }


def compute_weights(spot_name, lead):
    """Pesi d'ensemble: dalla skill verificata, con ritiro verso il prior.

    Il ritiro evita che pochi giorni fortunati facciano dominare un modello.
    """
    priors = prior_weights()
    skills = store.skills(spot_name)
    entries = {}
    for name in config.MODELS:
        s = skills.get((name, lead))
        entries[name] = s if (s and s.get("n") and s["n"] >= MIN_DAYS_FOR_SKILL) else None

    measured = [e for e in entries.values() if e]
    if not measured:
        return priors, "prior"

    med_mae = median([e["mae"] for e in measured]) or 3.0
    raw = {}
    for name, e in entries.items():
        if e is None:
            raw[name] = priors[name] * 0.5          # non verificato: meta' peso
            continue
        n = e["n"]
        eff = (n * e["mae"] + SHRINK_PSEUDO_DAYS * med_mae) / (n + SHRINK_PSEUDO_DAYS)
        raw[name] = priors[name] ** 0.4 * (1.0 / max(0.8, eff) ** 2)
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}, "verificato"


def model_bias(spot_name, model_name, lead):
    s = store.skills(spot_name).get((model_name, lead))
    if s and s.get("n") and s["n"] >= MIN_DAYS_FOR_SKILL and s.get("bias") is not None:
        return s["bias"]
    return 0.0
