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
# Piu' la foto di sfondo, se Gian l'ha messa nella cartella del progetto.
# Piu' robots.txt e sitemap.xml, quando il sito ha un indirizzo pubblico.
attesi = (len(config.PLACES) + 6 + (1 if config.sfondo_path() else 0)
          + (2 if config.SITE_URL else 0))
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
ok("actions/cache/restore@v4" in y and "actions/cache/save@v4" in y
   and "restore-keys" in y,
   "cache con chiave di ripiego, e ripristino e salvataggio in due passi "
   "separati: `actions/cache` intero salva solo se il job e' riuscito, e da "
   "quando la salute puo' farlo fallire un giro rosso butterebbe via anche il "
   "lavoro fatto")
ok("upload-artifact" in y, "copia di sicurezza del database")
ok("cron:" in y and "workflow_dispatch" in y, "schedulato e lanciabile a mano")
ok("push:" in y and "branches: [main]" in y,
   "una modifica al codice ripubblica il sito senza aspettare il cron")
ok("gardawind/**" in y, "il trigger su push guarda il pacchetto, non i documenti")
try:
    import yaml
    yaml.safe_load(y); ok(True,"YAML valido")
except ImportError:
    # SENZA pyyaml non si dice "superato": si controlla quello che si puo'.
    # Il Python di sistema del Mac non ha pyyaml, quindi questo era il ramo
    # VERO e stampava PASS senza aver letto niente - e un flusso rotto vuol
    # dire sito fermo sui dati vecchi, senza errore visibile.
    _righe = y.split("\n")
    _tab = [n+1 for n,r in enumerate(_righe) if r[:len(r)-len(r.lstrip())].count("\t")]
    _chiavi = [r.split(":")[0] for r in _righe if r and not r[0].isspace()
               and ":" in r and not r.startswith("#")]
    _dispari = [n+1 for n,r in enumerate(_righe)
                if r.strip().startswith("- ") and (len(r)-len(r.lstrip()))%2]
    ok(not _tab and {"name","on","jobs"} <= set(_chiavi) and not _dispari,
       "YAML plausibile anche senza pyyaml: nessuna tabulazione %s, le chiavi "
       "di primo livello ci sono (%s), le liste sono indentate pari %s"
       % (_tab or "ok", ",".join(sorted(set(_chiavi))[:6]), _dispari or "ok"))
except Exception as e:
    ok(False,"YAML non valido: %s"%e)

# --ci e --export sono davvero esposti dalla riga di comando
m=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','gardawind','__main__.py'),encoding='utf-8').read()
ok('"--export"' in m and '"--ci"' in m, "le opzioni esistono in __main__")

# La foto di sfondo: se c'e' nel progetto, finisce accanto alla pagina e la
# testa la usa; se non c'e', la pagina disegna il cielo e non cerca un file
# che non esiste.
import os as _os
OUT = "/tmp/sitotest"
_html = open(_os.path.join(OUT, "index.html"), encoding="utf-8").read()
if config.sfondo_path():
    ok(_os.path.exists(_os.path.join(OUT, config.SFONDO_FILE))
       and 'class="hero foto"' in _html and 'class="cielo"' not in _html,
       "con la foto: copiata accanto alla pagina, e niente cielo disegnato")
else:
    ok('class="hero"' in _html and 'class="cielo"' in _html,
       "senza foto: il cielo disegnato, e nessun riferimento a un file assente")

# La mappa del sito elenca una pagina per localita', dalla stessa lista.
if config.SITE_URL:
    _sm = open(_os.path.join(OUT, "sitemap.xml"), encoding="utf-8").read()
    ok(_sm.count("<url>") == len(config.PLACES)
       and all(web.url_pagina(p) in _sm for p in config.PLACES),
       "sitemap.xml: una voce per localita', dagli stessi indirizzi delle pagine")
    ok('<link rel="canonical" href="%s">' % web.url_pagina("Torbole") in _html,
       "e ogni pagina dichiara il suo indirizzo canonico")
