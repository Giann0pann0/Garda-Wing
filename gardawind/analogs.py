"""Forma intraday di Torbole da analoghi storici osservati.

Questo modulo modifica SOLO la forma temporale del profilo di giornata.
Il livello complessivo resta quello prodotto dal motore corrente.

Protocollo validato (da non cambiare senza nuova validazione):
- condizioni previste da best_match alla scadenza D+1/D+2/D+3;
- ciascuna sorgente standardizzata sulla propria distribuzione;
- archivio analoghi ERA5 + curve osservate T0193, training fino al 2023;
- k=3 vicini euclidei nello spazio standardizzato;
- mediana punto per punto delle curve normalizzate, griglia 10 minuti;
- nessun allineamento sull'ora d'ingresso.
"""

import datetime as _dt
import math
import statistics
import time

from . import store
from .util import (iso_utc, local_day, local_naive_to_utc, parse_dt_any,
                   to_local)

NORTH = (45.8701, 10.8774)
SOUTH = (45.7646, 10.8119)
STATION = "T0193"
TRAIN_START = "2012-07-05"
TRAIN_END = "2023-12-31"
EXPECTED_TRAIN_DAYS = 4020
EXPECTED_CONFIRM_DAYS = 617
K = 3
GRID_MIN = tuple(range(4 * 60, 21 * 60 + 1, 10))
MIN_COVERAGE = 0.90
MIN_PEAK = 6.0
MAX_INTERP_GAP_MIN = 30.0
CACHE_S = 12 * 60 * 60
CURRENT_SOURCE = "analog_live"
GATE_KEY = "analog_shape_gate_v1"
GATE_SIGNATURE = "torbole-analogs-k3-20260915"
# Numeri del blocco cieco 2025-2026 prodotto dal test che ha scelto il metodo.
# Non servono a ottimizzare nulla: sono una firma di regressione. Se questa
# implementazione non li riproduce entro tolleranze strette, NON modifica il
# prodotto pubblico.
BENCHMARK = {
    1: {"hits": .829, "false_alarms": .209, "minute_error": 79.0,
        "bias_minutes": -12.0, "steepness": 6.3},
    2: {"hits": .805, "false_alarms": .264, "minute_error": 93.0,
        "bias_minutes": -12.0, "steepness": 6.6},
    3: {"hits": .808, "false_alarms": .259, "minute_error": 93.0,
        "bias_minutes": -11.0, "steepness": 6.7},
}
FEATURES = (
    "rad_tot", "cloud", "tmax", "precip", "dp_lago",
    "wx", "wy", "wnotte", "sin", "cos",
)

_CACHE = {"at": 0.0, "library": None, "era_stats": None,
          "lead_stats": {}, "diagnostic": None}


def _mean(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def _stdev(values, mu=None):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(vals) < 2:
        return None
    mu = _mean(vals) if mu is None else float(mu)
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals))


def _season(day):
    d = _dt.date.fromisoformat(day)
    a = 2.0 * math.pi * d.timetuple().tm_yday / 365.25
    return math.sin(a), math.cos(a)


def _rows_by_day(rows):
    out = {}
    for r in rows:
        dt = parse_dt_any(r["valid"])
        if dt is not None:
            out.setdefault(local_day(dt), []).append(r)
    return out


def daily_conditions(day, north_rows, south_rows):
    """Le 10 variabili del protocollo, aggregate sul giorno locale."""
    nr = [r for r in north_rows if local_day(parse_dt_any(r["valid"])) == day]
    sr = [r for r in south_rows if local_day(parse_dt_any(r["valid"])) == day]
    if not nr or not sr:
        return None

    def hour(r):
        return to_local(parse_dt_any(r["valid"])).hour

    rad = [r.get("rad") for r in nr if r.get("rad") is not None]
    cloud = [r.get("cloud") for r in nr if 8 <= hour(r) <= 16 and r.get("cloud") is not None]
    t2m = [r.get("t2m") for r in nr if r.get("t2m") is not None]
    precip = [r.get("precip") for r in nr if r.get("precip") is not None]

    nmap = {r["valid"]: r for r in nr}
    smap = {r["valid"]: r for r in sr}
    dp = []
    for valid in sorted(set(nmap).intersection(smap)):
        h = to_local(parse_dt_any(valid)).hour
        a, b = nmap[valid].get("mslp"), smap[valid].get("mslp")
        if 9 <= h <= 17 and a is not None and b is not None:
            dp.append(float(a) - float(b))

    wx, wy, wn = [], [], []
    for r in nr:
        h = hour(r)
        if not (0 <= h <= 6) or r.get("w10") is None:
            continue
        w = float(r["w10"])
        wn.append(w)
        if r.get("d10") is not None:
            d = math.radians(float(r["d10"]))
            wx.append(w * math.cos(d))
            wy.append(w * math.sin(d))

    s, c = _season(day)
    v = {
        "rad_tot": sum(float(x) for x in rad) if rad else None,
        "cloud": _mean(cloud),
        "tmax": max(float(x) for x in t2m) if t2m else None,
        "precip": sum(float(x) for x in precip) if precip else None,
        "dp_lago": _mean(dp),
        "wx": _mean(wx), "wy": _mean(wy), "wnotte": _mean(wn),
        "sin": s, "cos": c,
    }
    return v if all(v[k] is not None for k in FEATURES) else None


def _stats(vectors):
    if not vectors:
        return None
    out = {}
    for k in FEATURES:
        vals = [v[k] for v in vectors if v.get(k) is not None]
        mu = _mean(vals)
        sd = _stdev(vals, mu)
        if mu is None or sd is None or sd < 1e-9:
            return None
        out[k] = (mu, sd)
    return out


def _z(v, stats):
    if not v or not stats:
        return None
    try:
        return tuple((float(v[k]) - stats[k][0]) / stats[k][1] for k in FEATURES)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _archive_daily(source, start_day, end_day):
    pn = store.point_key(NORTH[0], NORTH[1], source)
    ps = store.point_key(SOUTH[0], SOUTH[1], source)
    # Margine UTC per coprire interamente il giorno locale ai cambi DST.
    a = ( _dt.date.fromisoformat(start_day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    b = ( _dt.date.fromisoformat(end_day) + _dt.timedelta(days=1)).isoformat() + "T23:59:59Z"
    nd = _rows_by_day(store.archive_rows(pn, a, b))
    sd = _rows_by_day(store.archive_rows(ps, a, b))
    out = {}
    for day in sorted(set(nd).intersection(sd)):
        if day < start_day or day > end_day:
            continue
        v = daily_conditions(day, nd[day], sd[day])
        if v:
            out[day] = v
    return out


def _interp_curve(points):
    """Ricostruisce 04:00-21:00/10' senza extrapolazione."""
    if not points:
        return None
    by_min = {}
    for minute, wind in points:
        by_min.setdefault(float(minute), []).append(float(wind))
    pts = [(m, _mean(by_min[m])) for m in sorted(by_min)]
    if not pts or pts[0][0] > 4 * 60 + 10 or pts[-1][0] < 20 * 60 + 50:
        return None

    out = []
    j = 0
    for target in GRID_MIN:
        while j + 1 < len(pts) and pts[j + 1][0] < target:
            j += 1
        if j < len(pts) and abs(pts[j][0] - target) < 1e-9:
            out.append(pts[j][1]); continue
        if j + 1 >= len(pts):
            out.append(None); continue
        xa, ya = pts[j]; xb, yb = pts[j + 1]
        if xa > target or xb < target or xb - xa > MAX_INTERP_GAP_MIN:
            out.append(None); continue
        f = (target - xa) / float(xb - xa)
        out.append(ya + f * (yb - ya))

    if sum(v is not None for v in out) < math.ceil(MIN_COVERAGE * len(GRID_MIN)):
        return None
    # Nessuna extrapolazione agli estremi: i punti mancanti interni possono
    # essere riempiti solo se racchiusi da due osservazioni valide.
    for i, v in enumerate(out):
        if v is not None:
            continue
        ia = next((x for x in range(i - 1, -1, -1) if out[x] is not None), None)
        ib = next((x for x in range(i + 1, len(out)) if out[x] is not None), None)
        if ia is None or ib is None:
            return None
        f = (i - ia) / float(ib - ia)
        out[i] = out[ia] + f * (out[ib] - out[ia])
    return out


def _observed_curves(start_day=TRAIN_START, end_day=TRAIN_END):
    rows = store.connect().execute(
        "SELECT ts, AVG(wind_kn) wind_kn FROM obs_sample "
        "WHERE station=? AND wind_kn IS NOT NULL AND ts>=? AND ts<? "
        "GROUP BY ts ORDER BY ts",
        (STATION, start_day + "T00:00:00Z",
         (_dt.date.fromisoformat(end_day) + _dt.timedelta(days=2)).isoformat() + "T00:00:00Z")
    ).fetchall()
    byday = {}
    for r in rows:
        dt = parse_dt_any(r["ts"])
        if dt is None:
            continue
        loc = to_local(dt)
        day = loc.date().isoformat()
        if day < start_day or day > end_day:
            continue
        minute = loc.hour * 60 + loc.minute + loc.second / 60.0
        if 3 * 60 + 30 <= minute <= 21 * 60 + 30:
            byday.setdefault(day, []).append((minute, r["wind_kn"]))
    out = {}
    for day, pts in byday.items():
        curve = _interp_curve(pts)
        if not curve:
            continue
        peak = max(curve)
        if peak < MIN_PEAK:
            continue
        out[day] = tuple(max(0.0, x / peak) for x in curve)
    return out


def _build_library():
    era = _archive_daily("era5", TRAIN_START, TRAIN_END)
    curves = _observed_curves()
    common = sorted(set(era).intersection(curves))
    # Integrita' scientifica: il protocollo validato aveva esattamente 4020
    # giornate. Se il DB non riproduce quel campione, non si usa in silenzio
    # un motore diverso da quello validato.
    if len(common) != EXPECTED_TRAIN_DAYS:
        return None, None, {"reason": "training_days", "n": len(common),
                            "expected": EXPECTED_TRAIN_DAYS}
    stats = _stats([era[d] for d in common])
    if not stats:
        return None, None, {"reason": "era5_stats", "n": len(common)}
    lib = []
    for day in common:
        z = _z(era[day], stats)
        if z is not None:
            lib.append({"day": day, "z": z, "curve": curves[day]})
    if len(lib) != EXPECTED_TRAIN_DAYS:
        return None, None, {"reason": "training_z", "n": len(lib),
                            "expected": EXPECTED_TRAIN_DAYS}
    return lib, stats, {"reason": "ok", "n": len(lib)}


def _ensure_library():
    if _CACHE["library"] is not None and time.time() - _CACHE["at"] < CACHE_S:
        return _CACHE["library"], _CACHE["era_stats"]
    lib, stats, diag = _build_library()
    _CACHE.update({"library": lib, "era_stats": stats,
                   "diagnostic": diag, "lead_stats": {}, "at": time.time()})
    return lib, stats


def diagnostic():
    _ensure_library()
    return dict(_CACHE.get("diagnostic") or {})


def _lead_stats(lead):
    lead = int(lead)
    if lead in _CACHE["lead_stats"]:
        return _CACHE["lead_stats"][lead]
    # Distribuzione della STESSA sorgente usata nel test: previous-runs
    # best_match alla specifica scadenza. Non ERA5 e non l'ensemble.
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    daily = _archive_daily("lead%d" % lead, "2024-01-01", yesterday)
    stats = None
    if len(daily) >= 900:
        freshest = max(daily)
        lag = (_dt.date.fromisoformat(yesterday) - _dt.date.fromisoformat(freshest)).days
        if lag <= 3:
            stats = _stats(list(daily.values()))
    _CACHE["lead_stats"][lead] = stats
    return stats


def _current_rows(day, point):
    a = (_dt.date.fromisoformat(day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    b = (_dt.date.fromisoformat(day) + _dt.timedelta(days=1)).isoformat() + "T23:59:59Z"
    return store.archive_rows(point, a, b)


def _current_conditions(day):
    pn = store.point_key(NORTH[0], NORTH[1], CURRENT_SOURCE)
    ps = store.point_key(SOUTH[0], SOUTH[1], CURRENT_SOURCE)
    return daily_conditions(day, _current_rows(day, pn), _current_rows(day, ps))


def _median_template(neighbours):
    if len(neighbours) != K:
        return None
    curve = tuple(statistics.median([n["curve"][i] for n in neighbours])
                  for i in range(len(GRID_MIN)))
    peak = max(curve) if curve else 0.0
    return tuple(v / peak for v in curve) if peak > 0 else None


def choose(day, lead, current=None):
    """Seleziona i tre analoghi usando solo informazioni disponibili in previsione."""
    if int(lead) not in (1, 2, 3):
        return None, None
    library, _era = _ensure_library()
    if not library:
        return None, None
    stats = _lead_stats(lead)
    current = current or _current_conditions(day)
    target = _z(current, stats)
    if target is None:
        return None, None
    ranked = sorted(((_distance(target, row["z"]), row) for row in library),
                    key=lambda x: x[0])
    picked = [r for _d, r in ranked[:K]]
    template = _median_template(picked)
    if not template:
        return None, None
    return template, {
        "k": K,
        "days": [r["day"] for r in picked],
        "distances": [round(d, 3) for d, _r in ranked[:K]],
        "training_days": len(library),
        "source": "best_match lead%d -> ERA5/T0193" % int(lead),
    }


def _interp_scalar(rows, hour, key, default=None):
    pts = sorted((float(r["hour"]), r.get(key)) for r in rows if r.get(key) is not None)
    if not pts:
        return default
    if hour <= pts[0][0]:
        return pts[0][1]
    if hour >= pts[-1][0]:
        return pts[-1][1]
    for (ha, va), (hb, vb) in zip(pts, pts[1:]):
        if ha <= hour <= hb:
            f = (hour - ha) / float(hb - ha)
            return float(va) + f * (float(vb) - float(va))
    return default


def _interp_dir(rows, hour):
    pts = sorted((float(r["hour"]), r.get("dir")) for r in rows if r.get("dir") is not None)
    if not pts:
        return None
    # Interpolazione vettoriale, per non passare da 359 a 180 a 1 grado.
    cs = [{"hour": h, "c": math.cos(math.radians(d)),
           "s": math.sin(math.radians(d))} for h, d in pts]
    c = _interp_scalar(cs, hour, "c")
    s = _interp_scalar(cs, hour, "s")
    if c is None or s is None:
        return None
    return (math.degrees(math.atan2(s, c)) + 360.0) % 360.0


def apply_to_profile(day, lead, base_profile):
    """Restituisce il profilo Torbole a 10 minuti, conservando il picco corrente.

    `base_profile` e' la curva che il motore avrebbe mostrato senza analoghi.
    Il suo massimo resta identico: sostituiamo solo la forma.
    """
    if int(lead) not in (1, 2, 3) or not base_profile:
        return base_profile, None
    peak = max((float(r["wind"]) for r in base_profile if r.get("wind") is not None),
               default=0.0)
    if peak <= 0:
        return base_profile, None
    template, meta = choose(day, lead)
    if template is None:
        return base_profile, None

    out = []
    for minute, rel in zip(GRID_MIN, template):
        h = minute / 60.0
        wind = peak * rel
        base_w = _interp_scalar(base_profile, h, "wind", 0.0) or 0.0
        base_g = _interp_scalar(base_profile, h, "gust", base_w) or base_w
        ratio = max(1.0, base_g / base_w) if base_w > 0.2 else 1.0
        lo = _interp_scalar(base_profile, h, "lo", wind)
        hi = _interp_scalar(base_profile, h, "hi", wind)
        half = max(0.0, ((hi or wind) - (lo or wind)) / 2.0)
        dt_local = _dt.datetime.fromisoformat(day) + _dt.timedelta(minutes=minute)
        key = iso_utc(local_naive_to_utc(dt_local))
        out.append({
            "hour": h, "key": key, "wind": wind, "gust": wind * ratio,
            "lo": max(0.0, wind - half), "hi": wind + half,
            "dir": _interp_dir(base_profile, h),
            "t2m": _interp_scalar(base_profile, h, "t2m"),
            "cloud": _interp_scalar(base_profile, h, "cloud"),
            "precip": _interp_scalar(base_profile, h, "precip"),
        })
    meta = dict(meta)
    meta["peak_preserved"] = peak
    meta["grid_minutes"] = 10
    return out, meta


# ------------------------- validazione riproducibile -------------------------

def _sustained(curve, threshold=12.0, start=11 * 60, end=20 * 60):
    vals = [(m, curve[i]) for i, m in enumerate(GRID_MIN) if start <= m <= end]
    run = 0
    for _m, v in vals:
        run = run + 1 if v >= threshold else 0
        if run >= 3:
            return True
    return False


def _minutes_above(curve, threshold=12.0, start=11 * 60, end=20 * 60):
    return 10 * sum(1 for i, m in enumerate(GRID_MIN)
                    if start <= m <= end and curve[i] >= threshold)


def _steepness(curve, start=11 * 60, end=20 * 60):
    vals = [(m, curve[i]) for i, m in enumerate(GRID_MIN) if start <= m <= end]
    return max((vals[i + 3][1] - vals[i][1] for i in range(len(vals) - 3)), default=0.0)


def validation_report(start_day="2025-01-01", end_day="2026-09-14"):
    """Porta scientifica shape-only sullo STESSO campione D+1/D+2/D+3.

    Come nel test che ha scelto k, a ogni concorrente viene regalato il picco
    vero: qui si verifica solo la forma, non l'errore di livello.
    """
    library, _ = _ensure_library()
    if not library:
        return {"usable": False, "diagnostic": diagnostic()}
    obs_norm = _observed_curves(start_day, end_day)
    # La standardizzazione descrive la SORGENTE, quindi usa tutta la sua
    # distribuzione disponibile dal 2024. Il campione di conferma resta invece
    # rigorosamente 2025-2026 e comune ai tre lead.
    source_all = {lead: _archive_daily("lead%d" % lead, "2024-01-01", end_day)
                  for lead in (1, 2, 3)}
    pred = {lead: {d: v for d, v in source_all[lead].items()
                   if start_day <= d <= end_day}
            for lead in (1, 2, 3)}
    common = set(obs_norm)
    for lead in (1, 2, 3):
        common &= set(pred[lead])
    days = sorted(common)
    if len(days) != EXPECTED_CONFIRM_DAYS:
        return {"usable": False, "reason": "confirm_days", "n": len(days),
                "expected": EXPECTED_CONFIRM_DAYS}

    raw = {day: _raw_curve(day) for day in days}
    if any(raw[d] is None for d in days):
        return {"usable": False, "reason": "raw_curve_missing"}

    def measure(lead, day_map):
        stats = _stats(list(source_all[lead].values()))
        if stats is None:
            return None
        tp = fp = pos = neg = used = 0
        bias, abserr, slopes, true_slopes = [], [], [], []
        for day in days:
            source_day = day_map.get(day, day)
            z = _z(pred[lead][source_day], stats)
            if z is None:
                continue
            ranked = sorted(((_distance(z, r["z"]), r) for r in library),
                            key=lambda x: x[0])
            template = _median_template([r for _d, r in ranked[:K]])
            if template is None:
                continue
            real = tuple(raw[day]); peak = max(real)
            forecast = tuple(peak * x for x in template)
            yp, yt = _sustained(forecast), _sustained(real)
            if yt:
                pos += 1; tp += int(yp)
            else:
                neg += 1; fp += int(yp)
            dmin = _minutes_above(forecast) - _minutes_above(real)
            bias.append(dmin); abserr.append(abs(dmin))
            slopes.append(_steepness(forecast)); true_slopes.append(_steepness(real))
            used += 1
        return {
            "n": used,
            "hits": tp / pos if pos else None,
            "false_alarms": fp / neg if neg else None,
            "minute_error": _mean(abserr),
            "bias_minutes": _mean(bias),
            "steepness": statistics.median(slopes) if slopes else None,
            "true_steepness": statistics.median(true_slopes) if true_slopes else None,
        }

    leads = {lead: measure(lead, {}) for lead in (1, 2, 3)}
    if any(v is None or v.get("n") != EXPECTED_CONFIRM_DAYS
           for v in leads.values()):
        return {"usable": False, "reason": "validation_incomplete",
                "n": len(days), "leads": leads}

    # Nullo obbligatorio: D+1 con condizioni di un altro giorno, permutazione
    # deterministica. Se non peggiora chiaramente, la selezione non vale.
    import random
    shuffled = days[:]
    random.Random(20260915).shuffle(shuffled)
    null = measure(1, dict(zip(days, shuffled)))
    return {"usable": True, "n": len(days), "from": days[0], "to": days[-1],
            "leads": leads, "null": null}



def benchmark_gate(report):
    """Verifica che il codice riproduca il blocco cieco gia' validato.

    Le tolleranze coprono arrotondamenti/interpolazione, non un metodo diverso.
    Il nullo deve inoltre degradare in modo evidente.
    """
    reasons = []
    if not report or not report.get("usable") or report.get("n") != EXPECTED_CONFIRM_DAYS:
        return False, ["campione di conferma diverso da %d" % EXPECTED_CONFIRM_DAYS]
    tol = {"hits": .025, "false_alarms": .035, "minute_error": 8.0,
           "bias_minutes": 5.0, "steepness": .6}
    for lead, ref in BENCHMARK.items():
        got = (report.get("leads") or {}).get(lead)
        if not got:
            reasons.append("D+%d mancante" % lead); continue
        for key, target in ref.items():
            value = got.get(key)
            if value is None or abs(float(value) - target) > tol[key]:
                reasons.append("D+%d %s=%s (atteso %.3f +/- %.3f)"
                               % (lead, key, value, target, tol[key]))
        tv = got.get("true_steepness")
        if tv is None or abs(float(tv) - 7.6) > .5:
            reasons.append("D+%d ripidezza vera=%s (attesa 7.6 +/- 0.5)" % (lead, tv))
    null = report.get("null") or {}
    if null.get("hits") is None or null["hits"] >= .65:
        reasons.append("nullo non degrada abbastanza sui colpi")
    if null.get("false_alarms") is None or null["false_alarms"] <= .15:
        reasons.append("nullo non degrada abbastanza sui falsi")
    return not reasons, reasons


def promote_from_validation(report=None):
    """Apre la porta solo se il codice riproduce il benchmark congelato."""
    report = report or validation_report()
    ok, reasons = benchmark_gate(report)
    if ok:
        store.meta_set(GATE_KEY, GATE_SIGNATURE)
    else:
        store.meta_set(GATE_KEY, "closed")
    return ok, reasons, report


def promoted():
    return store.meta_get(GATE_KEY) == GATE_SIGNATURE

def _raw_curve(day):
    rows = store.connect().execute(
        "SELECT ts, AVG(wind_kn) wind_kn FROM obs_sample WHERE station=? "
        "AND wind_kn IS NOT NULL AND ts>=? AND ts<? GROUP BY ts ORDER BY ts",
        (STATION,
         (_dt.date.fromisoformat(day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z",
         (_dt.date.fromisoformat(day) + _dt.timedelta(days=2)).isoformat() + "T00:00:00Z")
    ).fetchall()
    pts = []
    for r in rows:
        dt = parse_dt_any(r["ts"])
        if dt is None or local_day(dt) != day:
            continue
        loc = to_local(dt)
        pts.append((loc.hour * 60 + loc.minute + loc.second / 60.0, r["wind_kn"]))
    curve = _interp_curve(pts)
    if not curve or max(curve) < MIN_PEAK:
        return None
    return tuple(curve)


__all__ = ["CURRENT_SOURCE", "K", "GRID_MIN", "FEATURES",
           "daily_conditions", "choose", "apply_to_profile", "diagnostic",
           "validation_report", "benchmark_gate", "promote_from_validation",
           "promoted"]
