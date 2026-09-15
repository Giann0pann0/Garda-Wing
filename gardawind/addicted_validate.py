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


def rapporto_completo(conn=None):
    return {
        "media": confronto_media(conn),
        "raffica_recente": confronto_raffica_recente(conn),
        "massimi_sospetti": valori_massimo_sospetti(conn),
        "campione_brenzone": identita_campione_brenzone(conn),
    }
