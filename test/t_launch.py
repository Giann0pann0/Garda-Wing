import os, sys, subprocess, time, urllib.request, shutil
BASE=os.path.dirname(os.path.abspath(__file__))
RES=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
sys.path.insert(0,RES)
from gardawind import config
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)

# 1) --no-browser esiste e viene rispettato dal lanciatore
src=open(os.path.join(RES,'gardawind','__main__.py'),encoding='utf-8').read()
ok("_open_browser" in src and "/usr/bin/open" in src, "apertura browser via comando 'open' di macOS")
ok("def _open_browser" in src, "funzione dedicata, non piu' webbrowser nudo")

sh=open(os.path.join(BASE,'..','mac','GardaWind'),encoding='utf-8').read()
ok("--no-browser" in sh, "il lanciatore avvia il server senza farlo aprire da Python")
ok("health" in sh and "for _ in $(seq 1 40)" in sh, "aspetta che /health risponda prima di aprire")
ok(sh.count("open \"$URL\"")>=2, "apre il browser sia al primo avvio sia se gia' in esecuzione")
ok("display alert" in sh and "avvio.log" in sh, "se non parte, avvisa e indica il log")
ok('wait "$SERVER"' in sh, "il bundle resta vivo finche' vive il server")

# 2) il server si avvia davvero e /health risponde entro pochi secondi
env=dict(os.environ, GARDAWIND_HOME="/tmp/gwlaunch")
shutil.rmtree("/tmp/gwlaunch", ignore_errors=True)
p=subprocess.Popen([sys.executable,"-m","gardawind","--port","8802","--no-browser"],
                   cwd=RES, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
up=False
for _ in range(40):
    try:
        if urllib.request.urlopen("http://127.0.0.1:8802/health", timeout=2).read()==b"ok":
            up=True; break
    except Exception: time.sleep(0.5)
ok(up, "il server risponde su /health dopo l'avvio")
if up:
    body=urllib.request.urlopen("http://127.0.0.1:8802/", timeout=30).read().decode()
    # Il piede non ripete piu' il nome del prodotto: la pagina ha il nome
    # del POSTO in cima, e "chiudi Garda Wind" era una delle scritte che
    # Gian ha chiesto di togliere. Resta il collegamento, che serve.
    ok(config.PLACES[0] in body and '>chiudi</a>' in body,
       "pagina servita, col nome del posto e il collegamento di chiusura")
    urllib.request.urlopen("http://127.0.0.1:8802/spegni", timeout=10).read()
    time.sleep(1.5)
    down=False
    try: urllib.request.urlopen("http://127.0.0.1:8802/health", timeout=2)
    except Exception: down=True
    ok(down, "/spegni ferma davvero il server")
p.terminate()
try: p.wait(timeout=5)
except Exception: p.kill()

# --------------------------------------------------------------------------
# Il processo veloce non puo' zittirsi per sempre in silenzio
# --------------------------------------------------------------------------
# Visto il 2026-09-19: live.json fermo dal 17, quindi "adesso" congelato fra
# una ricostruzione e l'altra, e Campione che sembrava morta. Due difese, e
# nessuna delle due e' una diagnosi: sono i modi in cui quel processo NON
# deve poter smettere di pubblicare.
import os as _os
_wf = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..",
                         ".github", "workflows", "adesso.yml"), encoding="utf-8").read()
_cron = "*/10" in _wf
ok("timeout-minutes:" in _wf,
   "il flusso veloce ha un limite di tempo per esecuzione")
_limite = int(_wf.split("timeout-minutes:")[1].split("\n")[0].strip())
ok(not _cron or _limite < 10,
   "piu' corto del periodo del cron (%d min): un'esecuzione impiantata muore"
   " da sola invece di essere annullata da quella dopo, per sempre" % _limite)
ok("cancel-in-progress: true" in _wf,
   "e l'ultima lettura vince, che per un dato osservato e' giusto")

_main = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..",
                           "gardawind", "__main__.py"), encoding="utf-8").read()
_pezzo = _main[_main.index('if args.live_json:'):]
_pezzo = _pezzo[:_pezzo.index("if args.ci:")]
ok(_pezzo.index("scrivi(args.live_json)") < _pezzo.index("avvisi"),
   "il file si scrive PRIMA degli avvisi")
# E SI PROVA DAVVERO, invece di cercare una stringa. Qui c'era
# `"except Exception" in _pezzo`, che e' vero anche per un try messo la' per
# un altro motivo: si poteva cancellare la protezione attorno agli avvisi e il
# controllo diceva PASS. Adesso si fa fallire avvisi.esegui e si guarda il
# codice di uscita del comando e il file.
import importlib as _il
from gardawind import avvisi as _avvisi, live as _live
_vero = _avvisi.esegui


def _esplode(*a, **k):
    raise RuntimeError("Telegram e' giu'")


_avvisi.esegui = _esplode
# Niente rete: quello che si prova qui e' la protezione, non la lettura delle
# centraline. Un controllo che chiama tre fonti vere e' un controllo che non si
# esegue volentieri, e un test che non si esegue non difende niente.
from gardawind import engine as _eng
_vere_letture = _eng.aggiorna_centraline_vive
_eng.aggiorna_centraline_vive = lambda: ["prova: nessuna lettura"]
_dest = "/tmp/gwlaunch-live.json"
if _os.path.exists(_dest):
    _os.remove(_dest)
try:
    from gardawind.__main__ import main as _main_fn
    _codice = _main_fn(["--live-json", _dest])
except SystemExit as e:                     # noqa: PERF203
    _codice = e.code
except Exception as e:                      # noqa: BLE001
    _codice = "eccezione: %s" % e
finally:
    _avvisi.esegui = _vero
    _eng.aggiorna_centraline_vive = _vere_letture
ok(_codice == 0 and _os.path.exists(_dest),
   "e un errore negli avvisi non fa uscire il comando con un codice di errore"
   " (uscita %r, file scritto %s): altrimenti il passo di pubblicazione non"
   " parte e il sito resta col dato vecchio per colpa di un messaggio Telegram"
   % (_codice, _os.path.exists(_dest)))

# ---- il pallino verde non deve poter mentire --------------------------------
# Il giro lungo ingoia i propri errori di proposito, e per mesi un'esecuzione
# riuscita a meta' e' restata verde: se la prima fonte risponde male, il sito
# viene ricostruito dal database vecchio e ci stampa sopra "previsione calcolata
# adesso". Questi controlli difendono il passo che lo scopre.
from gardawind import salute as _S  # noqa: E402

_st = _S.stato()
ok(set(_st) == {"ok", "motivi", "dettagli"},
   "la salute risponde con ok/motivi/dettagli")
ok(_st["ok"] is False and any("previsione" in m for m in _st["motivi"]),
   "su un database senza previsioni dice che qualcosa non torna, e dice cosa: "
   "%s" % (_st["motivi"][:1] or "niente"))
ok(any("ore" in r for r in _S.righe_da_stampare(_st)),
   "e lo stampa in righe leggibili, le stesse nel flusso e sul Mac")

# I tre motivi che fanno diventare rosso il pallino sono SOLO questi tre: un
# errore su una singola fonte non deve accenderlo, perche' un allarme che suona
# ogni settimana per niente si impara a ignorarlo.
_src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..",
                          "gardawind", "salute.py"), encoding="utf-8").read()
ok(_src.count("motivi.append(") == 6,
   "sei soli motivi di allarme (previsione assente, previsione vecchia, "
   "prodotto vuoto, una localita' senza previsione, archivio non spinto, "
   "centraline mute): %d" % _src.count("motivi.append("))
ok('dettagli["n_errori"]' in _src and "motivi.append" not in
   _src.split('dettagli["errori"]')[1],
   "gli errori delle singole fonti si contano e si stampano, e NON fanno "
   "fallire il giro")

_wf = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..",
                         ".github", "workflows", "garda-wind.yml"),
           encoding="utf-8").read()
ok("--salute" in _wf and _wf.index("upload-pages-artifact") < _wf.index("--salute"),
   "nel flusso il controllo sta DOPO la pubblicazione dell'artefatto: il sito "
   "esce comunque, il pallino diventa rosso")
ok("!cancelled()" in _wf,
   "e il passo che pubblica su Pages gira anche se la salute ha fatto fallire "
   "il giro: il rosso serve a chi guarda, non a togliere il sito a chi lo usa")
ok("github.run_attempt" in _wf,
   "la chiave della cache porta anche il tentativo: una ri-esecuzione riuscita "
   "puo' salvare il proprio lavoro")

# ---- i tre controlli guardavano tutti dalla stessa parte --------------------
# Riletti a freddo il 20/09/2026, prima di due mesi in cui nessuno li leggera'.
# Ognuno dei tre aveva un modo di dire di si' senza aver guardato.

# 1. "La previsione e' fresca" leggeva un'ora che veniva scritta SEMPRE, anche
#    quando nessuna delle quaranta richieste era arrivata a destinazione.
_eng_src = open(_os.path.join(RES, "gardawind", "engine.py"), encoding="utf-8").read()
_pezzo = _eng_src.split("def update_forecasts")[1].split("def update_context")[0]
ok("if okc:" in _pezzo and _pezzo.index("if okc:")
   < _pezzo.index('meta_set("last_forecast_run"'),
   "l'ora dell'ultima previsione si scrive solo se qualcosa e' arrivato "
   "davvero: era l'occhio del controllo, e guardava il proprio orologio")

# Non basta leggerlo nel testo: si prova. Con tutte le fonti che rifiutano,
# l'ora dell'ultima previsione NON deve muoversi.
from gardawind import store as _store, engine as _engine  # noqa: E402
from gardawind.sources import openmeteo as _om  # noqa: E402
from gardawind.sources.http import FetchError as _FE  # noqa: E402
_os.environ["GARDAWIND_HOME"] = "/tmp/gwsalute"
shutil.rmtree("/tmp/gwsalute", ignore_errors=True)
_store._CONN = None if hasattr(_store, "_CONN") else None
_store.init()
_store.meta_set("last_forecast_run", "2026-09-01T00:00:00Z")
_vera_fetch = _om.fetch_forecast
_om.fetch_forecast = lambda *a, **k: (_ for _ in ()).throw(_FE("giu'"))
try:
    _okc = _engine.update_forecasts()
finally:
    _om.fetch_forecast = _vera_fetch
ok(_okc == 0 and _store.meta_get("last_forecast_run") == "2026-09-01T00:00:00Z",
   "provato: con tutte le fonti giu' l'ora resta quella dell'ultimo run vero "
   "(%s)" % _store.meta_get("last_forecast_run"))

from gardawind import salute as _S2  # noqa: E402
_st2 = _S2.stato()
ok(any("previsione" in m and "ore" in m for m in _st2["motivi"]),
   "e allora la salute lo dice: previsione vecchia invece di verde")

# 2. "Il prodotto esiste" passava con un solo spot su sette.
_st3 = _S2.stato(prodotto={config.SPOT_ORDER[0]: [{"day": "x"}]})
ok(any("non hanno previsione" in m for m in _st3["motivi"])
   and config.SPOT_ORDER[-1] in " ".join(_st3["motivi"]),
   "sei localita' su sette senza previsione fanno diventare rosso il pallino, "
   "e il motivo dice quali")

# 3. "L'archivio cresce" leggeva dei file che il giro stesso aveva appena
#    riscritto: dentro il flusso non poteva dire di no. Adesso c'e' il
#    biglietto lasciato da chi ha spinto davvero.
_marca = _S2.marca_push_riuscito()
ok(_os.path.exists(_marca), "il biglietto del push riuscito si scrive dove sta "
                            "il database, non nel repository")
_st4 = _S2.stato()
ok(_st4["dettagli"]["archivio_misura"] == "push riuscito"
   and not any("archivio" in m for m in _st4["motivi"]),
   "appena spinto, l'archivio non e' un motivo di allarme")
open(_marca, "w", encoding="utf-8").write("2026-08-20T00:00:00Z\n")
_st5 = _S2.stato()
ok(any("archivio non arriva nel repository" in m for m in _st5["motivi"]),
   "fermo da un mese, invece, il pallino diventa rosso - ed e' anche il "
   "motivo per cui GitHub spegnerebbe i cron dopo 60 giorni")
ok("archivio-spinto.txt" in _wf
   and _wf.split("git push origin HEAD:main")[1].split("\n")[0].count("marca"),
   "e nel flusso il biglietto lo scrive SOLO chi e' arrivato in fondo al push")

# 4. Il controllo che mancava: nessuno dei tre guardava le MISURE, cioe' il
#    metro contro cui tutto il resto si corregge.
_vere_stats = _store.obs_stats
_store.obs_stats = lambda st: {"hour_to": "2026-08-01T10:00:00Z", "hours": 10,
                               "hour_from": "2026-01-01T00:00:00Z", "days": 1,
                               "day_from": None, "day_to": None, "samples": 0}
try:
    _st6 = _S2.stato()
finally:
    _store.obs_stats = _vere_stats
ok(any("centraline non dicono niente" in m for m in _st6["motivi"]),
   "una centralina ferma da settimane accende il pallino: la previsione "
   "continuerebbe a uscire, ma non impariamo piu' niente")

print("controlli sull'avvio e sulla salute: finiti")
