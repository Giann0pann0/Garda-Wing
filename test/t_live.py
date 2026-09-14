"""Il dato osservato separato dalla previsione: live.json.

Quattro cose da difendere, e sono tutte cose che nella versione precedente
andavano storte in silenzio:

  1. live.json contiene l'ORARIO del campione, non la sua eta'. L'eta' e' una
     sottrazione e va fatta quando si guarda: scriverla nel file significa
     congelarla, ed e' il motivo per cui la pagina diceva "adesso" cinque ore
     dopo.
  2. la raffica ricorrente esce solo alla sua finestra dichiarata di 30
     minuti. Dove la cadenza non la sostiene, il campo e' None e lo stato
     dice perche': "non stimabile" non e' zero.
  3. la cadenza che conta per la raffica e' quella dei campioni CON la
     raffica. Vento ogni 10 minuti e raffica ogni 30 non sostengono una
     finestra da 30, anche se la cadenza generale direbbe di si'.
  4. il file si scrive in modo atomico: chi lo sta leggendo non trova mai
     mezzo file.
"""
import datetime as dt
import io
import json
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwlive"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwlive", ignore_errors=True)

from gardawind import config, live, store
from gardawind.util import iso_utc

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc

store.init()
ADESSO = dt.datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
ST = config.SPOTS["Torbole-Ora"]["station"]


def scrivi_campioni(station, campioni, fonte="t_live"):
    store.save_samples(station, campioni, fonte)


# --------------------------------------------------------------------------
# 1. Nessun campione: si dice, non si inventa
# --------------------------------------------------------------------------
v = live.stazione(ST, adesso=ADESSO)
ok(v["ts"] is None and v["wind"] is None and v["gust_rec"] is None,
   "senza campioni tutto None, nessuno zero")
ok(v["gust_rec_stato"] == "no_data", "e lo stato lo dice: %s" % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 2. Cadenza 10 minuti, raffica presente: la ricorrente esce
# --------------------------------------------------------------------------
camp = []
for k in range(12, 0, -1):                  # ultimi due ore, ogni 10 minuti
    t = ADESSO - dt.timedelta(minutes=10 * k)
    # raffiche 20, 21, 22 che tornano: la ricorrente deve stare fra loro,
    # non sul massimo.
    raffica = [20.0, 21.0, 22.0][k % 3]
    camp.append((iso_utc(t), 14.0, raffica, 191.0))
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["wind"] == 14.0 and v["dir"] == 191.0, "l'ultimo campione e' quello piu' recente")
ok(v["ts"] == iso_utc(ADESSO - dt.timedelta(minutes=10)),
   "e il suo orario e' scritto nel file (%s)" % v["ts"])
ok("age" not in v and "eta" not in v,
   "nel file non c'e' nessuna eta': la calcola chi guarda")
ok(v["cadenza_min"] == 10.0, "cadenza dedotta dai dati: %s" % v["cadenza_min"])
ok(v["gust_rec"] is not None and 20.0 <= v["gust_rec"] <= 22.0,
   "la ricorrente sta dentro le raffiche che tornano (%s)" % v["gust_rec"])
ok(v["gust_rec"] < 22.0 or v["gust"] == 22.0,
   "e non e' automaticamente il massimo")
ok(v["gust_rec_stato"] == "ok" and v["gust_rec_finestra_min"] == 30.0,
   "la finestra dichiarata e' 30 minuti, sempre la stessa")

# --------------------------------------------------------------------------
# 3. Vento ogni 10 minuti, raffica ogni 30: la finestra non si sostiene
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive2", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive2"
store.close()
store.init()
camp = []
for k in range(12, 0, -1):
    t = ADESSO - dt.timedelta(minutes=10 * k)
    raffica = 21.0 if (k % 3 == 0) else None
    camp.append((iso_utc(t), 14.0, raffica, 191.0))
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["cadenza_min"] == 10.0, "la cadenza generale resta 10 minuti")
ok(v["cadenza_raffica_min"] == 30.0,
   "ma quella della raffica e' 30 (%s)" % v["cadenza_raffica_min"])
ok(v["gust_rec"] is None and "cadenza troppo rada" in v["gust_rec_stato"],
   "quindi la ricorrente a 30' non e' stimabile, e non viene allargata: %s"
   % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 4. Solo vento, nessuna raffica: si dichiara, non si finge
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive3", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive3"
store.close()
store.init()
camp = [(iso_utc(ADESSO - dt.timedelta(minutes=10 * k)), 15.0, None, 191.0)
        for k in range(12, 0, -1)]
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["wind"] == 15.0 and v["gust"] is None and v["gust_rec"] is None,
   "vento si', raffica no")
ok(v["gust_rec_stato"] == "raffica assente",
   "e lo stato distingue 'assente' da 'non stimabile': %s" % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 5. Un dato vecchio resta vecchio: il file non lo maschera
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive4", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive4"
store.close()
store.init()
vecchio = ADESSO - dt.timedelta(hours=5)
scrivi_campioni(ST, [(iso_utc(vecchio - dt.timedelta(minutes=10 * k)),
                      12.0, 18.0, 191.0) for k in range(6, 0, -1)])
v = live.stazione(ST, adesso=ADESSO)
ok(v["ts"] == iso_utc(vecchio - dt.timedelta(minutes=10)),
   "l'orario e' quello vero, di cinque ore fa")
ok(v["gust_rec"] is not None,
   "la ricorrente si calcola comunque: e' il dato che e' vecchio, non sbagliato")

# --------------------------------------------------------------------------
# 6. snapshot e scrittura atomica
# --------------------------------------------------------------------------
snap = live.snapshot(adesso=ADESSO)
ok(set(snap["luoghi"]) == set(config.PLACES),
   "snapshot: un luogo per ciascuno di %s" % ", ".join(config.PLACES))
ok(snap["generato"] == iso_utc(ADESSO),
   "snapshot: 'generato' e' quando si scrive, ed e' un'altra cosa dall'eta' del dato")
ok(all("station" in v for v in snap["luoghi"].values()),
   "snapshot: ogni luogo dichiara da quale centralina viene")

percorso = "/tmp/gwlive4/live.json"
live.scrivi(percorso, adesso=ADESSO)
ok(os.path.exists(percorso) and not os.path.exists(percorso + ".tmp"),
   "scrivi: il file c'e' e il temporaneo e' sparito")
letto = json.load(io.open(percorso, encoding="utf-8"))
ok(letto["luoghi"]["Torbole"]["ts"] == v["ts"],
   "scrivi: quello che si rilegge e' quello che si e' misurato")
ok(json.dumps(letto) and "age_min" not in json.dumps(letto),
   "scrivi: nel JSON non finisce nessuna eta' precalcolata")

# Riscrivere sopra un file esistente non lascia residui.
live.scrivi(percorso, adesso=ADESSO + dt.timedelta(minutes=1))
letto2 = json.load(io.open(percorso, encoding="utf-8"))
ok(letto2["generato"] != letto["generato"] and not os.path.exists(percorso + ".tmp"),
   "scrivi: la seconda scrittura sostituisce, e resta un file solo")
