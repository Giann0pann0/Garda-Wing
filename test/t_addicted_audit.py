"""La sonda dell'archivio addicted, provata contro un server finto.

Il controllo che questo file esiste per difendere e' uno: un server che
IGNORA "from" e risponde sempre con la giornata di oggi. Se non lo si
verifica, la sonda conclude "ci sono anni di storico" mentre sta rileggendo
mille volte lo stesso giorno. E' l'errore piu' costoso possibile qui, perche'
non si vede: i dati ci sono, sono solo sempre gli stessi.

Il server finto simula cinque comportamenti veri, uno per stazione:

  torbole        storico vero fino a 40 giorni indietro, poi serie vuote;
  malcesine      lo stesso, perche' due stazioni che si comportano uguale
                 devono dare due risultati uguali e SEPARATI;
  limone         ignora "from": risponde sempre oggi. Deve essere smascherata;
  campione       404: la stazione non esiste;
  malcesinenord  risponde HTML invece di JSON: il canale non c'e' per lei.

Le ultime tre non sono guasti della sonda: sono risultati dell'audit, e
"questa stazione non ha archivio" e' un'informazione che vale quanto il
contrario.
"""
import datetime as dt
import json
import os
import shutil
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["GARDAWIND_HOME"] = "/tmp/gwaudit"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwaudit", ignore_errors=True)
os.makedirs("/tmp/gwaudit", exist_ok=True)

from gardawind.sources import addicted_audit as A

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

OGGI = "2026-09-15"
OGGI_D = dt.date.fromisoformat(OGGI)
ORIZZONTE_FINTO = 40          # giorni di storico del server finto
RICHIESTE = []


class Finto(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        slug = u.path.strip("/").split("/")[-1]
        giorno = (q.get("from") or [OGGI])[0]
        RICHIESTE.append((slug, giorno))

        if slug == "campione":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"<html>non esiste</html>")
            return
        if slug == "semantica_storta":
            # mmax SOTTO mavg: se capitasse davvero, i due nomi non
            # significherebbero "media" e "massimo" dell'ora.
            corpo = json.dumps({
                "ok": True, "arch": ["2026/09/15/0600", "2026/09/15/0700"],
                "mavg": [10.0, 20.0], "mmax": [12.0, 15.0], "dir": [200, 200]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(corpo.encode())
            return
        if slug == "malcesinenord":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>la pagina, non il json</body></html>")
            return

        # limone ignora "from" e risponde sempre con oggi.
        risposta = OGGI if slug == "limone" else giorno
        indietro = (OGGI_D - dt.date.fromisoformat(risposta)).days
        vuoto = indietro > ORIZZONTE_FINTO
        y, m, d = risposta.split("-")
        arch = ["%s/%s/%s/%02d00" % (y, m, d, h) for h in range(24)]
        mavg = [None] * 24 if vuoto else [8.0 + h * 0.2 for h in range(24)]
        mmax = [None] * 24 if vuoto else [12.0 + h * 0.3 for h in range(24)]
        # Un buco vero a mezzogiorno, per contarlo.
        if not vuoto:
            mavg[12] = None
        corpo = json.dumps({"ok": True, "arch": arch, "mavg": mavg,
                            "mmax": mmax, "dir": [200] * 24, "mae": 1.1})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo.encode())


_srv = ThreadingHTTPServer(("127.0.0.1", 0), Finto)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
A.BASE = "http://127.0.0.1:%d/forecast/gardasee/%%s/" % _srv.server_address[1]
RAW = "/tmp/gwaudit/raw"

esiti = {}
for slug in A.SLUG_STAZIONI:
    ris, oriz = A.trova_orizzonte(slug, oggi=OGGI_D, base_raw=RAW)
    esiti[slug] = (ris, oriz, A.riassumi(ris))

# --------------------------------------------------------------------------
# 1. Il controllo che viene prima di tutti
# --------------------------------------------------------------------------
_ris, _oriz, R = esiti["limone"]
ok(R["n_from_ignorato"] >= 1,
   "limone ignora 'from' e viene smascherata (%d giornate marcate)"
   % R["n_from_ignorato"])
ok(_oriz is None,
   "e quindi NON le viene attribuito nessun orizzonte storico (%s)" % _oriz)
ok(R["n_con_serie"] == 0,
   "nessuna sua giornata conta come storico, anche se il JSON era pieno")
ok(R["n_provati"] <= 2,
   "e la sonda si ferma subito invece di scaricare mille volte lo stesso "
   "giorno (%d richieste)" % R["n_provati"])

# --------------------------------------------------------------------------
# 2. L'orizzonte, trovato per bisezione
# --------------------------------------------------------------------------
for slug in ("torbole", "malcesine"):
    _ris, oriz, R = esiti[slug]
    atteso = (OGGI_D - dt.timedelta(days=ORIZZONTE_FINTO)).isoformat()
    ok(oriz == atteso,
       "%s: orizzonte trovato al giorno esatto (%s, atteso %s)"
       % (slug, oriz, atteso))
    ok(R["n_provati"] < 25,
       "%s: trovato con %d richieste, non con cinquemila" % (slug, R["n_provati"]))
    ok(R["n_from_ignorato"] == 0, "%s: 'from' viene rispettato" % slug)

# --------------------------------------------------------------------------
# 3. Le tre stazioni senza archivio sono TRE risultati diversi
# --------------------------------------------------------------------------
_r, _o, R404 = esiti["campione"]
ok(R404["n_non_json"] >= 1 and any("404" in e for e in R404["errori"]),
   "campione: 404 dichiarato come tale (%s)" % (R404["errori"][:1]))
_r, _o, Rhtml = esiti["malcesinenord"]
ok(Rhtml["n_non_json"] >= 1
   and any("non JSON" in e and "HTML" in e for e in Rhtml["errori"]),
   "malcesinenord: risposta HTML distinta da un 404 (%s)" % (Rhtml["errori"][:1]))
ok(esiti["campione"][1] is None and esiti["malcesinenord"][1] is None,
   "e nessuna delle due riceve un orizzonte inventato")

# --------------------------------------------------------------------------
# 4. Le due Malcesine restano due
# --------------------------------------------------------------------------
ok(os.path.isdir(os.path.join(RAW, "malcesine"))
   and os.path.isdir(os.path.join(RAW, "malcesinenord")),
   "il grezzo sta in due cartelle separate, una per stazione")
ok(not os.path.exists(os.path.join(RAW, "malcesine_unito")),
   "e non esiste nessuna cartella che le unisce")
nomi = sorted(os.listdir(RAW))
ok(nomi == sorted(A.SLUG_STAZIONI),
   "una cartella per stazione, nessuna in piu': %s" % nomi)

# --------------------------------------------------------------------------
# 5. Il grezzo e la sua provenienza, sul disco
# --------------------------------------------------------------------------
cart = os.path.join(RAW, "torbole")
file_json = [f for f in os.listdir(cart) if f.endswith(".json")]
file_meta = [f for f in os.listdir(cart) if f.endswith(".meta")]
ok(len(file_json) == len(file_meta) == esiti["torbole"][2]["n_provati"],
   "un grezzo e una provenienza per ogni giornata provata (%d/%d)"
   % (len(file_json), len(file_meta)))
meta = json.load(open(os.path.join(cart, sorted(file_meta)[-1]), encoding="utf-8"))
for campo in ("fetched_at", "sha256", "parser_version", "url", "bytes"):
    ok(meta.get(campo) is not None,
       "la provenienza porta %s (%s)" % (campo, str(meta.get(campo))[:40]))

# --------------------------------------------------------------------------
# 6. I fatti dell'audit: cadenza, buchi, semantica di mavg/mmax
# --------------------------------------------------------------------------
_ris, _oriz, R = esiti["torbole"]
ok(R["cadenza_mediana"] == 60.0,
   "cadenza oraria dedotta dalle chiavi (%s min)" % R["cadenza_mediana"])
ok(R["slot_per_giorno"] == 24.0,
   "ventiquattro slot per giornata (%s)" % R["slot_per_giorno"])
ok(R["buchi_mediani"] == 1.0,
   "e il buco di mezzogiorno viene contato, non ignorato (%s)"
   % R["buchi_mediani"])
ok(R["mmax_sotto_mavg"] == 0,
   "mmax non sta mai sotto mavg: coerente con 'massimo dell'ora'")
ok(R["mae_dichiarato"] == 1.1,
   "l'errore dichiarato dal sito viene riportato (%s)" % R["mae_dichiarato"])
ok(set(R["campi_visti"]) >= {"arch", "mavg", "mmax", "dir", "ok"},
   "i campi visti sono dichiarati: %s" % R["campi_visti"])

# Un mmax sotto mavg deve essere CONTATO DALL'AUDIT: vorrebbe dire che i due
# nomi non significano "media" e "massimo" dell'ora, e sarebbe una scoperta
# sulla semantica della fonte, non un dettaglio.
_storto = A.audit_giorno("semantica_storta", OGGI, base_raw=RAW)
ok(_storto["mmax_sotto_mavg"] == 1,
   "l'audit conta le ore in cui mmax sta sotto mavg (%d)"
   % _storto["mmax_sotto_mavg"])
ok(_storto["json"] and _storto["n_slot"] == 2,
   "e lo fa leggendo la risposta, non i miei dati di prova")
shutil.rmtree(os.path.join(RAW, "semantica_storta"), ignore_errors=True)

# --------------------------------------------------------------------------
# 7. Niente viene ingerito: l'audit guarda e non tocca le osservazioni
# --------------------------------------------------------------------------
from gardawind import store
store.init()
n = store.connect().execute("SELECT COUNT(*) FROM obs_sample").fetchone()[0]
ok(n == 0,
   "dopo l'audit il database delle osservazioni e' ancora vuoto (%d righe): "
   "la decisione di ingerire viene dopo" % n)
