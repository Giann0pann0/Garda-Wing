"""La stagione: la mediana di ripiego, il vento atteso, il tetto della curva.

Il 19/11/2026 la pagella diceva che in quattro giorni tutti e sei gli scarti si
erano allargati, e Gian: "l'inverno e' diverso, ma dovremmo saperlo". Andando a
guardare, il modello l'inverno lo sapeva. Non lo sapevano tre cose intorno:

  la mediana di ripiego era quella di tutto l'anno;
  la curva disegnava il "se entra" anche con l'Ora al 10%;
  la curva non poteva alzare il vento grezzo piu' di tre volte, e sul Peler -
  dove i modelli leggono 3-4 nodi - si fermava a 10 mentre il modello diceva 14.

I numeri che hanno deciso le tre correzioni stanno nei commenti di
engine.clima_del_giorno, engine.vento_atteso e config.TETTO_FATTORE_CURVA.
Qui sta fermo il comportamento.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwstagione"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwstagione", ignore_errors=True)

from gardawind import config, engine, features as F, model as M, store
from gardawind.util import iso_utc, local_naive_to_utc

passati = 0


def ok(c, m):
    global passati
    passati += 1 if c else 0
    print(("PASS " if c else "FAIL ") + m)


store.init()
SPOT = "Torbole-Ora"
MIN_KN = config.SPOTS[SPOT]["min_kn"]

# ---- 1. il clima del giorno --------------------------------------------------
# Quattro anni finti con una stagione netta: d'estate l'Ora entra quasi sempre
# a 16 nodi, d'inverno quasi mai, e quando entra fa 12. Fuori regime 9 d'estate
# e 5 d'inverno.
bersagli = {}
g = dt.date(2022, 1, 1)
k = 0
while g < dt.date(2026, 1, 1):
    estate = 4 <= g.month <= 9
    entra = (k % 10 != 0) if estate else (k % 10 == 0)
    picco = (16.0 if estate else 12.0) if entra else (9.0 if estate else 5.0)
    bersagli[g.isoformat()] = (picco, entra, None, None)
    g += dt.timedelta(days=1)
    k += 1
engine._targets = lambda spot_name, use_cache=True: bersagli

lug = engine.clima_del_giorno(SPOT, "2026-07-10")
dic = engine.clima_del_giorno(SPOT, "2026-12-20")
ok(lug["stagione"] and dic["stagione"], "con quattro anni di giornate la stagione c'e'")
ok(lug["se_entra"] == 16.0 and dic["se_entra"] == 12.0,
   "la mediana del picco e' quella della stagione: 16 a luglio, 12 a dicembre")
ok(lug["se_non_entra"] == 9.0 and dic["se_non_entra"] == 5.0,
   "e cosi' quanto tira quando il regime NON entra: 9 e 5")
ok(lug["frequenza"] > 0.85 and dic["frequenza"] < 0.15,
   "la frequenza e' quella della stagione (%.2f a luglio, %.2f a dicembre)"
   % (lug["frequenza"], dic["frequenza"]))
# Il giro dell'anno: il 5 gennaio e' vicino al 20 dicembre, non lontano 350 giorni.
gen = engine.clima_del_giorno(SPOT, "2026-01-05")
ok(gen["se_entra"] == 12.0 and gen["n"] > 300,
   "dicembre e gennaio sono vicini: la finestra gira intorno a capodanno (n=%d)" % gen["n"])
# Solo il passato: una giornata futura non puo' entrare nella sua stessa mediana.
bersagli["2026-07-10"] = (99.0, True, None, None)
ok(engine.clima_del_giorno(SPOT, "2026-07-10")["se_entra"] == 16.0,
   "la giornata stessa non entra nella sua mediana")
del bersagli["2026-07-10"]

# Poca storia nella stagione: si torna a tutto l'anno, e lo si dice.
pochi = {d: v for d, v in bersagli.items() if d[5:7] in ("06", "07", "08")}
pochi.update({"2025-12-%02d" % i: (12.0, True, None, None) for i in range(1, 6)})
engine._targets = lambda spot_name, use_cache=True: pochi
scarso = engine.clima_del_giorno(SPOT, "2026-12-20")
ok(scarso["stagione"] is False and scarso["se_entra"] == 16.0,
   "cinque giornate d'inverno non sono una stagione: mediana di tutto l'anno, dichiarata")
engine._targets = lambda spot_name, use_cache=True: {"2025-07-01": (16.0, True, None, None)}
ok(engine.clima_del_giorno(SPOT, "2026-07-10") is None,
   "e senza storia non si inventa niente")
engine._targets = lambda spot_name, use_cache=True: bersagli

# ---- 2. il vento atteso ------------------------------------------------------
ok(abs(engine.vento_atteso(0.10, 13.0, 5.0) - 5.8) < 1e-9,
   "Ora al 10%: la curva sta a 5,8 nodi, non ai 13 di un'Ora entrata")
ok(abs(engine.vento_atteso(0.90, 13.0, 5.0) - 12.2) < 1e-9,
   "Ora al 90%: 12,2, quasi tutto il \"se entra\"")
ok(engine.vento_atteso(1.0, 13.0, 5.0) == 13.0 and engine.vento_atteso(0.0, 13.0, 5.0) == 5.0,
   "ai due estremi e' uno dei due numeri")
ok(engine.vento_atteso(None, 13.0, 5.0) == 13.0 and engine.vento_atteso(0.5, 13.0, None) == 13.0,
   "senza probabilita' o senza il \"non entra\" resta il \"se entra\", com'era")
ok(engine.vento_atteso(0.5, None, 5.0) is None, "senza \"se entra\" non c'e' niente da pesare")
ok(engine.vento_atteso(0.2, 8.0, 10.0) == 8.0,
   "il \"non entra\" non puo' ALZARE la curva sopra il \"se entra\"")

# ---- 3. la mediana di ripiego in predict -------------------------------------
N = len(F.TIERS["bias"])
FEATS = {"tgrad": 3.0, "pgrad": -1.0, "rad_pre": 0.7, "cloud_win": 0.2,
         "along925": 3.0, "cross925": 1.0, "w10_win": 12.0, "w10_max": 14.0,
         "stab850": -12.0, "stab925": -5.0, "precip": 0.0, "breeze": 2.0,
         "dewdep": 7.0, "doy_sin": 0.3, "doy_cos": -0.9, "persist_obs": 14.0,
         "persist_age": 1.0, "raw_peak_hour": 15.0, "contesto_noto": 1.0}
RIDGE = {"intercept": 2.9, "coef": [0.0] * N, "features": list(F.TIERS["bias"]), "lam": 1.0}
bocciato = {"payload": {"tier": "bias", "intensity": RIDGE},
            "metrics": {"lead_band": "analisi", "usable": False,
                        "usable_occurrence": False, "base_rate": 0.4,
                        "clim_median": 15.7}}
p_anno = M.predict(SPOT, FEATS, bocciato, 0)
p_stag = M.predict(SPOT, FEATS, bocciato, 0, clim_stagione=13.0)
ok(p_anno["speed"] == 15.7 and p_anno["source_int"] == "climatologia",
   "senza stagione il ripiego e' la mediana di tutto l'anno, com'era (15,7)")
ok(p_stag["speed"] == 13.0 and p_stag["source_int"] == "climatologia",
   "con la stagione e' quella della stagione (13,0), e si chiama sempre climatologia")
ok(M.predict(SPOT, FEATS, bocciato, 0, clim_stagione=8.0)["speed"] == MIN_KN,
   "mai sotto la soglia del regime: \"se entra\" vuol dire almeno %g nodi" % MIN_KN)
promosso = {"payload": {"tier": "bias", "intensity": RIDGE},
            "metrics": {"lead_band": "analisi", "usable": True, "clim_median": 15.7}}
ok(M.predict(SPOT, FEATS, promosso, 0, clim_stagione=13.0)["source_int"] == "appreso",
   "un modello promosso non viene toccato dalla stagione: decide lui")

# ---- 4. la curva: livello atteso, e il tetto a sei ---------------------------
GIORNO = "2026-11-20"
H0, H1 = config.SPOTS["Torbole-Peler"]["window"]


def ore_finte(grezzo):
    ore = {}
    for h in range(0, 24):
        t = local_naive_to_utc(dt.datetime.fromisoformat(GIORNO) + dt.timedelta(hours=h))
        ore[iso_utc(t)] = {"w10": grezzo, "d10": 10.0, "t2m": 8.0, "cloud": 0.2, "precip": 0.0}
    return ore


def picco(grezzo, sessione):
    engine.ensemble_hours = lambda spot_name: (ore_finte(grezzo), {}, 3, "finto")
    prof = engine.day_profile("Torbole", GIORNO, {"Torbole-Peler": sessione})
    return max(x["wind"] for x in prof if H0 <= x["hour"] <= H1)


engine.analogs.promoted = lambda: False
ok(config.TETTO_FATTORE_CURVA == 6.0, "il tetto dichiarato e' 6")
ok(abs(picco(3.5, {"speed": 14.0, "peak_hour": None, "lead": 0}) - 14.0) < 0.05,
   "grezzo 3,5 e modello 14: la curva arriva a 14 (prima si fermava a 10,5)")
ok(abs(picco(1.0, {"speed": 14.0, "peak_hour": None, "lead": 0}) - 6.0) < 0.05,
   "grezzo 1: la curva si ferma a sei volte il grezzo, il tetto c'e' ancora")
ok(abs(picco(3.5, {"speed": 14.0, "speed_atteso": 7.0, "peak_hour": None, "lead": 0}) - 7.0) < 0.05,
   "con il livello atteso la curva segue quello (7), non il \"se entra\" (14)")
ok(abs(picco(3.5, {"speed": 14.0, "speed_atteso": None, "peak_hour": None, "lead": 0}) - 14.0) < 0.05,
   "e dove il livello atteso manca resta il \"se entra\"")
print("%d controlli sulla stagione" % passati)
