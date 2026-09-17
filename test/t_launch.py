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
