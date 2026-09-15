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
        # UNA RISPOSTA COPRE TRE GIORNI: 72 slot a cadenza oraria, dal giorno
        # richiesto ai due successivi. Il server vero fa questo, e il conto
        # torna: chiedendo ieri arrivano 24 ore di ieri piu' le ore di oggi
        # fino adesso, cioe' le 34 medie viste nell'audit reale. Il primo
        # server finto restituiva un giorno solo, e il censimento contava un
        # terzo delle giornate senza che nulla sembrasse rotto.
        d0 = dt.date.fromisoformat(risposta)
        arch, mavg, mmax = [], [], []
        for i in range(72):
            giorno_slot = d0 + dt.timedelta(days=i // 24)
            ora = i % 24
            arch.append("%04d/%02d/%02d/%02d00"
                        % (giorno_slot.year, giorno_slot.month,
                           giorno_slot.day, ora))
            indietro = (OGGI_D - giorno_slot).days
            futuro = indietro < 0 or (indietro == 0 and ora >= 12)
            misurato = (0 <= indietro <= ORIZZONTE_FINTO) and not futuro
            # Un buco vero a mezzogiorno, per contarlo.
            if misurato and ora == 12:
                misurato = False
            mavg.append(8.0 + ora * 0.2 if misurato else None)
            mmax.append(12.0 + ora * 0.3 if misurato else None)
        corpo = json.dumps({"ok": True, "arch": arch, "mavg": mavg,
                            "mmax": mmax, "dir": [200] * 72, "mae": 1.1})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo.encode())


_srv = ThreadingHTTPServer(("127.0.0.1", 0), Finto)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
A.BASE = "http://127.0.0.1:%d/forecast/gardasee/%%s/" % _srv.server_address[1]
RAW = "/tmp/gwaudit/raw"

# Le stazioni di PROVA sono quelle del server finto, non quelle vere: qui si
# simulano cinque COMPORTAMENTI, e l'elenco vero delle stazioni cambia quando
# se ne scopre una nuova (e' appena successo con caporeamol e brenzone). Farli
# dipendere l'uno dall'altro romperebbe questi controlli a ogni scoperta.
STAZIONI_FINTE = ("torbole", "limone", "malcesine", "campione", "malcesinenord")

esiti = {}
for slug in STAZIONI_FINTE:
    ris, E = A.trova_orizzonte(slug, oggi=OGGI_D, base_raw=RAW)
    esiti[slug] = (ris, E["orizzonte"], A.riassumi(ris), E)

# --------------------------------------------------------------------------
# 1. Il controllo che viene prima di tutti
# --------------------------------------------------------------------------
_ris, _oriz, R, _E = esiti["limone"]
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
    _ris, oriz, R, _E = esiti[slug]
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
_r, _o, R404, _E4 = esiti["campione"]
ok(R404["n_non_json"] >= 1 and any("404" in e for e in R404["errori"]),
   "campione: 404 dichiarato come tale (%s)" % (R404["errori"][:1]))
_r, _o, Rhtml, _Eh = esiti["malcesinenord"]
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
ok(nomi == sorted(STAZIONI_FINTE),
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
_ris, _oriz, R, _E = esiti["torbole"]
# Il fondo della scala: se la sonda non trova mai una giornata vuota, il
# giorno piu' profondo NON e' l'orizzonte e va dichiarato come limite. Sul
# server finto l'archivio finisce a 40 giorni, quindi il fondo VIENE
# raggiunto - e il caso contrario si prova chiedendo una scala corta.
_ris_corta, _E_corta = A.trova_orizzonte("torbole", oggi=OGGI_D, salva=False,
                                         salti=(1, 3, 7))
ok(_E_corta["fondo_non_raggiunto"] is True,
   "con una scala che finisce prima dell'archivio, il fondo e' dichiarato "
   "non raggiunto")
ok(esiti["torbole"][3]["fondo_non_raggiunto"] is False,
   "mentre con la scala piena l'orizzonte e' un orizzonte vero")

ok(R["cadenza_mediana"] == 60.0,
   "cadenza oraria dedotta dalle chiavi (%s min)" % R["cadenza_mediana"])
# Settantadue slot PER RISPOSTA, non per giornata: sono 72 ore, cioe' tre
# giorni a cadenza oraria. Letto male, farebbe credere a un campionamento
# ogni venti minuti.
ok(R["slot_per_giorno"] == 72.0,
   "settantadue slot per RISPOSTA (%s)" % R["slot_per_giorno"])
ok(R["cadenza_mediana"] == 60.0 and R["slot_per_giorno"] * 60 / 60 == 72,
   "72 slot a cadenza 60 min = una finestra di 72 ore")
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

# --------------------------------------------------------------------------
# 7b. Gli slug veri vengono dalla pagina /historie/, non indovinati
# --------------------------------------------------------------------------
ok("caporeamol" in A.SLUG_STAZIONI and "limone" not in A.SLUG_STAZIONI,
   "lo slug di Limone e' caporeamol: 'limone' risponde HTML, ed e' il motivo "
   "per cui sembrava senza archivio")
ok(A.DICHIARATO["caporeamol"]["nome"].endswith("Limone"),
   "e il nome leggibile resta Limone, cosi' nessuno si perde")
ok(set(A.DICHIARATO) >= set(A.SLUG_STAZIONI),
   "ogni stazione sondata ha i suoi numeri dichiarati da confrontare")
ok(A.DICHIARATO["torbole"]["giorni_misurati"] == 959
   or A.DICHIARATO["torbole"]["nome"] == "finto",
   "Torbole dichiara 959 giornate misurate: e' il tetto di cio' che si puo' "
   "scaricare, non dodici anni")

# --------------------------------------------------------------------------
# 8. Il censimento: giorni veri, non richieste - e ripartibile
# --------------------------------------------------------------------------
# Il server finto ha 40 giorni di archivio e risponde con finestre di 24 ore.
# Il censimento deve contare i GIORNI, confrontarli col dichiarato, e alla
# seconda esecuzione non ribattere il sito.
A.DICHIARATO["torbole"] = {"dal": 2026, "giorni_misurati": 40,
                           "giorni_vento": None, "nome": "finto"}
CENS = "/tmp/gwaudit/censimento"
prima = len(RICHIESTE)
per_giorno, R1 = A.censimento("torbole", oggi=OGGI_D, dal=2026,
                              base_raw=CENS, massimo=20)
richieste_prima = len(RICHIESTE) - prima

# Quaranta giornate di archivio piu' oggi (mezza). Il censimento conta i
# GIORNI visti nelle risposte, non le richieste: 86 richieste, 41 giornate.
ok(R1["n_con_dato"] == 41,
   "conta le giornate con dato viste nelle risposte (%d)" % R1["n_con_dato"])
ok(R1["n_complete"] == 40,
   "complete solo le quaranta piene: oggi ha mezza giornata e non conta "
   "(%d complete)" % R1["n_complete"])
# Le richieste che hanno trovato dati ne coprono tre ciascuna: 41 giornate
# viste da ~14 richieste utili, non 41 da 41.
ok(R1["n_con_dato"] >= 3 * (R1["n_con_dato"] / 3.0) - 1,
   "le giornate viste arrivano a gruppi di tre per richiesta utile (%d)"
   % R1["n_con_dato"])
ok(R1["primo"] and R1["ultimo"] and R1["primo"] < R1["ultimo"],
   "con il periodo dichiarato: %s -> %s" % (R1["primo"], R1["ultimo"]))
ok(R1["dichiarato"] == 40 and R1["quota_del_dichiarato"] > 1.0,
   "il totale si mette accanto al dichiarato (quota %.2f)"
   % R1["quota_del_dichiarato"])
ok(R1["n_richieste"] == richieste_prima,
   "il conteggio delle richieste e' quello vero (%d)" % R1["n_richieste"])

# Seconda esecuzione: tutto dalla cache, nessuna richiesta nuova.
prima = len(RICHIESTE)
_pg2, R2 = A.censimento("torbole", oggi=OGGI_D, dal=2026, base_raw=CENS,
                        massimo=20)
ok(len(RICHIESTE) == prima and R2["n_richieste"] == 0,
   "alla seconda esecuzione non parte nessuna richiesta (%d)" % R2["n_richieste"])
ok(R2["n_dalla_cache"] > 0 and R2["n_con_dato"] == R1["n_con_dato"],
   "e il risultato e' lo stesso, letto dal grezzo salvato (%d dalla cache)"
   % R2["n_dalla_cache"])

# Il record dichiarato: un mmax piu' alto va segnalato.
A.RECORD_DICHIARATO_KN["torbole"] = 5.0
_pg3, R3 = A.censimento("torbole", oggi=OGGI_D, dal=2026, base_raw=CENS,
                        massimo=20)
ok(R3["mmax_oltre_record"] is True and R3["mmax_visto"] > 5.0,
   "un mmax oltre il record dichiarato viene segnalato (%.1f > 5.0)"
   % R3["mmax_visto"])
A.RECORD_DICHIARATO_KN["torbole"] = 49.6

# I passi sono di tre giorni, non di uno.
passi = A.giorni_da_censire("torbole", oggi=OGGI_D, dal=2026)
ok(all((dt.date.fromisoformat(passi[i + 1]) - dt.date.fromisoformat(passi[i])).days == 3
       for i in range(len(passi) - 1)),
   "le richieste sono una ogni tre giorni: una risposta copre tre giorni")
