"""Controlli del motore analogico: proteggono il protocollo, non solo la sintassi."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gardawind import analogs

passati = 0

def ok(cond, msg):
    global passati
    if cond:
        passati += 1; print("PASS " + msg)
    else:
        print("FAIL " + msg)

# Standardizzazione sorgente-specifica.
v = {k: float(i + 1) for i, k in enumerate(analogs.FEATURES)}
st = {k: (v[k] - 2.0, 2.0) for k in analogs.FEATURES}
z = analogs._z(v, st)
ok(z is not None and all(abs(x - 1.0) < 1e-9 for x in z),
   "z-score usa le statistiche passate, non valori assoluti")

# k deve restare 3: e' un iperparametro scelto prima sul 2024.
ok(analogs.K == 3, "k=3 e' bloccato dal protocollo validato")

# La mediana di 3 gradini conserva un gradino maggioritario.
n = len(analogs.GRID_MIN)
c1 = tuple(0.2 if i < 50 else 1.0 for i in range(n))
c2 = tuple(0.2 if i < 51 else 1.0 for i in range(n))
c3 = tuple(0.2 if i < 80 else 1.0 for i in range(n))
t = analogs._median_template([{"curve": c1}, {"curve": c2}, {"curve": c3}])
ok(t[50] < .5 and t[51] > .9, "mediana k=3 conserva il gradino")

# Nessun onset alignment: la doppia gobba deve rimanere sulla griglia assoluta.
left = tuple(1.0 if i < 35 else .2 for i in range(n))
right = tuple(.2 if i < 70 else 1.0 for i in range(n))
both = tuple(1.0 if i < 35 or i >= 70 else .2 for i in range(n))
t2 = analogs._median_template([{"curve": left}, {"curve": right}, {"curve": both}])
ok(t2[20] > .9 and t2[55] < .3 and t2[80] > .9,
   "nessun allineamento dell'ingresso: Peler e Ora non si sovrappongono")

# Applicazione: 10 minuti, stesso picco, nessuna modifica D+0.
base = []
for h in range(4, 22):
    base.append({"hour": float(h), "key": "x", "wind": 8.0,
                 "gust": 12.0, "lo": 6.0, "hi": 10.0,
                 "dir": 180.0, "t2m": 20.0, "cloud": 20.0, "precip": 0.0})
old = analogs.choose
try:
    analogs.choose = lambda day, lead, current=None: (
        tuple(.25 if i < 55 else 1.0 for i in range(n)),
        {"k": 3, "days": ["a", "b", "c"]})
    shaped, meta = analogs.apply_to_profile("2026-09-16", 1, base)
finally:
    analogs.choose = old
ok(len(shaped) == 103 and abs(shaped[1]["hour"] - shaped[0]["hour"] - 1/6) < 1e-9,
   "profilo analogico resta sulla griglia reale di 10 minuti")
ok(abs(max(r["wind"] for r in shaped) - 8.0) < 1e-9,
   "il picco del motore corrente resta invariato")
ok(meta and meta["grid_minutes"] == 10,
   "diagnostica dichiara la griglia da 10 minuti")
unchanged, m0 = analogs.apply_to_profile("2026-09-15", 0, base)
ok(unchanged == base and m0 is None, "D+0 non usa implicitamente il modello D+1")

# Ripidezza: un gradino da 3 a 10 in 30 minuti deve misurare 7, non essere smussato.
curve = tuple(3.0 if i < 60 else 10.0 for i in range(n))
ok(abs(analogs._steepness(curve) - 7.0) < 1e-9,
   "metrica di ripidezza protegge le transizioni in 30 minuti")

# Il gate di regressione deve aprire solo vicino ai numeri congelati.
rep = {"usable": True, "n": analogs.EXPECTED_CONFIRM_DAYS, "leads": {},
       "null": {"hits": .54, "false_alarms": .25}}
for lead, vals in analogs.BENCHMARK.items():
    row = dict(vals); row["true_steepness"] = 7.6
    rep["leads"][lead] = row
gate, why = analogs.benchmark_gate(rep)
ok(gate and not why, "gate apre sui numeri del benchmark congelato")
rep["leads"][1]["steepness"] = 3.0
gate, why = analogs.benchmark_gate(rep)
ok(not gate and why, "gate chiude se la curva torna liscia")

print("%d controlli analoghi" % passati)
