"""L'avviso "l'Ora e' arrivata": misura, una volta, e mai per fiducia.

Quattro promesse:
  1. si manda quando la mezz'ora sostenuta e' COMPLETA, non al primo colpo;
  2. il regime e' una direzione: vento forte da nord al pomeriggio non e' l'Ora;
  3. UNA volta per regime per giorno, anche se il processo gira ogni dieci
     minuti e il vento continua a soffiare;
  4. se Telegram non risponde, non si segna come mandato: si riprova al giro
     dopo. E senza token non si fa niente e non si esplode.
"""
import datetime as dt
import io
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwavvisi"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwavvisi", ignore_errors=True)
os.makedirs("/tmp/gwavvisi", exist_ok=True)

from gardawind import avvisi, config, orari, store
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
SPOT = "Torbole-Ora"
ST = config.SPOTS[SPOT]["station"]
ASSE = config.SPOTS[SPOT]["axis_obs"]
GIORNO = "2026-07-15"           # estate: la finestra utile dell'Ora e' larga


def campioni(fino_a_min, vento, direzione=ASSE, da_min=11 * 60):
    """Campioni ogni dieci minuti da `da_min` a `fino_a_min` (locali)."""
    righe = []
    m = da_min
    while m <= fino_a_min:
        naive = dt.datetime.fromisoformat(GIORNO + "T00:00:00") + dt.timedelta(minutes=m)
        righe.append((iso_utc(local_naive_to_utc(naive)),
                      vento(m) if callable(vento) else vento, 18.0, direzione))
        m += 10
    return righe


def salva(righe):
    store.save_samples(ST, righe, "prova")


def adesso_a(minuto):
    naive = dt.datetime.fromisoformat(GIORNO + "T00:00:00") + dt.timedelta(minutes=minuto)
    return local_naive_to_utc(naive)


inviati = []


class _Risposta(object):
    def __init__(self, corpo):
        self.corpo = corpo

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def telegram_finto(req, timeout=None):
    inviati.append(req.data.decode("utf-8"))
    return _Risposta(b'{"ok": true}')


def telegram_rotto(req, timeout=None):
    raise IOError("rete assente")


# ---- 1. Un colpo di vento non e' un ingresso ----
salva(campioni(12 * 60 + 10, lambda m: 14.0 if m == 12 * 60 else 5.0))
ok(avvisi.stato_regime(SPOT, GIORNO, adesso_a(12 * 60 + 10)) is None,
   "un campione sopra soglia non e' un ingresso")

# ---- 2. La mezz'ora sostenuta si': e l'orario e' quello dell'ingresso ----
salva(campioni(13 * 60, lambda m: 14.0 if m >= 12 * 60 + 20 else 5.0))
st = avvisi.stato_regime(SPOT, GIORNO, adesso_a(13 * 60))
ok(st is not None, "con la mezz'ora sostenuta l'Ora e' arrivata")
ok(st and 12 * 60 <= st["minuto"] <= 12 * 60 + 40,
   "e l'orario e' quello dell'ingresso, non quello di adesso (%s)"
   % (st and "%02d:%02d" % (st["minuto"] // 60, st["minuto"] % 60)))
ok(st and st["soglia"] == config.SPOTS[SPOT]["min_kn"],
   "con la soglia dello spot, non un numero scritto qui")
t = avvisi.testo(st)
ok("Ora è arrivata" in t and "Torbole" in t and "kn" in t,
   "e il messaggio dice la cosa giusta: %r" % t.replace("\n", " / "))

# ---- 3. Il regime e' una direzione ----
shutil.rmtree("/tmp/gwavvisi", ignore_errors=True)
os.makedirs("/tmp/gwavvisi")
store.close(); store.init()
salva(campioni(13 * 60, 16.0, direzione=(ASSE + 180.0) % 360.0))
ok(avvisi.stato_regime(SPOT, GIORNO, adesso_a(13 * 60)) is None,
   "sedici nodi da NORD nel pomeriggio non sono l'Ora, e non c'e' avviso")

# ---- 4. Una volta sola, e solo dopo l'invio riuscito ----
shutil.rmtree("/tmp/gwavvisi", ignore_errors=True)
os.makedirs("/tmp/gwavvisi")
store.close(); store.init()
salva(campioni(13 * 60, lambda m: 14.0 if m >= 12 * 60 + 20 else 5.0))
inviati[:] = []
righe = avvisi.esegui(token="", chat="", adesso=adesso_a(13 * 60))
ok(any("non configurati" in r for r in righe) and not inviati,
   "senza token non manda niente e lo dice, senza esplodere")
righe = avvisi.esegui(token="t", chat="@c", adesso=adesso_a(13 * 60),
                      opener=telegram_rotto)
ok(any("NON inviato" in r for r in righe) and not inviati,
   "se Telegram non risponde lo scrive nel log")
ok(not store.meta_get("avviso:%s:%s" % (SPOT, GIORNO)),
   "e NON segna come mandato: si riprova al giro dopo")
righe = avvisi.esegui(token="t", chat="@c", adesso=adesso_a(13 * 60 + 10),
                      opener=telegram_finto)
ok(len(inviati) == 1 and any("inviato" in r for r in righe),
   "al giro dopo, con la rete, manda: %s" % righe[:1])
ok("chat_id=%40c" in inviati[0] and "Ora" in inviati[0],
   "al canale giusto, con il testo")
salva(campioni(14 * 60, 15.0, da_min=13 * 60))
righe = avvisi.esegui(token="t", chat="@c", adesso=adesso_a(14 * 60),
                      opener=telegram_finto)
ok(len(inviati) == 1 and any("niente da dire" in r for r in righe),
   "un'ora dopo, col vento che continua, NON rimanda: una volta per giorno")

# ---- 5. Il giorno dopo si ricomincia ----
ok(not store.meta_get("avviso:%s:2026-07-16" % SPOT),
   "e il giorno dopo la chiave e' nuova, quindi si puo' rimandare")

# ---- 6. Nessun token nel repository ----
import re
radice = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sospetti = []
for cartella, _d, files in os.walk(os.path.join(radice, "gardawind")):
    for f in files:
        if f.endswith(".py"):
            testo = io.open(os.path.join(cartella, f), encoding="utf-8").read()
            if re.search(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", testo):
                sospetti.append(f)
ok(not sospetti, "nessun token Telegram scritto nel codice (%s)" % sospetti)
wf = io.open(os.path.join(radice, ".github", "workflows", "adesso.yml"),
             encoding="utf-8").read()
ok("secrets.TELEGRAM_BOT_TOKEN" in wf and "vars.TELEGRAM_CHAT" in wf,
   "il workflow prende il token dai segreti e il canale dalle variabili")

print("%d controlli avvisi" % passati)
