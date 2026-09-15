"""Validazione e infrastruttura del nowcasting intraday.

Questo modulo NON modifica la previsione produttiva. Misura una sola ipotesi:
se il vento osservato e' sopra/sotto la previsione all'ultima ora disponibile,
quanto di quello scarto persiste nelle ore successive?

Due livelli restano separati:
  1. banco storico su lead1, per sapere se la persistenza esiste davvero;
  2. archivio prospettico della curva realmente mostrata all'utente, necessario
     prima di autorizzare una correzione della UI produttiva.
"""

import datetime as _dt
import math
from collections import defaultdict

from . import config, store
from .util import local_day, local_hour, parse_dt_any

# Contratto esplicito: niente costanti di cadenza nascoste.
# obs_hour e arch_hour sono entrambe tabelle ORARIE per definizione dello schema.
LOOKBACK_HOURS = 1
ALPHA_GRID = (0.0, 0.25, 0.50, 0.75, 1.00, 1.25)
MIN_TRAIN_TARGETS = 500
MIN_TEST_TARGETS = 500
MIN_GAIN_MAE_KN = 0.50
MIN_GAIN_RMSE_KN = 0.50

# Prima di correggere la curva realmente mostrata servono dati raccolti con
# quella stessa curva. Il banco lead1 apre solo il gate concettuale.
PROD_MIN_DAYS = 30
PROD_MIN_TARGETS = 300

REGIMES = {
    "Torbole-Peler": {"hours": (6, 10)},   # finestra pratica, non onset meteorologico
    "Torbole-Ora": {"hours": (11, 19)},
}

REASON_OK = "ok"
REASON_NO_HISTORY = "no_history"
REASON_TOO_FEW_TRAIN = "too_few_train"
REASON_TOO_FEW_TEST = "too_few_test"
REASON_GAIN_TOO_SMALL = "gain_too_small"
REASON_PRODUCTION_HISTORY_SHORT = "production_history_short"


def _mae(pairs, pred_index):
    if not pairs:
        return None
    return sum(abs(r[pred_index] - r["obs"]) for r in pairs) / len(pairs)


def _rmse(pairs, pred_index):
    if not pairs:
        return None
    return math.sqrt(sum((r[pred_index] - r["obs"]) ** 2 for r in pairs) / len(pairs))


def _rows_for_regime(spot_name):
    """Ritorna ore comuni lead1/T0193, senza inferire campioni mancanti."""
    spec = REGIMES[spot_name]
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"], "lead1")
    fc = store.archive_rows(point, "2024-01-01T00:00:00Z", "2100-01-01T00:00:00Z")
    by_valid = {r["valid"]: r for r in fc if r.get("w10") is not None}
    if not by_valid:
        return []
    q = ("SELECT hour,wind_mean FROM obs_hour WHERE station=? "
         "AND wind_mean IS NOT NULL ORDER BY hour")
    out = []
    h0, h1 = spec["hours"]
    for o in store.connect().execute(q, (spot["station"],)):
        f = by_valid.get(o["hour"])
        if not f:
            continue
        dt = parse_dt_any(o["hour"])
        h = local_hour(dt)
        if h < h0 or h > h1:
            continue
        out.append({"valid": o["hour"], "day": local_day(dt),
                    "year": int(local_day(dt)[:4]), "hour": h,
                    "fc": float(f["w10"]), "obs": float(o["wind_mean"])})
    return out


def make_targets(rows, alpha, lookback_hours=LOOKBACK_HOURS):
    """Applica solo informazione temporalmente precedente al bersaglio.

    La correzione all'ora h usa lo scarto osservato-previsione dell'ultima ora
    precedente presente nello stesso giorno e distante esattamente
    `lookback_hours`. Nessuna interpolazione, nessun uso di ore future.
    """
    by_day = defaultdict(dict)
    for r in rows:
        by_day[r["day"]][r["hour"]] = r
    out = []
    for day in sorted(by_day):
        hours = by_day[day]
        for h in sorted(hours):
            prev = hours.get(h - lookback_hours)
            cur = hours[h]
            if prev is None:
                continue
            delta = prev["obs"] - prev["fc"]
            corrected = max(0.0, cur["fc"] + float(alpha) * delta)
            out.append({"day": day, "year": cur["year"], "hour": h,
                        "base": cur["fc"], "corrected": corrected,
                        "obs": cur["obs"], "delta_prev": delta})
    return out


def choose_alpha(train_rows):
    """Sceglie alpha SOLO sul passato del blocco che verra' provato."""
    best = None
    for alpha in ALPHA_GRID:
        targets = make_targets(train_rows, alpha)
        if len(targets) < MIN_TRAIN_TARGETS:
            continue
        score = _mae(targets, "corrected")
        candidate = (score, abs(alpha), alpha)
        if best is None or candidate < best[0]:
            best = (candidate, alpha, len(targets))
    if best is None:
        return None
    return {"alpha": best[1], "n": best[2], "mae_train": best[0][0]}


def forward_year_validation(spot_name):
    """Forward chaining per anno: 2025 usa solo 2024, 2026 usa 2024-25."""
    rows = _rows_for_regime(spot_name)
    years = sorted({r["year"] for r in rows})
    folds = []
    for test_year in years:
        train = [r for r in rows if r["year"] < test_year]
        test = [r for r in rows if r["year"] == test_year]
        chosen = choose_alpha(train)
        if not chosen:
            continue
        targets = make_targets(test, chosen["alpha"])
        if len(targets) < MIN_TEST_TARGETS:
            continue
        base_mae = _mae(targets, "base")
        corr_mae = _mae(targets, "corrected")
        base_rmse = _rmse(targets, "base")
        corr_rmse = _rmse(targets, "corrected")
        folds.append({"year": test_year, "alpha": chosen["alpha"],
                      "n": len(targets), "mae_base": base_mae,
                      "mae_nowcast": corr_mae, "gain_mae": base_mae - corr_mae,
                      "rmse_base": base_rmse, "rmse_nowcast": corr_rmse,
                      "gain_rmse": base_rmse - corr_rmse})
    if not folds:
        return {"spot": spot_name, "state": "closed", "reason": REASON_NO_HISTORY,
                "folds": []}
    enough = all(f["n"] >= MIN_TEST_TARGETS for f in folds)
    gain_ok = all(f["gain_mae"] >= MIN_GAIN_MAE_KN and
                  f["gain_rmse"] >= MIN_GAIN_RMSE_KN for f in folds)
    if not enough:
        reason = REASON_TOO_FEW_TEST
    elif not gain_ok:
        reason = REASON_GAIN_TOO_SMALL
    else:
        reason = REASON_OK
    return {"spot": spot_name, "state": "open" if reason == REASON_OK else "closed",
            "reason": reason, "folds": folds}


def production_coverage(place="Torbole"):
    """Copertura della curva realmente emessa; nessuna promessa prima del dato."""
    c = store.connect()
    try:
        r = c.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT substr(valid_hour,1,10)) giorni, "
            "MIN(issued_at) a, MAX(issued_at) b FROM issued_profile WHERE place=?",
            (place,)).fetchone()
    except Exception:
        return {"n": 0, "days": 0, "from": None, "to": None,
                "state": "closed", "reason": REASON_PRODUCTION_HISTORY_SHORT}
    n, days = int(r["n"] or 0), int(r["giorni"] or 0)
    ok = n >= PROD_MIN_TARGETS and days >= PROD_MIN_DAYS
    return {"n": n, "days": days, "from": r["a"], "to": r["b"],
            "state": "open" if ok else "closed",
            "reason": REASON_OK if ok else REASON_PRODUCTION_HISTORY_SHORT}


def validation_report():
    return {"historical": {s: forward_year_validation(s) for s in REGIMES},
            "production": production_coverage("Torbole")}


__all__ = ["LOOKBACK_HOURS", "ALPHA_GRID", "MIN_TRAIN_TARGETS",
           "MIN_TEST_TARGETS", "MIN_GAIN_MAE_KN", "MIN_GAIN_RMSE_KN",
           "PROD_MIN_DAYS", "PROD_MIN_TARGETS", "REGIMES", "make_targets",
           "choose_alpha", "forward_year_validation", "production_coverage",
           "validation_report"]
