"""La raffica prevista e' il medio per un rapporto MISURATO, in un posto solo.

Gian: "la previsione delle raffiche e' molto lontana dal medio, si puo' fare
qualcosa?". Misurato: la raffica E' lontana dal medio (1,5-2 volte, e' il
lago), ma il rapporto che dava il modello ora per ora era rumore
(correlazione 0,03-0,23 con quello vero), il ripiego di 1,35 sottostimava di
4-6 nodi, e i sensori non misurano la stessa raffica (1,9 su Addicted, 1,45
su Meteotrentino nello stesso posto).

Quattro cose da difendere:

  1. il rapporto si impara dalla centralina che la pagina MOSTRA, nelle ore
     del regime, a scalini di vento; e uno scalino con poche ore non parla;
  2. senza ore si usa il predefinito, che e' una mediana misurata, e la
     pagina lo dice;
  3. il rapporto vive in un posto solo: ne' g10/w10 del modello ne' 1,35
     esistono piu' nel motore;
  4. la scheda scrive medio e raffica, non il range dell'ensemble.
"""
import datetime as dt
import inspect
import os
import re
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwraffica"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwraffica", ignore_errors=True)
os.makedirs("/tmp/gwraffica", exist_ok=True)

from gardawind import config, engine, store, web
from gardawind.util import iso_utc, local_naive_to_utc

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


store.init()
ORA, PELER = "Torbole-Ora", "Torbole-Peler"
ST = config.SPOTS[ORA]["station"]


def salva(giorno, ora, media, raffica):
    naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=ora)
    store.connect().execute(
        "INSERT OR REPLACE INTO obs_hour(station,hour,wind_mean,wind_max,"
        "gust_max,gust_rec,dir_deg,dir_const,n_samples) VALUES(?,?,?,?,?,?,?,?,?)",
        (ST, iso_utc(local_naive_to_utc(naive))[:13], media, media + 1, raffica,
         None, 190.0, 0.9, 6))


# ---- 2. senza ore: il predefinito, dichiarato ------------------------------
rel = engine.relazione_raffica(ORA)
ok(rel["scalini"] == {} and rel["ore"] == 0,
   "senza raffiche in archivio la centralina non ha insegnato niente")
ok(engine.rapporto_raffica(ORA, 14.0) == engine.RAFFICA_PREDEFINITO,
   "e si usa il predefinito %.1f" % engine.RAFFICA_PREDEFINITO)
ok(1.5 <= engine.RAFFICA_PREDEFINITO <= 1.9,
   "che e' una mediana misurata (1,5-2 sul lago), non il vecchio 1,35")
ok("non ha ancora abbastanza ore" in web.raffica_parole("Torbole"),
   "e il cassetto dei dettagli lo dice")

# ---- 1. si impara dalla centralina, nel regime, a scalini -------------------
# Venti giorni di Ora: fra 8 e 12 kn la raffica e' 1,8 volte il medio, fra 12
# e 16 e' 1,5 volte. Di mattina (Peler) invece 2,0 - e non deve contaminare.
for g in range(1, 21):
    giorno = "2026-07-%02d" % g
    for h in (13, 14, 15):
        salva(giorno, h, 10.0, 18.0)          # 8-12 kn: x1.8
        salva(giorno, h + 3, 14.0, 21.0)      # 12-16 kn: x1.5
    salva(giorno, 7, 10.0, 20.0)              # Peler: x2.0
engine.STATE.clear()
rel = engine.relazione_raffica(ORA)
ok(abs(rel["scalini"].get(8.0, 0) - 1.8) < 0.01
   and abs(rel["scalini"].get(12.0, 0) - 1.5) < 0.01,
   "l'Ora impara i suoi scalini dalla centralina: %s" % rel["scalini"])
ok(16.0 not in rel["scalini"] and 20.0 not in rel["scalini"],
   "e gli scalini senza ore non esistono, non si inventano")
ok(rel["ore"] == 120 and rel["fonte"] == ST,
   "sa quante ore ha imparato (%d) e da dove" % rel["ore"])
ok(abs(engine.relazione_raffica(PELER)["scalini"].get(8.0, 0) - 2.0) < 0.01,
   "e il Peler impara i suoi, separati: le sette del mattino non entrano nell'Ora")
ok(abs(engine.rapporto_raffica(ORA, 10.0) - 1.8) < 0.01
   and abs(engine.rapporto_raffica(ORA, 15.0) - 1.5) < 0.01,
   "al livello di vento il suo scalino")
ok(abs(engine.rapporto_raffica(ORA, 19.0) - 1.5) < 0.01,
   "sopra l'ultimo scalino imparato si tiene l'ultimo, non il predefinito")
ok(abs(engine.rapporto_raffica(ORA, 5.0) - 1.8) < 0.01,
   "sotto il primo si tiene il primo")

# Uno scalino con meno di RAFFICA_MIN_ORE ore non parla.
for g in range(1, engine.RAFFICA_MIN_ORE):
    salva("2026-08-%02d" % g, 14, 17.0, 30.0)
engine.STATE.clear()
ok(16.0 not in engine.relazione_raffica(ORA)["scalini"],
   "%d ore sole a 16-20 kn non bastano per uno scalino" % (engine.RAFFICA_MIN_ORE - 1))
salva("2026-08-%02d" % engine.RAFFICA_MIN_ORE, 14, 17.0, 30.0)
engine.STATE.clear()
ok(abs(engine.relazione_raffica(ORA)["scalini"].get(16.0, 0) - 30 / 17.0) < 0.01,
   "con %d ore si'" % engine.RAFFICA_MIN_ORE)
ok("Imparato qui" in web.raffica_parole("Torbole")
   and "1.80" in web.raffica_parole("Torbole"),
   "e il cassetto dei dettagli scrive i rapporti imparati")

# Un rapporto assurdo viene limitato, non creduto.
for g in range(1, 15):
    salva("2026-09-%02d" % g, 14, 21.0, 90.0)
engine.STATE.clear()
ok(engine.relazione_raffica(ORA)["scalini"].get(20.0) == engine.RAFFICA_LIMITI[1],
   "un rapporto di 4,3 viene fermato al limite %.1f" % engine.RAFFICA_LIMITI[1])

# ---- 3. un posto solo -------------------------------------------------------
src = inspect.getsource(engine)
ok("1.35" not in src, "il 1,35 non esiste piu' nel motore")
ok(len(re.findall(r'g10"\)\s*\n?\s*.*w10', src)) == 0
   and src.count("rapporto_raffica(") >= 3,
   "e la raffica prevista passa da rapporto_raffica, ovunque")
ok(src.count("clamp(g / w") == 0,
   "nessuna copia residua del rapporto del modello")

# ---- 4. la scheda: medio e raffica, non il range dell'ensemble --------------
profilo = [{"hour": h, "wind": 14.0 if 13 <= h <= 17 else 6.0,
            "gust": 21.0 if 13 <= h <= 17 else 9.0, "lo": 1.0, "hi": 29.0,
            "dir": 190} for h in range(4, 21)]
num = web.sessione_numeri(ORA, profilo, "2026-07-10")
ok(num and "lo" not in num and "hi" not in num,
   "sessione_numeri non porta piu' il range dell'ensemble")
ok(num and abs(num["kn"] - 14.0) < 0.01 and abs(num["raffica"] - 21.0) < 0.01,
   "porta il medio (%.0f) e la raffica (%.0f) al picco" % (num["kn"], num["raffica"]))
sess = {ORA: {"prob": 0.7, "affidabilita": None}}
card = web.card_regime("Torbole", "ORA", "Ora", "pomeriggio", profilo, sess,
                       "2026-07-10")
ok("<b>14</b><small>medio</small>" in card and "<b>21</b><small>raffica</small>" in card,
   "la scheda scrive '14 medio 21 raffica'")
ok("1–29" not in card and "1–29" not in card,
   "e il '1-29' non c'e' piu'")
print("%d controlli sulla raffica prevista" % passati)
