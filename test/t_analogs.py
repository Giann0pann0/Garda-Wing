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

# --------------------------------------------------------------------------
# La persistenza e' UNA, e viene da fuori
# --------------------------------------------------------------------------
# Era il difetto piu' silenzioso della prima stesura: `run >= 3` su una
# griglia di dieci minuti sono VENTI minuti, non trenta, perche' tre campioni
# coprono due intervalli. La porta misurava quindi una cosa piu' facile della
# specifica, e i suoi numeri non erano confrontabili con il benchmark.
from gardawind.orari import PERSISTENZA_MIN

ok(analogs._persistenza_min() == PERSISTENZA_MIN,
   "la mezz'ora della porta e' quella di orari.py, non una copia (%g)"
   % analogs._persistenza_min())
ok(analogs._punti_persistenza() == 4,
   "trenta minuti su griglia da dieci sono QUATTRO campioni, non tre (%d)"
   % analogs._punti_persistenza())

n = len(analogs.GRID_MIN)
i11 = analogs.GRID_MIN.index(11 * 60)


def con_tratto(punti_sopra, da=i11 + 6):
    """Una curva piatta a 6 kn con un tratto a 14 kn lungo `punti_sopra`."""
    return tuple(14.0 if da <= i < da + punti_sopra else 6.0 for i in range(n))


ok(not analogs._sustained(con_tratto(3)),
   "venti minuti sopra soglia NON sono una giornata navigabile")
ok(analogs._sustained(con_tratto(4)),
   "trenta minuti si': e' la stessa mezz'ora della climatologia")
ok(analogs._minutes_above(con_tratto(4)) == 40,
   "i minuti sopra soglia contano i campioni per dieci (%d)"
   % analogs._minutes_above(con_tratto(4)))

# --------------------------------------------------------------------------
# La porta deve poter APRIRE, non solo chiudere
# --------------------------------------------------------------------------
# Con il controllo esatto sul campione, una giornata di differenza
# nell'archivio - un buco di centralina che si chiude, una run in piu' -
# chiudeva la porta per sempre con un messaggio che non diceva niente. La
# tolleranza e' dichiarata, e il conteggio vero si stampa sempre.
def rapporto(n_giorni):
    r = {"usable": True, "n": n_giorni, "leads": {},
         "null": {"hits": .54, "false_alarms": .25}}
    for lead, vals in analogs.BENCHMARK.items():
        row = dict(vals)
        row["true_steepness"] = 7.6
        r["leads"][lead] = row
    return r


atteso = analogs.EXPECTED_CONFIRM_DAYS
tol = analogs.TOLLERANZA_CONFERMA_GG
g1, _w = analogs.benchmark_gate(rapporto(atteso - 3))
ok(g1, "tre giornate in meno non chiudono la porta")
g2, w2 = analogs.benchmark_gate(rapporto(atteso - tol - 40))
ok(not g2 and any("campione" in x for x in w2),
   "ma un campione molto diverso la chiude, dicendo il conteggio: %s" % w2[:1])
g3, w3 = analogs.benchmark_gate({"usable": False, "reason": "confirm_days"})
ok(not g3 and w3 and "confirm_days" in str(w3),
   "e senza misura la porta dice PERCHE' non ha misurato, non solo che e' chiusa")

# --------------------------------------------------------------------------
# Anche la LIBRERIA deve poter esistere con un archivio che cresce
# --------------------------------------------------------------------------
# La finestra di addestramento e' chiusa nel 2023, ma i dati di quelle
# giornate no: un recupero di storico della centralina cambia il conteggio, e
# col controllo esatto il motore si spegneva per sempre senza dirlo. Qui si
# pretende che una libreria vicina si costruisca e che una molto diversa no,
# dicendo il numero vero.
import datetime as _dt


def _finta_libreria(n_giorni):
    giorno = _dt.date(2013, 1, 1)
    era, curve = {}, {}
    for i in range(n_giorni):
        d = (giorno + _dt.timedelta(days=i)).isoformat()
        era[d] = {k: float((i * 7 + j * 13) % 100) for j, k in enumerate(analogs.FEATURES)}
        curve[d] = tuple(0.3 if x < 50 else 1.0 for x in range(n))
    return era, curve


def _con_libreria(n_giorni):
    va, vo = analogs._archive_daily, analogs._observed_curves
    era, curve = _finta_libreria(n_giorni)
    analogs._archive_daily = lambda source, a, b: era
    analogs._observed_curves = lambda *a, **k: curve
    try:
        return analogs._build_library()
    finally:
        analogs._archive_daily, analogs._observed_curves = va, vo


lib, st_era, diag = _con_libreria(analogs.EXPECTED_TRAIN_DAYS)
ok(lib is not None and len(lib) == analogs.EXPECTED_TRAIN_DAYS,
   "con il campione congelato la libreria si costruisce (%s)" % diag.get("reason"))
lib2, _s2, d2 = _con_libreria(analogs.EXPECTED_TRAIN_DAYS + 12)
ok(lib2 is not None and len(lib2) == analogs.EXPECTED_TRAIN_DAYS + 12,
   "dodici giornate recuperate dallo storico non spengono il motore (%s)"
   % d2.get("reason"))
lib3, _s3, d3 = _con_libreria(analogs.EXPECTED_TRAIN_DAYS - 300)
ok(lib3 is None and d3.get("reason") == "training_days"
   and d3.get("n") == analogs.EXPECTED_TRAIN_DAYS - 300,
   "trecento in meno la spengono, e la diagnostica dice quante ce n'erano (%s)"
   % d3)
ok(d3.get("tolerance") == analogs.TOLLERANZA_ADDESTRAMENTO_GG,
   "con la tolleranza dichiarata accanto, non da indovinare")

# Chi decide sulla DIMENSIONE del campione e' uno solo: la porta. Dentro
# validation_report il confronto col numero congelato era un secondo giudice
# senza tolleranza, e vinceva lui - la misura non veniva nemmeno prodotta. Il
# vincolo che resta li' e' un altro: i tre lead devono misurare le STESSE
# giornate. Questo controllo e' strutturale perche' il difetto e' strutturale:
# non si vede nei numeri, si vede in chi confronta cosa.
import inspect

sorgente = inspect.getsource(analogs.validation_report)
ok("!= EXPECTED_CONFIRM_DAYS" not in sorgente
   and "> EXPECTED_CONFIRM_DAYS" not in sorgente,
   "dentro la misura il numero congelato non fa da giudice, solo da etichetta")
ok('v.get("n") != len(days)' in sorgente,
   "ma i tre lead devono aver misurato le stesse giornate, non un numero fisso")
ok("EXPECTED_CONFIRM_DAYS" in inspect.getsource(analogs.benchmark_gate)
   and "TOLLERANZA_CONFERMA_GG" in inspect.getsource(analogs.benchmark_gate),
   "e il confronto col campione congelato vive nella porta, con la tolleranza")

# Il nullo resta obbligatorio: se non degrada, la porta non apre comunque.
senza_nullo = rapporto(atteso)
senza_nullo["null"] = {"hits": .80, "false_alarms": .05}
g4, w4 = analogs.benchmark_gate(senza_nullo)
ok(not g4 and any("nullo" in x for x in w4),
   "un nullo che non degrada chiude la porta anche con i numeri giusti")

print("%d controlli analoghi" % passati)
