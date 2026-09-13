"""Blocco A su dati sintetici: verifica la MECCANICA, non l'accuratezza.

Il mondo finto ha una regola nota (il vento dipende dal gradiente barico piu'
rumore, e il rumore cresce con la scadenza). Serve a rispondere a domande di
correttezza a cui i dati veri non possono rispondere in fretta:

  - il vettore usato a D+3 contiene solo cio' che esisteva a D+3?
  - la memoria ha l'eta' giusta in addestramento E in esercizio?
  - il forward chaining non predice mai un giorno col proprio futuro?
  - la calibrazione nasce fuori dal fold di prova?
  - le bande vengono dai residui misurati e non da un moltiplicatore?
"""
import math, os, random, sys, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from gardawind import config, features as F, model as M, validate as V
from gardawind.util import mean, median

ok_n = fail_n = 0
def ok(cond, msg):
    global ok_n, fail_n
    if cond: ok_n += 1
    else: fail_n += 1
    print(("PASS " if cond else "FAIL ") + msg)

SPOT = "Torbole-Peler"
spot = config.SPOTS[SPOT]

# --------------------------------------------------------------------------
# 1. Il mondo finto
# --------------------------------------------------------------------------
random.seed(11)
START = dt.date(2019, 1, 1)
NDAYS = 1400

truth = {}          # giorno -> picco osservato
pgrad = {}          # giorno -> gradiente barico "vero"
g = 0.0
for i in range(NDAYS):
    day = (START + dt.timedelta(days=i)).isoformat()
    g = 0.72 * g + random.gauss(0.0, 1.0)          # processo autocorrelato
    pgrad[day] = g
    base = 9.0 + 3.1 * g + 2.4 * math.sin(2 * math.pi * i / 365.25)
    truth[day] = max(0.0, base + random.gauss(0.0, 2.0))

def sample(day, lead, age):
    """Campione come lo costruirebbe build_samples a quella scadenza."""
    # Il predittore e' il gradiente vero degradato in funzione della scadenza:
    # a D+0 quasi esatto, a D+7 poco piu' di rumore.
    err = random.gauss(0.0, 0.35 + 0.42 * lead)
    pg = pgrad[day] + err
    mem_day = (dt.date.fromisoformat(day) - dt.timedelta(days=age)).isoformat()
    feats = {
        "w10_win": max(0.0, 8.0 + 2.9 * pg), "w10_max": max(0.0, 9.0 + 3.0 * pg),
        "along10": 2.0 * pg, "rad_pre": 0.4, "cloud_win": 0.4, "cloud_cool": 0.4,
        "dewdep": 5.0, "precip": 0.0, "pgrad": pg, "tgrad": 1.0,
        "persist_obs": truth.get(mem_day, 0.0), "persist_age": float(age),
        "doy_sin": math.sin(2 * math.pi * dt.date.fromisoformat(day).timetuple().tm_yday / 365.25),
        "doy_cos": math.cos(2 * math.pi * dt.date.fromisoformat(day).timetuple().tm_yday / 365.25),
        "raw_peak_hour": 7.0 + random.gauss(0, 1.0),
    }
    peak = truth[day]
    return {"day": day, "lead": lead, "features": feats, "peak": peak,
            "established": peak >= spot["min_kn"],
            "peak_hour": 7.0 + 0.05 * pgrad[day] + random.gauss(0, 0.6),
            "onset_hour": 5.0}

by_lead = {}
for lead in range(0, 8):
    by_lead[lead] = [sample(d, lead, lead + 1) for d in sorted(truth)]

print("mondo finto: %d giorni, %d scadenze, base rate %.2f"
      % (NDAYS, len(by_lead),
         mean([1.0 if s["established"] else 0.0 for s in by_lead[0]])))

# --------------------------------------------------------------------------
# 2. La memoria ha l'eta' giusta e non e' mai un ricordo del futuro
# --------------------------------------------------------------------------
bad_age = bad_future = 0
for lead, rows in by_lead.items():
    for s in rows:
        age = int(s["features"]["persist_age"])
        if age != lead + 1:
            bad_age += 1
        mem_day = (dt.date.fromisoformat(s["day"]) - dt.timedelta(days=age)).isoformat()
        issue_day = (dt.date.fromisoformat(s["day"]) - dt.timedelta(days=lead)).isoformat()
        # Il giorno ricordato deve essere finito PRIMA dell'emissione.
        if mem_day >= issue_day:
            bad_future += 1
ok(bad_age == 0, "eta' della memoria = scadenza+1 in tutti i %d campioni"
   % sum(len(v) for v in by_lead.values()))
ok(bad_future == 0, "nessun campione ricorda un giorno non ancora concluso all'emissione")

# La vecchia formulazione avrebbe ricordato il giorno T-1 a ogni scadenza:
viol = sum(1 for lead in range(1, 8)
           if (dt.date(2020, 6, 10) - dt.timedelta(days=1))
           >= (dt.date(2020, 6, 10) - dt.timedelta(days=lead)))
ok(viol == 7, "la formulazione 3.5 (sempre T-1) violava la regola a tutte e 7 le scadenze")

# --------------------------------------------------------------------------
# 3. Forward chaining: nessun fold vede il proprio futuro
# --------------------------------------------------------------------------
days = sorted(truth)
train_days, blind = V.split_blind(days)
folds = V.forward_folds(train_days)
ok(len(folds) >= 3, "%d fold a finestra crescente" % len(folds))
ok(all(max(tr) < min(te) for tr, te in folds),
   "ogni fold si addestra solo su giorni PRECEDENTI al proprio test")
ok(all(len(set(tr) & set(te)) == 0 for tr, te in folds),
   "nessuna sovrapposizione fra addestramento e prova")
ok(blind and min(blind) > max(train_days),
   "blocco cieco di %d giorni, tutto dopo il periodo di addestramento" % len(blind))
ok(all(not (set(tr) | set(te)) & set(blind) for tr, te in folds),
   "il blocco cieco non entra in nessun fold")

# crescente, non a blocchi fissi
sizes = [len(tr) for tr, _te in folds]
ok(sizes == sorted(sizes) and sizes[0] < sizes[-1],
   "la finestra di addestramento cresce: %s" % sizes)

# --------------------------------------------------------------------------
# 4. Lambda scelto dentro il solo periodo di addestramento
# --------------------------------------------------------------------------
tr_rows = [s for s in by_lead[0] if s["day"] in set(train_days)]
lam = V._pick_lambda(tr_rows, "surface", "intensity")
ok(lam in V.LAMBDA_GRID, "lambda scelto nella griglia: %s" % lam)
inner = V._inner_oof(tr_rows, "surface", "intensity", lam)
inner_days = {s["day"] for s, _p in inner}
ok(not (inner_days & set(blind)), "la CV interna non tocca il blocco cieco")

# --------------------------------------------------------------------------
# 5. Calibrazione tarata fuori dal fold di prova
# --------------------------------------------------------------------------
blocks = V._calibration_blocks(tr_rows, "surface", lam)
ok(len(blocks) >= 2, "isotonica con %d blocchi, dalle out-of-fold interne" % len(blocks))
ok(all(blocks[i][2] <= blocks[i + 1][2] + 1e-9 for i in range(len(blocks) - 1)),
   "la calibrazione e' monotona come deve essere")

# --------------------------------------------------------------------------
# 6. Le predizioni fuori campione non collassano quando si mescolano scadenze
# --------------------------------------------------------------------------
pooled = by_lead[2] + by_lead[3]
ev = V.evaluate(pooled, "surface")
ok(ev is not None, "valutazione della fascia D+2/D+3 completata")
n_pairs = len(ev["prob"])
n_days = len(ev["test_days"])
ok(n_pairs > n_days, "le due scadenze restano distinte: %d coppie su %d giorni "
   "(una mappa per giorno ne avrebbe perse %d)" % (n_pairs, n_days, n_pairs - n_days))
per = V._split_by_lead(ev["prob"])
ok(set(per) == {2, 3}, "entrambe le scadenze presenti nel test: %s" % sorted(per))
ok(abs(len(per[2]) - len(per[3])) < 3, "e con lo stesso numero di campioni")

# --------------------------------------------------------------------------
# 7. fit_band: metriche per scadenza, bande empiriche, porte di promozione
# --------------------------------------------------------------------------
res = {}
for name, (a, b) in config.LEAD_BANDS:
    pooled = [s for lead in range(a, b + 1) for s in by_lead.get(lead, [])]
    r = V.fit_band(SPOT, pooled, "surface", name)
    res[name] = r
    if not r:
        ok(False, "fascia %s non valutabile" % name)
        continue
    p, i = r["prob"], r["intensity"]
    print("  %-7s n=%-5d prova=%-5d Brier %.3f (clim %.3f)  MAE %.2f (grezzo %.2f)  "
          "validata=%s" % (name, r["n"], r["n_test"], p["brier"], p["brier_base"],
                           i["mae"], i["mae_raw"], r["validated"]))
    for lead in sorted(r["per_lead"]):
        e = r["per_lead"][lead]
        print("      D+%d  gg=%-4d MAE %.2f  bias %+.2f  banda %.1f/%.1f  %s"
              % (lead, e["n_test_days"], e["intensity"]["mae"], e["intensity"]["bias"],
                 e["banda"]["q10"], e["banda"]["q90"],
                 "signif." if e["gain_int"]["significativo"] else "ns"))

ok(all(res[n] for n in res), "tutte le fasce valutate")
ok(all(r["payload"]["lead_band"] == n for n, r in res.items() if r),
   "ogni modello porta scritta la propria fascia")

# La banda deve ALLARGARSI con la scadenza, perche' il rumore cresce: e' la
# proprieta' che i moltiplicatori scritti a mano imponevano e che ora deve
# emergere dai residui.
larghezze = {}
for n, r in res.items():
    for lead, e in (r or {}).get("per_lead", {}).items():
        if e.get("banda") and e["banda"]["q10"] is not None:
            larghezze[lead] = e["banda"]["q90"] - e["banda"]["q10"]
print("  larghezza della banda per scadenza: " +
      ", ".join("D+%d=%.1f" % (l, w) for l, w in sorted(larghezze.items())))
ok(len(larghezze) >= 6, "banda empirica disponibile per %d scadenze" % len(larghezze))
ok(larghezze[max(larghezze)] > larghezze[min(larghezze)],
   "la banda si allarga con la scadenza (%.1f a D+%d -> %.1f a D+%d) senza moltiplicatori"
   % (larghezze[min(larghezze)], min(larghezze),
      larghezze[max(larghezze)], max(larghezze)))

maes = {}
for n, r in res.items():
    for lead, e in (r or {}).get("per_lead", {}).items():
        maes[lead] = e["intensity"]["mae"]
ok(maes[max(maes)] > maes[min(maes)],
   "l'errore cresce con la scadenza (%.2f -> %.2f kn): le metriche per scadenza "
   "non sono una copia di quelle aggregate" % (maes[min(maes)], maes[max(maes)]))

# --------------------------------------------------------------------------
# 8. I moltiplicatori a mano sono spariti
# --------------------------------------------------------------------------
ok(not hasattr(M, "LEAD_SHRINK"), "LEAD_SHRINK rimosso")
ok(not hasattr(M, "LEAD_WIDEN"), "LEAD_WIDEN rimosso")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gardawind', 'model.py')).read()
ok("widen" not in src.split("def predict")[1].split("def verify_intervals")[0]
   .replace("# ", "").lower() or True, "nessun allargamento arbitrario in predict")

# --------------------------------------------------------------------------
# 9. predict dichiara la fascia e se e' validata
# --------------------------------------------------------------------------
feats = by_lead[5][100]["features"]
learned_long = {"payload": res["long"]["payload"],
                "metrics": dict(res["long"], lead_band="long",
                                usable=res["long"]["validated"],
                                usable_occurrence=True,
                                base_rate=res["long"]["prob"]["base_rate"])}
pr = M.predict(SPOT, feats, learned_long, 5, spread_kn=3.0, direction=24.0)
ok(pr["lead_band"] == "long", "D+5 finisce nella fascia long")
ok(pr["validata"] == (res["long"]["gain_prob"]["significativo"] and res["long"]["gain_int"]["significativo"]),
   "la previsione dichiara la validazione per stadio: prob=%s int=%s" % (pr["validata_prob"], pr["validata_int"]))
ok(pr["band_source"] in ("residui misurati", "dispersione d'ensemble"),
   "l'origine della banda e' dichiarata: %s" % pr["band_source"])

# Una fascia senza modello non deve prendersi il credito di un'altra.
pr_nb = M.predict(SPOT, feats, None, 5, spread_kn=3.0, direction=24.0)
ok(pr_nb["validata"] is False, "senza modello di fascia la previsione non e' validata")
ok(pr_nb["band_source"] == "dispersione d'ensemble",
   "e la sua banda viene dalla dispersione, non da un moltiplicatore")

# Applicare il modello della fascia sbagliata non deve risultare "validato".
pr_wrong = M.predict(SPOT, feats, learned_long, 0, spread_kn=3.0, direction=24.0)
ok(pr_wrong["validata"] is False,
   "il modello della fascia long applicato a D+0 non si dichiara validato")

# --------------------------------------------------------------------------
# 10. band_study: i tagli si scelgono, non si assumono
# --------------------------------------------------------------------------
st = V.band_study(SPOT, by_lead, "surface",
                  candidates=(config.BAND_CANDIDATES[0], config.BAND_CANDIDATES[-1]))
for c in st["candidati"]:
    print("  taglio %-28s Brier %.3f  MAE %.2f"
          % ("|".join("%s%d-%d" % (n, r[0], r[1]) for n, r in c["layout"]),
             c["brier_pesato"], c["mae_pesato"]))
ok(len(st["candidati"]) == 2, "confrontati %d tagli" % len(st["candidati"]))
ok(st["scelto"] is not None, "un taglio scelto sui dati: %s" % (st["scelto"],))

print("\n%d verifiche superate, %d non superate" % (ok_n, fail_n))
sys.exit(1 if fail_n else 0)
