"""Le serie irripetibili escono dalla cache e vanno dentro git.

Tre serie esistono solo perche' le registriamo mentre passano: i campioni a
dieci minuti con la direzione, le curve che abbiamo pubblicato, la previsione
altrui con il giorno in cui l'abbiamo letta. Nessuno le conserva al posto
nostro, e fino a oggi stavano in una cache che GitHub cancella dopo sette
giorni di non uso e che tiene 10 GB in tutto - col nostro database da mezzo
giga riscritto a ogni esecuzione, circa quattro giorni di profondita'.

La cosa che questi controlli difendono piu' di ogni altra e' la REGOLA DEL NON
RIMPICCIOLIRE. Senza, il salvataggio diventerebbe il modo di perdere tutto:
basterebbe una cache sfrattata perche' la prima esecuzione successiva - con il
database vuoto e in ricostruzione - scrivesse file vuoti SOPRA l'archivio
buono. Un backup che si lascia svuotare dalla sorgente e' peggio di nessun
backup, perche' ci si fida.
"""
import gzip
import importlib
import os
import shutil
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
os.environ["GARDAWIND_HOME"] = "/tmp/gwarchivio"
shutil.rmtree("/tmp/gwarchivio", ignore_errors=True)

from gardawind import archivio, config, store

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


# I file di prova NON vanno nel progetto vero: si dirotta la radice.
config.PROJECT_DIR = "/tmp/gwarchivio-progetto"
shutil.rmtree(config.PROJECT_DIR, ignore_errors=True)
os.makedirs(config.PROJECT_DIR, exist_ok=True)

store.init()
store.save_samples("campione", [
    ("2026-09-19T08:20:00Z", 9.3, 17.3, 10.0),
    ("2026-09-19T08:30:00Z", 9.5, 17.0, None),
    ("2026-10-01T06:00:00Z", 12.0, 19.0, 200.0)], "addicted-live")
store.save_samples("campione", [("2026-09-19T09:00:00Z", 8.0, 12.0, None)],
                   "addicted-json")      # canale orario: non e' questa serie
store.save_issued_profile("Torbole", "2026-09-19T05:00:00Z",
                          [{"key": "2026-09-19T13:00:00Z", "wind": 14.0,
                            "gust": 20.0}])
store.save_fc_altrui("addicted-sports", "torbole_addicted",
                     [("2026-09-20T12:00:00Z", 11.0, 8.0, 14.0)],
                     letto_a="2026-09-19T05:10:00Z")

# ---- 1. un file per mese, e solo le serie irripetibili ---------------------
fatti = archivio.esporta()
nomi = sorted(p for p, _n, _nuove in fatti)
ok(len(fatti) == 4, "quattro file: due mesi del canale vivo piu' le altre due "
   "serie (%s)" % len(fatti))
ok(any(p.endswith("vivo/campione-2026-09.csv.gz") for p in nomi)
   and any(p.endswith("vivo/campione-2026-10.csv.gz") for p in nomi),
   "il canale vivo e' diviso per mese: %s" % nomi[-2:])
righe = gzip.open(os.path.join(config.PROJECT_DIR,
                               "storico/vivo/campione-2026-09.csv.gz"),
                  "rt").read().strip().split("\n")
ok(righe[0] == "ts,wind_kn,gust_kn,dir_deg" and len(righe) == 3,
   "con l'intestazione e le due letture di settembre - non quella del canale "
   "orario, che si riscarica (%d righe)" % (len(righe) - 1))
ok("10.0" in righe[1],
   "e la direzione misurata e' dentro: e' la cosa nuova, ed e' quella che "
   "non si recupera piu'")

# ---- 2. rifarlo non cambia niente -----------------------------------------
di_nuovo = archivio.esporta()
ok(all(nuove == 0 for _p, _n, nuove in di_nuovo),
   "una seconda esportazione non aggiunge nulla: e' idempotente")

# ---- 3. LA REGOLA: un database vuoto non svuota i file ---------------------
shutil.rmtree("/tmp/gwarchivio", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwarchivio"
importlib.reload(store)
store.init()
ok(store.connect().execute("SELECT COUNT(*) FROM obs_sample").fetchone()[0] == 0,
   "database nuovo e vuoto, come dopo una cache sfrattata")
archivio.esporta()
dopo = gzip.open(os.path.join(config.PROJECT_DIR,
                              "storico/vivo/campione-2026-09.csv.gz"),
                 "rt").read().strip().split("\n")
ok(len(dopo) == 3,
   "esportare da un database vuoto NON svuota l'archivio (%d righe ancora li')"
   % (len(dopo) - 1))

# ---- 4. e il giro si chiude: i file rientrano nel database ------------------
ripresi = archivio.recupera()
ok(sum(n for _f, n in ripresi) == 5,
   "recupera rimette dentro tutte le righe (%s)" % ripresi)
c = store.connect()
r = c.execute("SELECT wind_kn, gust_kn, dir_deg, source FROM obs_sample "
              "WHERE ts='2026-09-19T08:20:00Z'").fetchone()
ok(r and r[0] == 9.3 and r[2] == 10.0 and r[3] == "addicted-live",
   "con i valori e la direzione intatti, e la fonte giusta")
ok(c.execute("SELECT COUNT(*) FROM fc_altrui").fetchone()[0] == 1
   and c.execute("SELECT COUNT(*) FROM issued_profile").fetchone()[0] == 1,
   "e anche le altre due serie sono tornate")
n2 = sum(n for _f, n in archivio.recupera())
ok(n2 == 0, "e un secondo recupero non duplica niente (%d)" % n2)

# ---- 5. il flusso in cloud lo fa davvero ----------------------------------
wf = open(os.path.join(QUI, "..", ".github", "workflows", "garda-wind.yml"),
          encoding="utf-8").read()
ok("contents: write" in wf,
   "il job ha il permesso di scrivere nel repository")
ok("Metti al sicuro le serie irripetibili" in wf and "git push origin HEAD:main" in wf,
   "e il passo che le spinge c'e'")
ok("continue-on-error: true" in wf,
   "ma non fa fallire la build: perdere la pubblicazione del sito per un "
   "conflitto di git sarebbe peggio di sei ore di ritardo nel salvataggio")
voci = [r.strip() for r in wf.split("permissions:")[0].split("\n")
        if r.strip().startswith("- \"")]
ok(all("storico" not in v for v in voci),
   "e storico/ NON e' fra i percorsi che rilanciano il flusso - sarebbe un "
   "ciclo che non si ferma piu' (%s)" % voci)
ok("archivio.recupera()" in open(os.path.join(QUI, "..", "gardawind",
                                              "__main__.py"),
                                 encoding="utf-8").read(),
   "e il ciclo in cloud ricarica i file PRIMA di lavorare")
print("%d controlli sull'archivio irripetibile" % passati)
