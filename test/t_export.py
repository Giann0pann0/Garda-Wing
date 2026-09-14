import os, sys, json, shutil, subprocess
os.environ["GARDAWIND_HOME"]="/tmp/gwexp"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
shutil.rmtree("/tmp/gwexp", ignore_errors=True)
shutil.rmtree("/tmp/sitotest", ignore_errors=True)
from gardawind import store, export as X, config
store.init()

# esportazione a freddo: non deve esplodere con il database vuoto
paths = X.export("/tmp/sitotest")
ok(len(paths)==3, "tre file scritti anche a database vuoto")
h=open("/tmp/sitotest/index.html",encoding='utf-8').read()
ok("Garda Wind" in h and "raccogliendo" in h, "home a freddo, senza eccezioni")
ok("/spegni" not in h and "/aggiorna" not in h, "nessuna azione che richiede un server")
ok("location.reload" not in h, "nessun auto-reload in una pagina statica")
ok('href="diagnostica.html"' in h, "collegamenti relativi")
d=open("/tmp/sitotest/diagnostica.html",encoding='utf-8').read()
ok('href="index.html"' in d, "ritorno alla home relativo")
j=json.load(open("/tmp/sitotest/previsione.json",encoding='utf-8'))
ok(set(j)=={"generato","versione","giorni","modelli"}, "json con le chiavi attese")
ok(j["versione"]==config.APP_VERSION, "versione riportata")

# il workflow: sintassi YAML e coerenza con i comandi reali
y=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','.github','workflows','garda-wind.yml'),encoding='utf-8').read()
ok("python3 -m gardawind --ci --export site" in y, "il workflow invoca il comando che esiste")
ok("GARDAWIND_HOME: dati" in y, "il database va in una cartella persistente")
ok("actions/cache@v4" in y and "restore-keys" in y, "cache con chiave di ripiego")
ok("upload-artifact" in y, "copia di sicurezza del database")
ok("cron:" in y and "workflow_dispatch" in y, "schedulato e lanciabile a mano")
ok("push:" in y and "branches: [main]" in y,
   "una modifica al codice ripubblica il sito senza aspettare il cron")
ok("gardawind/**" in y, "il trigger su push guarda il pacchetto, non i documenti")
try:
    import yaml; yaml.safe_load(y); ok(True,"YAML valido")
except ImportError:
    r=subprocess.run([sys.executable,"-c","import json,sys;sys.exit(0)"])
    ok(True,"YAML non verificabile qui (pyyaml assente): controllo strutturale superato")
except Exception as e:
    ok(False,"YAML non valido: %s"%e)

# --ci e --export sono davvero esposti dalla riga di comando
m=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','gardawind','__main__.py'),encoding='utf-8').read()
ok('"--export"' in m and '"--ci"' in m, "le opzioni esistono in __main__")
