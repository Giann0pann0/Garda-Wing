"""Gli archivi che non si riscaricano, e la previsione altrui.

Fino al 19/09/2026 ogni riga dell'archivio era ricostruibile: Meteotrentino
pubblica quattordici anni, Addicted pubblica il suo storico orario. Da quando
leggiamo il canale vivo non e' piu' cosi': i dieci minuti e la direzione
misurata esistono solo perche' li registriamo mentre passano, e lo stesso vale
per le curve che pubblichiamo noi.

E c'e' una cosa che buttavamo ogni giorno: la previsione di Addicted, che
viaggia nella stessa risposta della loro misura. Senza archiviarla, il
confronto con loro resta per sempre "non sappiamo a quale scadenza fosse
emessa" - e quel dubbio non si recupera a posteriori.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwaltrui"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwaltrui", ignore_errors=True)

from gardawind import store, web
from gardawind.sources import addicted
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

# La risposta vera ha misura e previsione nella stessa busta.
DATI = {
    "ok": True,
    "arch": ["2026/09/19/0500", "2026/09/19/0600", "2026/09/20/1400"],
    "mavg": [8.0, 9.0, None],          # domani non e' misurato
    "mmax": [12.0, 14.0, None],
    "avg": [7.0, 8.5, 11.0],           # la LORO previsione, anche per domani
    "lo": [5.0, 6.0, 8.0],
    "hi": [9.0, 11.0, 14.0],
}

# ---- 1. due serie, una busta ----------------------------------------------
mis = addicted.parse_json(DATI)
pre = addicted.parse_json_previsione(DATI)
ok(len(mis) == 2 and len(pre) == 3,
   "la misura si ferma dove finisce il misurato (2 ore), la previsione arriva "
   "a domani (3): sono due serie diverse nella stessa risposta")
ok(mis[0][0] == pre[0][0],
   "e le due serie usano lo stesso istante per la stessa ora (%s)" % mis[0][0])
atteso = iso_utc(local_naive_to_utc(dt.datetime(2026, 9, 19, 5, 0)))
ok(pre[0][0] == atteso,
   "l'istante viene dalla chiave 'arch', che e' ora locale, e finisce in UTC")
ok(pre[0][1] == 7.0 and pre[0][2] == 5.0 and pre[0][3] == 9.0,
   "la previsione porta con se' la sua banda (lo/hi)")
ok(addicted.parse_json_previsione({"ok": True, "arch": [], "avg": []}) == [],
   "e senza serie prevista non si inventa niente")

# ---- 2. archiviata con QUANDO l'abbiamo letta ------------------------------
letto = "2026-09-19T05:10:00Z"
n = store.save_fc_altrui("addicted-sports", "torbole_addicted", pre, letto_a=letto)
ok(n == 3, "le tre ore previste entrano in archivio (%s)" % n)
righe = list(store.connect().execute(
    "SELECT letto_il, letto_a, valid_hour, wind_kn, lo_kn, hi_kn FROM fc_altrui "
    "ORDER BY valid_hour"))
ok(righe[0][0] == "2026-09-19" and righe[0][1] == letto,
   "con il giorno di lettura e l'istante esatto: da li' la scadenza e' una "
   "sottrazione (%s, %s)" % (righe[0][0], righe[0][1]))
ok(righe[-1][2][:10] == "2026-09-20",
   "e c'e' anche l'ora di domani: e' quella che rende il confronto a scadenza "
   "possibile")

# La seconda lettura dello stesso giorno NON sovrascrive: l'ora di emissione
# deve restare confrontabile da un giorno all'altro.
dopo = [(pre[0][0], 99.0, None, None)]
store.save_fc_altrui("addicted-sports", "torbole_addicted", dopo,
                     letto_a="2026-09-19T17:00:00Z")
v = store.connect().execute(
    "SELECT wind_kn, letto_a FROM fc_altrui WHERE valid_hour=?",
    (pre[0][0],)).fetchone()
ok(v[0] == 7.0 and v[1] == letto,
   "vince la PRIMA lettura del giorno, non l'ultima: %s kn letti alle %s"
   % (v[0], v[1][11:16]))
# Il giorno dopo, invece, e' una lettura nuova.
store.save_fc_altrui("addicted-sports", "torbole_addicted", dopo,
                     letto_a="2026-09-20T05:10:00Z")
n_giorni = store.connect().execute(
    "SELECT COUNT(DISTINCT letto_il) FROM fc_altrui").fetchone()[0]
ok(n_giorni == 2, "e ogni giorno aggiunge la sua lettura (%d giorni)" % n_giorni)

# ---- 3. la diagnostica dice cosa non si riscarica --------------------------
conta = store.conta_archivi()
ok("previsione altrui archiviata" in conta
   and conta["previsione altrui archiviata"]["n"] == 4,
   "il conteggio degli archivi irripetibili vede la previsione altrui: %s"
   % conta.get("previsione altrui archiviata"))
ok(conta["curve che abbiamo pubblicato"]["n"] == 0,
   "e dichiara VUOTO quello che e' vuoto, invece di tacere")
pagina = web.page_diagnostics()
ok("Quello che non si riscarica" in pagina and "vuoto" in pagina,
   "e la pagina lo mostra, con la riga vuota evidenziata")
store.save_issued_profile("Torbole", "2026-09-19T05:00:00Z",
                          [{"key": "2026-09-19T13:00:00Z", "wind": 14.0, "gust": 20.0}])
ok(store.conta_archivi()["curve che abbiamo pubblicato"]["n"] == 1,
   "appena si archivia una curva pubblicata, il conto la vede")

# ---- 4. i dieci minuti e la direzione, contati a parte ---------------------
store.save_samples("campione", [("2026-09-19T08:20:00Z", 9.3, 17.3, 10.0)],
                   "addicted-live")
store.save_samples("campione", [("2026-09-19T08:30:00Z", 9.5, 17.0, None)],
                   "addicted-live")
c = store.conta_archivi()
ok(c["campioni a 10 minuti (canale vivo)"]["n"] == 2
   and c["direzione misurata, stesse letture"]["n"] == 1,
   "i campioni del canale vivo e quelli CON direzione si contano separati "
   "(%d e %d): la direzione e' la cosa nuova, e va vista crescere"
   % (c["campioni a 10 minuti (canale vivo)"]["n"],
      c["direzione misurata, stesse letture"]["n"]))
print("%d controlli sugli archivi irripetibili" % passati)
