"""La tabella dei ripieghi, attraversata tutta.

model.predict ha tre sorgenti per la probabilita', tre per l'intensita', due per
la banda e un freno sulla direzione: diciotto combinazioni dichiarabili. Il
20/09/2026 tre difetti dei numeri su quattro abitavano proprio qui, e nessuno di
loro ha fatto fallire un controllo - perche' i controlli guardavano un caso alla
volta e la scala dei ripieghi non era scritta da nessuna parte.

Questo file e' la tabella. Non prova che le scelte siano quelle giuste (quella e'
una decisione di prodotto, e sta scritta nella docstring di predict): prova che
il codice faccia ESATTAMENTE quello che la tabella dichiara, in ogni casella. E'
la rete che serve per poter semplificare quella funzione senza paura.
"""
import os
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
os.environ["GARDAWIND_HOME"] = "/tmp/gwripieghi"

from gardawind import config, model as M  # noqa: E402

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


SPOT = "Torbole-Ora"
ASSE = config.SPOTS[SPOT]["axis"]
MIN_KN = config.SPOTS[SPOT]["min_kn"]

# Feature qualunque ma complete: il prior fisico deve poter rispondere.
FEATS = {"tgrad": 3.0, "pgrad": -1.0, "rad_pre": 0.7, "cloud_win": 0.2,
         "along925": 3.0, "cross925": 1.0, "w10_win": 12.0, "w10_max": 14.0,
         "stab850": -12.0, "stab925": -5.0, "precip": 0.0, "breeze": 2.0,
         "dewdep": 7.0, "doy_sin": 0.3, "doy_cos": -0.9, "persist_obs": 14.0,
         "persist_age": 1.0, "raw_peak_hour": 15.0, "contesto_noto": 1.0}

# Un modello finto, con le manopole che contano. I payload sono nella forma vera
# (util.LogisticModel.to_dict / RidgeModel.to_dict) e con i coefficienti a zero:
# cosi' predict ci passa davvero, e il valore che esce e' l'intercetta, cioe' un
# numero che sappiamo in anticipo. TIER "bias" ha le sue feature: il vettore le
# prende da features.TIERS, quindi i coefficienti devono essere tanti quante loro.
from gardawind import features as F  # noqa: E402

N_BIAS = len(F.TIERS["bias"])
LOGISTICO = {"intercept": 0.4, "coef": [0.0] * N_BIAS,
             "features": list(F.TIERS["bias"]), "lam": 1.0}
RIDGE = {"intercept": 2.9, "coef": [0.0] * N_BIAS,
         "features": list(F.TIERS["bias"]), "lam": 1.0}


def modello(fascia, usable_occ, usable_int, clim=None, banda=True):
    return {
        "payload": {
            "tier": "bias",
            "occurrence": dict(LOGISTICO),
            "intensity": dict(RIDGE),
            "calibration": [[0.0, 1.0, 0.6]],
            "q10": -1.0 if banda else None,
            "q90": 3.0 if banda else None,
        },
        "metrics": {
            "lead_band": fascia,
            "usable": usable_int,
            "usable_occurrence": usable_occ,
            "base_rate": 0.42,
            "clim_median": clim,
        },
    }


def p(learned, lead=0, direction=None, spread=2.0):
    return M.predict(SPOT, FEATS, learned, lead, spread_kn=spread,
                     direction=direction if direction is not None else ASSE)


# ---- 1. la fascia: stessa, "analisi", un'altra ----------------------------
# config.band_for_lead: D+0 e' "short".
fascia0 = config.band_for_lead(0)
altra = next(b for b in ("medium", "long", "short") if b != fascia0)

r = p(modello(fascia0, True, True))
ok(r["source_prob"] == "appreso" and r["source_int"] == "appreso"
   and r["band_source"] == "residui misurati" and r["validata"],
   "fascia dichiarata = fascia chiesta: si usa, banda dai residui, validata")

r = p(modello("analisi", True, True), lead=0)
ok(r["source_int"] == "appreso" and r["band_source"] == "residui misurati"
   and r["validata"],
   "modello \"analisi\" a D+0: si usa e vale, perche' e' la scadenza su cui e' misurato")

r = p(modello("analisi", True, True), lead=3)
ok(r["source_int"] == "appreso" and r["band_source"] == "dispersione d'ensemble"
   and not r["validata"],
   "lo stesso modello a D+3: si usa, ma la banda non e' la sua e non si dice validata")

r = p(modello(altra, True, True), lead=0)
ok(r["source_int"] == "prior" and not r["validata"],
   "un modello che dichiara un'altra fascia non si usa: l'intensita' torna al prior")
ok(r["source_prob"] == "climatologia",
   "ma la frequenza climatologica osservata resta: e' un conteggio su questa "
   "centralina, non il modello, e non dipende dalla scadenza")

# ---- 2. la probabilita': tre sorgenti ------------------------------------
r = p(modello(fascia0, True, False, clim=None))
ok(r["source_prob"] == "appreso", "stadio A promosso -> probabilita' appresa")
r = p(modello(fascia0, False, False, clim=None))
ok(r["source_prob"] == "climatologia" and abs(r["prob"] - 0.42) < 1e-9,
   "stadio A non promosso -> frequenza climatologica osservata (%.2f)" % r["prob"])
senza_base = modello(fascia0, False, False)
senza_base["metrics"]["base_rate"] = None
r = p(senza_base)
ok(r["source_prob"] == "prior",
   "senza nemmeno la frequenza osservata -> prior fisico, dichiarato")

# ---- 3. l'intensita': tre sorgenti --------------------------------------
r = p(modello(fascia0, True, True))
ok(r["source_int"] == "appreso", "stadio B promosso -> intensita' appresa")
r = p(modello(fascia0, True, False, clim=16.0))
ok(r["source_int"] == "climatologia" and abs(r["speed"] - 16.0) < 1e-9,
   "stadio B non promosso ma con mediana climatologica -> quella (%.1f kn)" % r["speed"])
r = p(modello(fascia0, True, False, clim=None))
ok(r["source_int"] == "prior",
   "senza mediana climatologica -> prior fisico (e NON la climatologia di un'altra fascia)")
r = p(modello(fascia0, True, False, clim=MIN_KN - 5.0))
ok(r["speed"] >= MIN_KN,
   "e una stima condizionata al regime non scende sotto la soglia del regime "
   "(%.1f >= %.1f)" % (r["speed"], MIN_KN))

# ---- 4. la banda: residui o dispersione --------------------------------
r = p(modello(fascia0, True, True, banda=True))
# q10=-1, q90=+3 sui residui (previsto - osservato): la banda si SOTTRAE.
ok(abs(r["hi"] - (r["speed"] + 1.0)) < 1e-9
   and abs(r["lo"] - (r["speed"] - 3.0)) < 1e-9,
   "banda dai residui: si sottraggono scambiati (%.1f-%.1f attorno a %.1f)"
   % (r["lo"], r["hi"], r["speed"]))
r = p(modello(fascia0, True, True, banda=False), spread=2.0)
larga = r["hi"] - r["lo"]
ok(r["band_source"] == "dispersione d'ensemble" and larga > 8.0,
   "senza residui: banda dalla dispersione, e larga (%.1f kn)" % larga)
r2 = p(modello(fascia0, True, True, banda=False), spread=6.0)
ok((r2["hi"] - r2["lo"]) > larga,
   "e piu' i modelli litigano piu' si allarga (%.1f contro %.1f)"
   % (r2["hi"] - r2["lo"], larga))

# ---- 5. il freno sulla direzione ---------------------------------------
dentro = p(modello(fascia0, True, True), direction=ASSE)
fuori = p(modello(fascia0, True, True), direction=ASSE + 100.0)
ok(dentro["dir_penalty"] == 1.0 and dentro["source_prob"] == "appreso",
   "direzione dentro il settore: il freno non morde e non si dichiara niente")
ok(fuori["dir_penalty"] < 1.0 and fuori["prob"] < dentro["prob"],
   "direzione a cento gradi dall'asse: la probabilita' scende (%.2f -> %.2f)"
   % (dentro["prob"], fuori["prob"]))
ok(fuori["source_prob"] == "appreso-frenato" and fuori["source"] == "misto",
   "e il numero NON e' piu' quello verificato: lo dice la fonte (%s / %s)"
   % (fuori["source_prob"], fuori["source"]))

# ---- 6. la parola che arriva in pagina ---------------------------------
ok(p(modello(fascia0, True, True))["source"] == "appreso",
   "due stadi appresi -> \"appreso\"")
nudo = modello(altra, True, True)
nudo["metrics"]["base_rate"] = None
nudo["metrics"]["clim_median"] = None
ok(p(nudo)["source"] == "prior",
   "nessuna misura e nessun modello -> \"prior\" su tutta la linea")
ok(p(modello(fascia0, False, True))["source"] == "misto",
   "uno solo dei due -> \"misto\"")
ok(p(modello(fascia0, True, False, clim=16.0))["source"] == "misto",
   "e l'intensita' climatologica e' anch'essa un \"misto\", non un \"appreso\"")

# ---- 7. tutte le combinazioni rispondono, nessuna esplode --------------
casi = 0
for fascia in (fascia0, "analisi", altra, None):
    for uocc in (True, False):
        for uint in (True, False):
            for clim in (None, 16.0):
                for banda in (True, False):
                    for lead in (0, 3):
                        for dirz in (ASSE, ASSE + 100.0):
                            r = p(modello(fascia, uocc, uint, clim, banda),
                                  lead=lead, direction=dirz)
                            casi += 1
                            assert r["prob"] is not None and r["speed"] is not None
                            assert r["lo"] is not None and r["hi"] is not None
                            assert r["lo"] <= r["hi"]
                            assert r["source_prob"] in (
                                "appreso", "appreso-frenato", "climatologia", "prior")
                            assert r["source_int"] in (
                                "appreso", "climatologia", "prior")
                            assert r["band_source"] in (
                                "residui misurati", "dispersione d'ensemble")
ok(casi == 256,
   "tutte le %d combinazioni della tabella danno una previsione completa, con "
   "una fonte dichiarata per ogni pezzo" % casi)

print("%d controlli sulla tabella dei ripieghi" % passati)
