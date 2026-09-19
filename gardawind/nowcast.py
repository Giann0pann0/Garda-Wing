"""Validazione e infrastruttura del nowcasting intraday.

Questo modulo NON modifica la previsione produttiva. Misura una sola ipotesi:
se il vento osservato e' sopra/sotto la previsione all'ultima ora disponibile,
quanto di quello scarto persiste nelle ore successive?

Due livelli restano separati:
  1. banco storico su lead1, per sapere se la persistenza esiste davvero;
  2. archivio prospettico della curva realmente mostrata all'utente, necessario
     prima di autorizzare una correzione della UI produttiva.
"""

import math
import random
from collections import defaultdict

from . import config, store
from .util import angle_diff, local_day, local_hour, parse_dt_any

LOOKBACK_HOURS = 1
ALPHA_GRID = (0.0, 0.25, 0.50, 0.75, 1.00, 1.25)
MIN_TRAIN_TARGETS = 500
MIN_TEST_TARGETS = 500
MIN_GAIN_MAE_KN = 0.50
MIN_GAIN_RMSE_KN = 0.50
BOOTSTRAP_N = 2000

PROD_MIN_DAYS = 30
PROD_MIN_TARGETS = 300

# Le finestre vengono da config, non riscritte qui. C'era "(6, 10)" per il
# Peler: non e' la finestra del regime (4, 10) ne' quella utile calcolata
# giorno per giorno - era un TERZO orario, e le ore 04-05, dove d'inverno il
# Peler e' piu' forte, non entravano nel banco su cui si decide se accendere
# la correzione intraday del prodotto.
REGIMES = {nome: {"hours": config.SPOTS[nome]["window"]}
           for nome in ("Torbole-Peler", "Torbole-Ora")}

REASON_OK = "ok"
REASON_NO_HISTORY = "no_history"
REASON_TOO_FEW_TRAIN = "too_few_train"
REASON_TOO_FEW_TEST = "too_few_test"
REASON_GAIN_TOO_SMALL = "gain_too_small"
REASON_GAIN_UNCERTAIN = "gain_uncertain"
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
    """Ore comuni lead1/T0193, senza inferire campioni mancanti."""
    spec = REGIMES[spot_name]
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"], "lead1")
    fc = store.archive_rows(point, "2024-01-01T00:00:00Z", "2100-01-01T00:00:00Z")
    by_valid = {r["valid"]: r for r in fc if r.get("w10") is not None}
    if not by_valid:
        return []
    q = ("SELECT hour,wind_mean,dir_deg FROM obs_hour WHERE station=? "
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
        day = local_day(dt)
        out.append({"valid": o["hour"], "day": day, "month": int(day[5:7]),
                    "year": int(day[:4]), "hour": h,
                    "fc": float(f["w10"]), "obs": float(o["wind_mean"]),
                    "dir": None if o["dir_deg"] is None else float(o["dir_deg"])})
    return out


def _fit_static_bias(rows):
    """Bias obs-fc stimato SOLO sul training, per mese/ora con fallback."""
    by_mh = defaultdict(list)
    by_h = defaultdict(list)
    allv = []
    for r in rows:
        d = float(r["obs"] - r["fc"])
        by_mh[(r["month"], r["hour"])].append(d)
        by_h[r["hour"]].append(d)
        allv.append(d)
    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
    return {
        "mh": {k: mean(v) for k, v in by_mh.items()},
        "h": {k: mean(v) for k, v in by_h.items()},
        "global": mean(allv),
    }


def _static_bias_for(r, model):
    if not model:
        return 0.0
    return model["mh"].get((r["month"], r["hour"]),
                           model["h"].get(r["hour"], model["global"]))


def make_targets(rows, alpha, lookback_hours=LOOKBACK_HOURS, bias_model=None):
    """Bersagli causali: nessuna interpolazione, nessuna informazione futura.

    Oltre alla correzione candidata conserva tre riferimenti onesti:
    - base: forecast lead1 grezzo;
    - persistence: osservazione dell'ora precedente;
    - static_bias: forecast + bias mese/ora stimato solo sul training.
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
            static_bias = max(0.0, cur["fc"] + _static_bias_for(cur, bias_model))
            out.append({"day": day, "year": cur["year"], "month": cur.get("month", int(day[5:7])),
                        "hour": h, "base": cur["fc"],
                        "persistence": prev["obs"], "static_bias": static_bias,
                        "corrected": corrected, "obs": cur["obs"],
                        "delta_prev": delta, "dir": cur.get("dir")})
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


def _regime_days(rows, spot_name):
    """Giornate con almeno due ore consecutive coerenti col regime osservato.

    E' una classificazione ORARIA esplicita per il banco nowcast, non sostituisce
    la logica temporale piu' fine di orari.giudica_giornata.
    """
    spot = config.SPOTS[spot_name]
    good = defaultdict(set)
    for r in rows:
        if r["obs"] < spot["min_kn"] or r.get("dir") is None:
            continue
        # L'asse della CENTRALINA: qui si giudica una direzione MISURATA, e
        # config e' esplicito - "il bersaglio si giudica nel sistema della
        # centralina". Per il Peler di Torbole sono 54 gradi contro i 24
        # dell'asse geometrico: trenta gradi, dichiarati "non rumore". Col
        # riferimento sbagliato il settore accettato si sposta di trenta gradi,
        # e le ore di Peler vero finivano fra quelle "senza regime" mentre un
        # nordico sinottico ci entrava.
        if angle_diff(r["dir"], spot.get("axis_obs", spot["axis"])) \
                <= config.REGIME_SECTOR_DEG:
            good[r["day"]].add(r["hour"])
    out = set()
    for day, hs in good.items():
        if any((h + 1) in hs for h in hs):
            out.add(day)
    return out


def _paired_gain_ci(targets, challenger, baseline, n_boot=BOOTSTRAP_N, seed=12345):
    """Bootstrap appaiato per GIORNO: CI95 del guadagno MAE baseline-candidato."""
    by_day = defaultdict(list)
    for r in targets:
        gain = abs(r[baseline] - r["obs"]) - abs(r[challenger] - r["obs"])
        by_day[r["day"]].append(gain)
    days = sorted(by_day)
    if not days:
        return (None, None)
    rng = random.Random(seed)
    vals = []
    for _ in range(int(n_boot)):
        picked = [rng.choice(days) for _ in days]
        flat = [x for d in picked for x in by_day[d]]
        vals.append(sum(flat) / len(flat))
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return (lo, hi)


def _metrics(targets, field):
    return {"mae": _mae(targets, field), "rmse": _rmse(targets, field)}


def forward_year_validation(spot_name):
    """Forward chaining annuale con riferimenti e incertezza pre-registrati."""
    rows = _rows_for_regime(spot_name)
    years = sorted({r["year"] for r in rows})
    folds = []
    for test_year in years:
        train = [r for r in rows if r["year"] < test_year]
        test = [r for r in rows if r["year"] == test_year]
        chosen = choose_alpha(train)
        if not chosen:
            continue
        bias_model = _fit_static_bias(train)
        targets = make_targets(test, chosen["alpha"], bias_model=bias_model)
        if len(targets) < MIN_TEST_TARGETS:
            continue
        metrics = {k: _metrics(targets, k)
                   for k in ("base", "persistence", "static_bias", "corrected")}
        baselines = ("base", "persistence", "static_bias")
        best = min(baselines, key=lambda k: metrics[k]["mae"])
        gain_mae = metrics[best]["mae"] - metrics["corrected"]["mae"]
        gain_rmse = metrics[best]["rmse"] - metrics["corrected"]["rmse"]
        ci_lo, ci_hi = _paired_gain_ci(targets, "corrected", best)

        regime_days = _regime_days(test, spot_name)
        t_reg = [r for r in targets if r["day"] in regime_days]
        t_no = [r for r in targets if r["day"] not in regime_days]
        split = {}
        for label, subset in (("regime", t_reg), ("no_regime", t_no)):
            split[label] = {"n": len(subset),
                            "mae_nowcast": _mae(subset, "corrected"),
                            "mae_persistence": _mae(subset, "persistence"),
                            "mae_static_bias": _mae(subset, "static_bias")}

        folds.append({"year": test_year, "alpha": chosen["alpha"], "n": len(targets),
                      "metrics": metrics, "best_baseline": best,
                      "gain_mae": gain_mae, "gain_rmse": gain_rmse,
                      "gain_mae_ci95": (ci_lo, ci_hi), "split": split})

    if not folds:
        return {"spot": spot_name, "state": "closed", "reason": REASON_NO_HISTORY,
                "folds": []}
    if not all(f["n"] >= MIN_TEST_TARGETS for f in folds):
        reason = REASON_TOO_FEW_TEST
    elif not all(f["gain_mae"] >= MIN_GAIN_MAE_KN and
                 f["gain_rmse"] >= MIN_GAIN_RMSE_KN for f in folds):
        reason = REASON_GAIN_TOO_SMALL
    elif not all(f["gain_mae_ci95"][0] is not None and
                 f["gain_mae_ci95"][0] > 0.0 for f in folds):
        reason = REASON_GAIN_UNCERTAIN
    else:
        reason = REASON_OK
    return {"spot": spot_name, "state": "open" if reason == REASON_OK else "closed",
            "reason": reason, "folds": folds}


def production_coverage(place="Torbole"):
    """Conta SOLO curve emesse gia' verificabili contro un osservato reale."""
    c = store.connect()
    stations = sorted({v["station"] for v in config.SPOTS.values()
                       if v.get("place") == place and v.get("station")})
    if not stations:
        return {"n": 0, "days": 0, "from": None, "to": None,
                "state": "closed", "reason": REASON_PRODUCTION_HISTORY_SHORT}
    station = stations[0]
    try:
        r = c.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT substr(i.valid_hour,1,10)) giorni, "
            "MIN(i.issued_at) a, MAX(i.issued_at) b "
            "FROM issued_profile i JOIN obs_hour o ON o.hour=i.valid_hour "
            "AND o.station=? AND o.wind_mean IS NOT NULL WHERE i.place=?",
            (station, place)).fetchone()
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
           "BOOTSTRAP_N", "PROD_MIN_DAYS", "PROD_MIN_TARGETS", "REGIMES",
           "make_targets", "choose_alpha", "forward_year_validation",
           "production_coverage", "validation_report",
           "REASON_GAIN_UNCERTAIN"]
