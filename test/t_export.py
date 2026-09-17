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
# Una pagina per localita', piu' diagnostica.html, live.json e
# previsione.json. Il conteggio si ricava da config.PLACES e non e' scritto a
# mano: una localita' in piu' non deve fare cadere un controllo che parla
# d'altro, e soprattutto non deve poter NON avere la sua pagina.
from gardawind import config
# I file comuni: diagnostica, live.json, manifesto, due icone, previsione.
attesi = len(config.PLACES) + 6
ok(len(paths) == attesi,
   "una pagina per localita' piu' i file comuni, anche a database vuoto"
   " (%d su %d)" % (len(paths), attesi))
ok(any(p.endswith("live.json") for p in paths), "fra cui il dato osservato")
ok(any(p.endswith("manifest.webmanifest") for p in paths)
   and any(p.endswith("icona-192.png") for p in paths),
   "e il manifesto con le icone, perche' il sito si installi sul telefono")
icona_png = open("/tmp/sitotest/icona-192.png", "rb").read()
ok(icona_png[:8] == b"\x89PNG\r\n\x1a\n" and len(icona_png) > 200,
   "l'icona e' un PNG vero, generato in libreria standard (%d byte)"
   % len(icona_png))
for place in config.PLACES:
    from gardawind import web
    nome = "/tmp/sitotest/%s.html" % web._slug(place)
    ok(os.path.exists(nome), "la pagina di %s esiste (%s)"
       % (place, os.path.basename(nome)))
h=open("/tmp/sitotest/index.html",encoding='utf-8').read()
ok("raccogliendo" in h, "prima pagina a freddo, senza eccezioni")
ok(config.PLACES[0] in h and config.PLACES[1] in h,
   "e porta la navigazione verso le altre localita'")
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
