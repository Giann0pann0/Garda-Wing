"""Validazione indipendente dello storico SportAddicted contro T0193.

Non modifica il modello e non scrive dati. Serve a tenere separati tre fatti:
- mavg e' una serie utile ma non e' sulla stessa scala della T0193;
- mmax assomiglia al massimo orario della raffica nel periodo recente in cui
  T0193 espone davvero la raffica;
- nello storico esistono valori ripetuti/sospetti (es. 49.6 a Torbole), quindi
  mmax non va usato alla cieca come gust_rec 30'.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import store
from .util import recurrent_gust

ROME = ZoneInfo("Europe/Rome")


def _finite(x):
    return x is not None and math.isfinite(float(x))


def metriche(coppie):
    """Metriche per coppie (riferimento, candidato)."""
    pts = [(float(a), float(b)) for a, b in coppie if _finite(a) and _finite(b)]
    n = len(pts)
    if not n:
        return {"n": 0, "bias": None, "mae": None, "rmse": None, "corr": None}
    a = [x for x, _ in pts]
    b = [y for _, y in pts]
    diff = [y - x for x, y in pts]
    ma = sum(a) / n
    mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    cov = sum((x - ma) * (y - mb) for x, y in pts)
    corr = cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None
    return {
        "n": n,
        "bias": sum(diff) / n,
        "mae": sum(abs(x) for x in diff) / n,
        "rmse": math.sqrt(sum(x * x for x in diff) / n),
        "corr": corr,
    }


def _local_hour(iso_utc):
    d = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return d.astimezone(ROME).hour


def _periodo(h):
    if 6 <= h < 11:
        return "peler_06_11"
    if 11 <= h < 20:
        return "ora_11_20"
    return "altro"


def confronto_media(conn=None):
    """Torbole Addicted mavg vs media oraria T0193, stesso istante UTC."""
    c = conn or store.connect()
    rows = c.execute(
        "SELECT o.hour,o.wind_mean,a.wind_mean_kn "
        "FROM obs_hour o JOIN addicted_hour a ON a.hour=o.hour "
        "WHERE o.station='T0193' AND a.station='torbole' "
        "AND o.wind_mean IS NOT NULL AND a.wind_mean_kn IS NOT NULL"
    ).fetchall()
    tutto = [(r[1], r[2]) for r in rows]
    gruppi = defaultdict(list)
    for r in rows:
        gruppi[_periodo(_local_hour(r[0]))].append((r[1], r[2]))
    return {"tutto": metriche(tutto), **{k: metriche(v) for k, v in gruppi.items()}}


def confronto_raffica_recente(conn=None):
    """Confronto mmax con raffica T0193 nel periodo in cui la raffica esiste.

    La raffica ricorrente resta la mediana mobile canonica a 30 minuti; mmax
    viene confrontato sia col massimo osservato dell'ora sia con quella
    ricorrente, senza chiamare le due grandezze con lo stesso nome.
    """
    c = conn or store.connect()
    rows = c.execute(
        "SELECT ts,wind_kn,gust_kn FROM obs_sample "
        "WHERE station='T0193' AND gust_kn IS NOT NULL ORDER BY ts"
    ).fetchall()
    if not rows:
        return {"ore": 0, "max_orario": metriche([]), "ricorrente30": metriche([])}

    pts = []
    for r in rows:
        d = datetime.fromisoformat(r[0].replace("Z", "+00:00"))
        pts.append((d.timestamp() / 60.0, float(r[2])))
    ric = recurrent_gust(pts, centered=True)

    by_hour = defaultdict(lambda: {"gust": [], "ric": []})
    for r, (_t, gr) in zip(rows, ric):
        h = r[0][:13] + ":00:00Z"
        by_hour[h]["gust"].append(float(r[2]))
        if gr is not None:
            by_hour[h]["ric"].append(float(gr))

    max_pairs, rec_pairs = [], []
    for h, vals in by_hour.items():
        a = c.execute(
            "SELECT hourly_max_kn FROM addicted_hour "
            "WHERE station='torbole' AND hour=?", (h,)
        ).fetchone()
        if not a or a[0] is None:
            continue
        sa = float(a[0])
        max_pairs.append((max(vals["gust"]), sa))
        if vals["ric"]:
            rec_pairs.append((statistics.median(vals["ric"]), sa))
    return {
        "ore": len(max_pairs),
        "max_orario": metriche(max_pairs),
        "ricorrente30": metriche(rec_pairs),
    }


def valori_massimo_sospetti(conn=None, min_value=40.0, min_repeat=20):
    """Cerca massimi estremi ripetuti troppe volte per sembrare eventi singoli.

    Non li cancella: li segnala. Il criterio e' volutamente conservativo e
    serve a impedire che una costante ripetuta entri nel modello senza audit.
    """
    c = conn or store.connect()
    rows = c.execute(
        "SELECT hourly_max_kn FROM addicted_hour "
        "WHERE station='torbole' AND hourly_max_kn IS NOT NULL "
        "AND hourly_max_kn>=?", (float(min_value),)
    ).fetchall()
    cnt = Counter(round(float(r[0]), 3) for r in rows)
    return sorted(
        [{"value": v, "count": n} for v, n in cnt.items() if n >= min_repeat],
        key=lambda x: (-x["count"], x["value"]),
    )


def identita_campione_brenzone(conn=None):
    c = conn or store.connect()
    r = c.execute(
        "SELECT COUNT(*) n, "
        "SUM(CASE WHEN c.wind_mean_kn=b.wind_mean_kn AND "
        "c.hourly_max_kn=b.hourly_max_kn THEN 1 ELSE 0 END) uguali "
        "FROM addicted_hour c JOIN addicted_hour b ON b.hour=c.hour "
        "WHERE c.station='campione' AND b.station='brenzone'"
    ).fetchone()
    n = int(r[0] or 0)
    ug = int(r[1] or 0)
    return {"n": n, "uguali": ug, "quota": (ug / n if n else None)}



def qc_massimi_storici(conn=None, tolleranza_kn=0.2):
    """QC descrittivo di mmax per stazione, senza cancellare dati.

    Un plateau alto viene solo SEGNALATO quando un valore esatto occupa almeno
    lo 0.5% della serie (minimo 20 ore) ed e' nel percentile 99 o oltre.
    E' un criterio conservativo per trovare masse puntuali come 49.6 Torbole:
    non trasforma automaticamente il valore in sentinella e non modifica dati.
    """
    c = conn or store.connect()
    stations = [r[0] for r in c.execute(
        "SELECT DISTINCT station FROM addicted_hour ORDER BY station"
    ).fetchall()]
    out = {}
    for station in stations:
        rows = c.execute(
            "SELECT wind_mean_kn,hourly_max_kn FROM addicted_hour "
            "WHERE station=?", (station,)
        ).fetchall()
        vals = [float(r[1]) for r in rows if _finite(r[1])]
        if not vals:
            out[station] = {"n": len(rows), "n_max": 0, "plateau_sospetti": []}
            continue
        sv = sorted(vals)
        def quantile(p):
            # interpolazione lineare compatibile con la definizione usuale
            pos = (len(sv) - 1) * p
            lo = int(math.floor(pos)); hi = int(math.ceil(pos))
            if lo == hi:
                return sv[lo]
            return sv[lo] + (sv[hi] - sv[lo]) * (pos - lo)
        p99 = quantile(0.99)
        counts = Counter(round(v, 3) for v in vals)
        min_repeat = max(20, int(math.ceil(0.005 * len(vals))))
        plateaux = sorted(
            [{"value": v, "count": n, "share": n / len(vals)}
             for v, n in counts.items() if v >= p99 and n >= min_repeat],
            key=lambda x: (-x["count"], x["value"]),
        )
        bad_below = 0
        zero_with_mean = 0
        missing = 0
        for mean, mx in rows:
            if not _finite(mx):
                missing += 1
                continue
            if _finite(mean) and float(mx) + float(tolleranza_kn) < float(mean):
                bad_below += 1
            if _finite(mean) and float(mx) == 0.0 and float(mean) > float(tolleranza_kn):
                zero_with_mean += 1
        suspect_values = {x["value"] for x in plateaux}
        safe = 0
        for mean, mx in rows:
            if not _finite(mx):
                continue
            x = round(float(mx), 3)
            if x in suspect_values:
                continue
            if _finite(mean) and float(mx) + float(tolleranza_kn) < float(mean):
                continue
            if _finite(mean) and float(mx) == 0.0 and float(mean) > float(tolleranza_kn):
                continue
            safe += 1
        out[station] = {
            "n": len(rows), "n_max": len(vals), "missing_max": missing,
            "p50": quantile(0.50), "p95": quantile(0.95),
            "p99": p99, "p999": quantile(0.999), "max": max(vals),
            "max_sotto_media": bad_below, "zero_con_media": zero_with_mean,
            "plateau_sospetti": plateaux, "ore_qc_ok": safe,
            "quota_qc_ok": safe / len(rows) if rows else None,
        }
    return out


def identita_shiftata_campione_brenzone(conn=None, giorni=7):
    """Modello di nullo: Campione contro Brenzone sfasata di N giorni.

    Il confronto viene fatto in Python per non rompere l'indice SQL con
    funzioni datetime sulle centinaia di migliaia di righe.
    """
    from datetime import timedelta
    c = conn or store.connect()
    ca = c.execute(
        "SELECT hour,wind_mean_kn,hourly_max_kn FROM addicted_hour "
        "WHERE station='campione'"
    ).fetchall()
    br = c.execute(
        "SELECT hour,wind_mean_kn,hourly_max_kn FROM addicted_hour "
        "WHERE station='brenzone'"
    ).fetchall()
    bmap = {r[0]: (r[1], r[2]) for r in br}
    delta = timedelta(days=int(giorni))
    n = ug = 0
    for hour, mean, mx in ca:
        d = datetime.fromisoformat(hour.replace("Z", "+00:00")) + delta
        target = d.isoformat().replace("+00:00", "Z")
        b = bmap.get(target)
        if b is None:
            continue
        n += 1
        if mean == b[0] and mx == b[1]:
            ug += 1
    return {"giorni": int(giorni), "n": n, "uguali": ug,
            "quota": ug / n if n else None}


def rapporto_completo(conn=None):
    return {
        "media": confronto_media(conn),
        "raffica_recente": confronto_raffica_recente(conn),
        "massimi_sospetti": valori_massimo_sospetti(conn),
        "campione_brenzone": identita_campione_brenzone(conn),
        "campione_brenzone_shift7": identita_shiftata_campione_brenzone(conn, 7),
        "qc_massimi": qc_massimi_storici(conn),
        "profilo_rafficosita": profilo_rafficosita_storica(conn),
        "gate_proxy_gust_rec": gate_proxy_gust_rec(conn),
    }


def _fit_lineare(coppie):
    """Retta candidato = intercetta + pendenza * riferimento, solo descrittiva."""
    pts = [(float(x), float(y)) for x, y in coppie if _finite(x) and _finite(y)]
    if len(pts) < 2:
        return {"n": len(pts), "intercetta": None, "pendenza": None,
                "corr": None, "mae_fit": None}
    xs = [x for x, _ in pts]; ys = [y for _, y in pts]
    mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    if vx <= 0:
        return {"n": len(pts), "intercetta": None, "pendenza": None,
                "corr": None, "mae_fit": None}
    cov = sum((x - mx) * (y - my) for x, y in pts)
    b = cov / vx
    a = my - b * mx
    pred = [a + b * x for x in xs]
    mae = sum(abs(y - p) for y, p in zip(ys, pred)) / len(ys)
    vy = sum((y - my) ** 2 for y in ys)
    corr = cov / math.sqrt(vx * vy) if vy > 0 else None
    return {"n": len(pts), "intercetta": a, "pendenza": b,
            "corr": corr, "mae_fit": mae}


def profilo_rafficosita_storica(conn=None, station="torbole"):
    """Descrive il ponte mavg -> mmax sul sottoinsieme QC-ok.

    Non costruisce una proxy di gust_rec e non tocca il modello. Il rapporto
    mmax/mavg viene riassunto solo per mavg>=3 kn: sotto quella soglia il
    rapporto esplode per puro denominatore e diventa poco interpretabile.
    """
    c = conn or store.connect()
    qc = qc_massimi_storici(c).get(station, {})
    sospetti = {round(float(x["value"]), 3)
                for x in qc.get("plateau_sospetti", [])}
    rows = c.execute(
        "SELECT hour,wind_mean_kn,hourly_max_kn FROM addicted_hour "
        "WHERE station=? AND wind_mean_kn IS NOT NULL AND hourly_max_kn IS NOT NULL "
        "ORDER BY hour", (station,)
    ).fetchall()

    gruppi = defaultdict(list)
    per_mese = defaultdict(list)
    esclusi = 0
    for hour, mean, mx in rows:
        if not (_finite(mean) and _finite(mx)):
            continue
        mean = float(mean); mx = float(mx)
        if round(mx, 3) in sospetti or mx + 0.2 < mean or (mx == 0.0 and mean > 0.2):
            esclusi += 1
            continue
        h = _local_hour(hour)
        periodo = _periodo(h)
        gruppi[periodo].append((mean, mx))
        d = datetime.fromisoformat(hour.replace("Z", "+00:00")).astimezone(ROME)
        if periodo in ("peler_06_11", "ora_11_20"):
            per_mese[(periodo, d.month)].append((mean, mx))

    def riassunto(pts):
        if not pts:
            return {"n": 0}
        means = [x for x, _ in pts]
        maxs = [y for _, y in pts]
        spread = [y - x for x, y in pts]
        ratios = [y / x for x, y in pts if x >= 3.0]
        fit = _fit_lineare(pts)
        return {
            "n": len(pts),
            "mavg_mediana": statistics.median(means),
            "mmax_mediana": statistics.median(maxs),
            "spread_mediana": statistics.median(spread),
            "spread_p90": sorted(spread)[int(0.90 * (len(spread) - 1))],
            "ratio_mediana_mavg_ge3": statistics.median(ratios) if ratios else None,
            "fit": fit,
        }

    mensile = {k: riassunto(v) for k, v in sorted(per_mese.items())}
    return {
        "station": station,
        "ore_input": len(rows),
        "ore_escluse_qc": esclusi,
        "gruppi": {k: riassunto(v) for k, v in gruppi.items()},
        "mensile": mensile,
    }


def gate_proxy_gust_rec(conn=None, min_ore=1000, min_giorni=90, min_mesi=6):
    """Gate di COPERTURA per qualsiasi futura calibrazione mmax -> gust_rec.

    Non giudica la bonta' della formula: impedisce soltanto di promuoverla con
    pochi giorni o una sola stagione. I limiti sono espliciti e dichiarati,
    non costanti nascoste nella planabilita'.
    """
    c = conn or store.connect()
    rows = c.execute(
        "SELECT ts,gust_kn FROM obs_sample WHERE station='T0193' "
        "AND gust_kn IS NOT NULL ORDER BY ts"
    ).fetchall()
    if not rows:
        return {"ore": 0, "giorni": 0, "mesi": 0, "pronto": False,
                "min_ore": min_ore, "min_giorni": min_giorni, "min_mesi": min_mesi}
    ore = set(); giorni = set(); mesi = set()
    for ts, _ in rows:
        h = ts[:13] + ":00:00Z"
        a = c.execute(
            "SELECT hourly_max_kn FROM addicted_hour WHERE station='torbole' AND hour=?",
            (h,)).fetchone()
        if not a or not _finite(a[0]):
            continue
        ore.add(h)
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ROME)
        giorni.add(d.date().isoformat())
        mesi.add("%04d-%02d" % (d.year, d.month))
    pronto = len(ore) >= min_ore and len(giorni) >= min_giorni and len(mesi) >= min_mesi
    return {"ore": len(ore), "giorni": len(giorni), "mesi": len(mesi),
            "pronto": pronto, "min_ore": int(min_ore),
            "min_giorni": int(min_giorni), "min_mesi": int(min_mesi)}
