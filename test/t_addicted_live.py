"""Il canale vivo di Addicted: dieci minuti, tutte le centraline, una richiesta.

Gian, guardando la pagina: "sport addicted pubblica i dati in tempo reale ogni
10 minuti!". Aveva ragione, e noi leggevamo il canale orario - da cui la curva
del misurato di Campione e Malcesine ferma all'ora della costruzione.

Il corpo qui sotto e' quello VERO, scaricato il 19/09/2026 alle 10:22 locali,
ridotto ai campi che leggiamo. Le cose che difende:

  1. si legge "rec" (la finestra dichiarata) e non "live" (lo scatto di un
     minuto): due definizioni di "vento misurato" sulla stessa pagina sono il
     modo piu' sicuro di far leggere un numero per un altro;
  2. lo slug viene dal campo "fc" che il sito stesso pubblica, non da una
     tabella scritta a mano: la chiave della webcam di Malcesine e' "gardasee";
  3. una centralina che non misura non entra, e non diventa uno zero;
  4. la direzione qui E' misurata, e la prova sta nel confronto col campo del
     modello dentro la stessa risposta.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwaddlive"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwaddlive", ignore_errors=True)

from gardawind import config, engine, store
from gardawind.sources import addicted_live as AL
from gardawind.sources.http import FetchError
from gardawind.util import parse_dt_any

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


store.init()

# Il corpo vero, 19/09/2026 10:22 locali (08:22 UTC).
CORPO = (
    '{"ok":true,"now":1789806128,"interval":60,"cams":{'
    '"torbole":{"live":{"avg":4.3,"max":13,"dir":315,"temp":21.2,"wtemp":null,'
    '"age":0,"t":1789806120},"rec":{"avg":5.9,"max":16.2,"dir":8,"n":10,"min":10},'
    '"stale":false,"fc":"/forecast/gardasee/torbole/","compass":"NO","recdir":"N"},'
    '"malcesinenord":{"live":{"avg":6.5,"max":10.8,"dir":358,"temp":20.6,'
    '"wtemp":null,"age":0,"t":1789806120},"rec":{"avg":5.3,"max":11.9,"dir":358,'
    '"n":10,"min":10},"stale":false,"fc":"/forecast/gardasee/malcesinenord/",'
    '"compass":"N","recdir":"N"},'
    '"gardasee":{"live":{"avg":12.2,"max":19.1,"dir":337,"temp":20.7,'
    '"wtemp":null,"age":7,"t":1789805700},"rec":{"avg":12.8,"max":19.1,'
    '"dir":337,"n":3,"min":10},"stale":false,'
    '"fc":"/forecast/gardasee/malcesine/","compass":"NO","recdir":"NO"},'
    '"campione":{"live":{"avg":9.2,"max":11.9,"dir":23,"temp":22.2,"wtemp":null,'
    '"age":1,"t":1789806060},"rec":{"avg":9.3,"max":17.3,"dir":10,"n":10,"min":10},'
    '"stale":false,"fc":"/forecast/gardasee/campione/","compass":"NE",'
    '"recdir":"N"},'
    '"caporeamol":{"live":null,"rec":null,"stale":true,'
    '"fc":"/forecast/gardasee/caporeamol/","compass":"","recdir":""}}}'
)

chiamate = []


def finto(corpo):
    def _f(url, params=None, timeout=None, data=None, encoding="utf-8"):
        chiamate.append(url)
        return corpo
    return _f


AL.fetch_text = finto(CORPO)
letture, meta = AL.fetch()

# ---- 1. una richiesta, tutte le centraline ---------------------------------
ok(len(chiamate) == 1 and chiamate[0] == config.URL_ADDICTED_LIVE,
   "una sola richiesta, all'indirizzo che la pagina usa da se'")
ok(meta.get("interval_s") == 60,
   "e il sito dichiara ogni quanto lo rilegge: %s s" % meta.get("interval_s"))

# ---- 2. lo slug viene dal sito, non da una tabella -------------------------
ok("malcesine" in letture and "gardasee" not in letture,
   "la webcam \"gardasee\" E' Malcesine, e lo slug lo dice il campo fc (%s)"
   % sorted(letture))
ok(AL.slug_da_fc("/forecast/gardasee/malcesine/") == "malcesine"
   and AL.slug_da_fc(None) is None,
   "slug_da_fc prende l'ultimo pezzo dell'indirizzo, e niente da niente")
ok(set(letture) >= {"torbole", "malcesine", "campione"},
   "ci sono tutte le centraline che ci servono, in una lettura")

# ---- 3. si legge "rec", non "live" -----------------------------------------
c = letture["campione"]
ok(c["wind"] == 9.3 and c["gust"] == 17.3,
   "il vento e la raffica sono quelli di rec (9,3 e 17,3), non di live "
   "(9,2 e 11,9): la finestra dichiarata, non lo scatto del minuto")
ok(c["finestra_min"] == 10.0 and c["n_campioni"] == 10,
   "e viaggiano con la finestra e il numero di campioni che li ha fatti "
   "(%g min, %s campioni)" % (c["finestra_min"], c["n_campioni"]))
ok(letture["malcesine"]["n_campioni"] == 3,
   "a Malcesine la stessa finestra ne contiene 3: e' il dato a dirlo, non noi")

# ---- 4. l'istante e' quello della lettura ----------------------------------
ok(parse_dt_any(c["ts"]) == dt.datetime(2026, 9, 19, 8, 21, tzinfo=dt.timezone.utc),
   "l'istante e' quello della misura (live.t), non quello della richiesta: "
   "due letture nello stesso minuto scrivono la stessa riga (%s)" % c["ts"])
ok(parse_dt_any(letture["malcesine"]["ts"])
   < parse_dt_any(letture["torbole"]["ts"]),
   "e ogni centralina porta il suo, non uno comune: Malcesine e' di 7 minuti "
   "prima, e la pagina deve poterlo dire")

# ---- 5. chi non misura non entra, e non diventa zero -----------------------
ok("caporeamol" not in letture,
   "Capo Reamol non c'e': live e rec sono null e il sito dichiara stale")
ok(all(r["wind"] is not None for r in letture.values()),
   "nessuna lettura senza vento: un dato mancante non e' un dato a zero")

# ---- 6. la direzione e' MISURATA, e la prova e' nella stessa risposta -------
# Il campo del modello (la mappa animata delle correnti) dava 334-343 gradi a
# tutte e cinque le stazioni, un campo liscio; le misure dicono 8, 358, 337,
# 10. E Capo Reamol, che il modello prevede come le altre, non ha misura.
MODELLO = {"torbole": 334, "malcesinenord": 338, "malcesine": 338,
           "campione": 339, "caporeamol": 343}
scarti = {s: min(abs(letture[s]["dir"] - MODELLO[s]),
                 360 - abs(letture[s]["dir"] - MODELLO[s]))
          for s in letture}
ok(max(scarti.values()) > 25,
   "le direzioni misurate NON sono il campo del modello: scarto massimo %.0f "
   "gradi (%s)" % (max(scarti.values()), scarti))
ok(letture["campione"]["dir"] == 10.0 and letture["torbole"]["dir"] == 8.0,
   "e sono gradi, non punti cardinali")
ok(AL._dir(360) == 0.0 and AL._dir(0) == 0.0 and AL._dir(359.5) == 359.5,
   "il 360 del sito diventa 0: i gradi stanno in [0, 360)")
# Prima qui si chiedeva che 361 diventasse 1: il `% 360` normalizzava tutto,
# compresi i "nessun dato" che le centraline mandano come numeri. 999 diventava
# 279 gradi e -999 diventava 81 - e 81 gradi sta DENTRO il settore osservato del
# Peler, quindi un'ora di Ora mattutina finiva etichettata Peler per un valore
# che voleva dire "non lo so".
ok(AL._dir(361) is None and AL._dir(999) is None and AL._dir(-999) is None,
   "e un numero fuori da 0-360 non e' un angolo: e' un 'nessun dato', e resta None")

# ---- 7. una risposta rotta si ferma, non indovina --------------------------
for corpo, perche in (('{"ok":false}', "ok=false"),
                      ('{"ok":true}', "senza stazioni"),
                      ('{"ok":true,"cams":{}}', "stazioni vuote")):
    AL.fetch_text = finto(corpo)
    try:
        AL.fetch()
        ok(False, "una risposta %s deve fermare la lettura" % perche)
    except FetchError:
        ok(True, "una risposta %s ferma la lettura" % perche)
AL.fetch_text = finto("non sono json")
try:
    AL.fetch()
    ok(False, "un corpo non-JSON deve fermare la lettura")
except FetchError:
    ok(True, "un corpo non-JSON ferma la lettura")

# ---- 8. dentro il ciclo: campioni, e solo campioni -------------------------
AL.fetch_text = finto(CORPO)
righe = engine.leggi_addicted_vivo()
ok(len(righe) == 2,
   "le due centraline Addicted della pagina vengono salvate (%s)" % righe)
camp = list(store.connect().execute(
    "SELECT station, ts, wind_kn, gust_kn, dir_deg, source FROM obs_sample "
    "ORDER BY station"))
ok([r[0] for r in camp] == ["campione", "malcesine_add"],
   "con il nome delle NOSTRE stazioni, non con quello della webcam: %s"
   % [r[0] for r in camp])
ok(all(r[5] == "addicted-live" for r in camp),
   "e con la loro fonte dichiarata, distinta dalla serie oraria")
ok(all(r[4] is not None for r in camp),
   "la direzione misurata entra nei campioni")
ok(not list(store.connect().execute("SELECT 1 FROM obs_hour")),
   "obs_hour NON viene toccata: il bersaglio del modello non cambia "
   "definizione a meta' storia")
ok(not list(store.connect().execute(
    "SELECT 1 FROM obs_sample WHERE station='torbole_addicted'")),
   "e Torbole Addicted non entra: la sua pagina mostra Meteotrentino")

# Due giri nello stesso minuto: una riga, non due.
engine.leggi_addicted_vivo()
n = list(store.connect().execute("SELECT COUNT(*) FROM obs_sample"))[0][0]
ok(n == 2, "due letture dello stesso istante restano due righe in tutto (%d)" % n)

# La scala: il vento torna sulla scala Meteotrentino in lettura, la raffica no.
lette = {r["ts"]: r for r in store.samples_since("campione", "2026-01-01T00:00:00Z")}
r = list(lette.values())[0]
ok(r["wind_kn"] > 9.3 and abs(r["gust_kn"] - 17.3) < 0.01,
   "letto, il medio e' sulla scala di Torbole (%.1f da 9,3) e la raffica resta "
   "quella dello strumento (%.1f)" % (r["wind_kn"], r["gust_kn"]))

# ---- 9. quello che il sito dichiara guasto non si scrive come nuovo --------
FERMA = CORPO.replace('"fc":"/forecast/gardasee/campione/"',
                      '"fc":"/forecast/gardasee/campione/","stale":true')
AL.fetch_text = finto(FERMA)
letture2, _m = AL.fetch()
ok(letture2["campione"]["stale"] is True,
   "lo stale del sito arriva fino a noi")
store.connect().execute("DELETE FROM obs_sample")
store.connect().commit()
righe2 = engine.leggi_addicted_vivo()
ok(all("campione" not in r for r in righe2),
   "e una centralina che il sito dichiara ferma non viene salvata (%s)" % righe2)

# ---- 10. la curva: con questo canale diventa disegnabile -------------------
# E' il difetto che Gian ha visto: dieci minuti fanno una curva, un'ora no.
store.connect().execute("DELETE FROM obs_sample")
store.connect().commit()
base = dt.datetime(2026, 9, 19, 5, 0, tzinfo=dt.timezone.utc)
store.save_samples("campione", [
    ((base + dt.timedelta(minutes=10 * k)).strftime("%Y-%m-%dT%H:%M:%SZ"),
     9.0 + k * 0.2, 14.0 + k * 0.2, 200.0) for k in range(13)],
    AL.SOURCE)
fini = engine.campioni_fini("campione", "2026-09-19")
ok(len(fini) == 13,
   "tredici letture da dieci minuti sono una curva (%d punti su %g ore)"
   % (len(fini), fini[-1]["hour"] - fini[0]["hour"] if fini else 0))
print("%d controlli sul canale vivo Addicted" % passati)
