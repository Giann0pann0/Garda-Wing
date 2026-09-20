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

# ---- 6. i nomi dei file tornano a essere stazioni --------------------------
# Il difetto che questo controllo impedisce di rimettere: il nome del file e'
# "<stazione>-<AAAA-MM>.csv.gz" e il mese contiene un trattino, quindi
# tagliare all'ULTIMO trattino dava "campione-2026". Le righe rientravano
# sotto una stazione che non esiste, il recupero non recuperava niente, e
# l'esportazione dopo creava "campione-2026-2026-09.csv.gz": un file
# spazzatura in piu' a ogni giro, committato in main dal flusso.
#
# I sedici controlli qui sopra passavano lo stesso, perche' verificavano i
# valori e la direzione e mai la STAZIONE. Un controllo che guarda il carico
# e non l'indirizzo lascia passare i pacchi consegnati a casa d'altri.
stazioni = [r[0] for r in store.connect().execute(
    "SELECT DISTINCT station FROM obs_sample ORDER BY station")]
ok(stazioni == ["campione"],
   "le righe rientrano sotto la LORO stazione, non sotto un nome inventato "
   "(%s)" % stazioni)
posti = [r[0] for r in store.connect().execute(
    "SELECT DISTINCT place FROM issued_profile")]
sta2 = [r[0] for r in store.connect().execute(
    "SELECT DISTINCT station FROM fc_altrui")]
ok(posti == ["Torbole"] and sta2 == ["torbole_addicted"],
   "vale per tutte e tre le serie, compresi i nomi con un trattino dentro "
   "(%s, %s)" % (posti, sta2))
prima = sorted(os.listdir(os.path.join(config.PROJECT_DIR, "storico/vivo")))
archivio.esporta()
ok(sorted(os.listdir(os.path.join(config.PROJECT_DIR, "storico/vivo"))) == prima,
   "e una esportazione dopo un recupero non crea file nuovi: %s" % prima)

# ---- 7. il ponte fra i due processi ----------------------------------------
# Il difetto piu' grave della revisione: i due processi hanno due database
# separati - per una ragione buona, le cache sono immutabili e il veloce non
# puo' salvare sopra quella del lento senza rischiare di fargli perdere i
# modelli - ma la conseguenza non era stata vista. I campioni a dieci minuti
# CON LA DIREZIONE li legge il veloce, 144 volte al giorno, e li mette nel suo
# database; il lento, che addestra e che archivia, ne prendeva 4 al giorno da
# se'. Dell'unica serie che non si riscarica ne salvavamo una su trentasei.
import datetime as _dt  # noqa: E402

shutil.rmtree("/tmp/gwveloce", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwveloce"
importlib.reload(store)
store.init()
ADESSO = _dt.datetime(2026, 9, 20, 12, 0, tzinfo=_dt.timezone.utc)
store.save_samples("campione", [
    ((ADESSO - _dt.timedelta(minutes=10 * k)).strftime("%Y-%m-%dT%H:%M:%SZ"),
     9.0 + k * 0.1, 14.0, 200.0 + k) for k in range(12)], "addicted-live")
store.save_samples("campione", [("2026-09-01T10:00:00Z", 8.0, 12.0, 100.0)],
                   "addicted-live")          # troppo vecchio per il ponte
store.save_samples("malcesine_add", [
    ((ADESSO - _dt.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
     13.0, 19.0, None)], "addicted-live")
store.save_samples("T0193", [("2026-09-20T11:50:00Z", 12.0, 18.0, 55.0)],
                   "meteotrentino")          # altra fonte: non e' questa serie

PONTE = "/tmp/gwveloce/vivo.csv.gz"


def _ramo_vuoto(url, timeout=None):
    """Il ramo esiste ma il ponte non c'e' ancora: la prima esecuzione.

    Il `fetch` si passa SEMPRE nei controlli. Senza, scrivi_vivo_recente va a
    leggere il file davvero pubblicato su GitHub - si fonde con lui, com'e'
    giusto in produzione - e un controllo che dipende dal vento di stamattina
    sul Garda non e' un controllo.
    """
    return gzip.compress(b"station,ts,wind_kn,gust_kn,dir_deg\n")


n = archivio.scrivi_vivo_recente(PONTE, adesso=ADESSO, fetch=_ramo_vuoto)
ok(n == 13, "il processo veloce pubblica i campioni recenti del canale vivo "
   "(%d: 12 di Campione e 1 di Malcesine, non quello di tre settimane fa "
   "ne' quelli di un'altra fonte)" % n)

# Ora il processo LENTO, con il suo database, li rilegge.
shutil.rmtree("/tmp/gwlento", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlento"
importlib.reload(store)
store.init()
ok(store.connect().execute("SELECT COUNT(*) FROM obs_sample").fetchone()[0] == 0,
   "il database del processo lento parte vuoto, come in cloud")
letti = archivio.leggi_vivo_pubblicato(fetch=lambda url, timeout=None: open(PONTE, "rb").read())
ok(letti == 13, "e li riprende tutti dal ramo (%d)" % letti)
r = store.connect().execute(
    "SELECT station, wind_kn, dir_deg, source FROM obs_sample "
    "WHERE ts=? AND station='campione'",
    (ADESSO.strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()
ok(r and r[1] == 9.0 and r[2] == 200.0 and r[3] == "addicted-live",
   "con la DIREZIONE misurata, che e' la ragione per cui quel canale esiste")
ok(archivio.leggi_vivo_pubblicato(
    fetch=lambda url, timeout=None: open(PONTE, "rb").read()) == 13,
   "rileggerlo non duplica niente: stessa chiave, stessa riga")
fatti = archivio.esporta()
ok(any("vivo/campione" in p for p, _n, _nuove in fatti),
   "e da li' finiscono nell'archivio mensile dentro git (%s)"
   % [p for p, _n, _nuove in fatti])

wf = open(os.path.join(QUI, "..", ".github", "workflows", "adesso.yml"),
          encoding="utf-8").read()
ok("vivo.csv.gz" in wf,
   "il flusso veloce pubblica il file accanto a live.json")
main = open(os.path.join(QUI, "..", "gardawind", "__main__.py"),
            encoding="utf-8").read()
ok("scrivi_vivo_recente" in main and "leggi_vivo_pubblicato" in main,
   "e i due comandi lo scrivono e lo rileggono")
# ---- il PONTE non si rimpicciolisce -----------------------------------------
# Era l'unico pezzo della catena senza la regola del non rimpicciolire, ed era
# il collo di bottiglia da cui passano 35 letture su 36 di quella serie: con la
# cache del processo veloce persa, la prima esecuzione successiva pubblicava un
# file di una riga sopra quello buono da tre giorni.
import csv as _csv
import datetime as _dt
import gzip as _gz
import io as _io
import os as _os

ADESSO = _dt.datetime(2026, 9, 20, 13, 0, tzinfo=_dt.timezone.utc)


def _ponte_finto(n):
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(("station", "ts", "wind_kn", "gust_kn", "dir_deg"))
    for i in range(n):
        w.writerow(["campione", "2026-09-20T%02d:%02d:00Z" % (10 + i // 6, (i % 6) * 10),
                    9.0, 12.0, 190.0])
    corpo = _gz.compress(buf.getvalue().encode("utf-8"))
    return lambda url, timeout=None: corpo


# Nel database una sola lettura (la cache e' appena stata persa), sul ramo trenta.
store.save_samples("campione", [("2026-09-20T12:00:00Z", 11.0, 15.0, 200.0)],
                   "addicted-live")
PONTE = "/tmp/gwarchivio/vivo-ponte.csv.gz"
n = archivio.scrivi_vivo_recente(PONTE, adesso=ADESSO, fetch=_ponte_finto(30))
scritte = list(_csv.reader(_io.StringIO(
    _gz.open(PONTE, "rb").read().decode("utf-8"))))[1:]
attesi = {"2026-09-20T%02d:%02d:00Z" % (10 + i // 6, (i % 6) * 10) for i in range(30)}
presenti = {r[1] for r in scritte if r[0] == "campione"}
ok(attesi <= presenti and n >= 30,
   "il ponte si FONDE con quello pubblicato: tutte e trenta le righe del ramo "
   "sono ancora la' (%d righe in tutto)" % n)
ok(any(r[1] == "2026-09-20T12:00:00Z" and float(r[2]) == 11.0 for r in scritte),
   "e a parita' di istante vince la lettura nostra, che e' la piu' fresca")


def _fetch_rotto(url, timeout=None):
    raise RuntimeError("rete giu'")


PONTE2 = "/tmp/gwarchivio/vivo-ponte2.csv.gz"
sollevata = None
try:
    archivio.scrivi_vivo_recente(PONTE2, adesso=ADESSO, fetch=_fetch_rotto)
except Exception as e:                                # noqa: BLE001
    sollevata = e
ok(isinstance(sollevata, archivio.PonteNonLetto) and not _os.path.exists(PONTE2),
   "se il file pubblicato non si legge NON si scrive niente: un ponte piu' "
   "corto e' peggio di un ponte vecchio")
main_src = open(os.path.join(QUI, "..", "gardawind", "__main__.py"),
                encoding="utf-8").read()
ok("PonteNonLetto" in main_src and "_os.remove(vivo)" in main_src,
   "e il comando veloce lo sa: pubblica live.json e lascia stare il ponte")

# ---- la curva emessa: la prima vince, come nel file ------------------------
# Due giri possono condividere lo stesso `issued_at` da quando quell'ora si
# scrive solo se la previsione e' arrivata davvero (engine.update_forecasts):
# in mezzo ci sta un riaddestramento, quindi la curva del secondo giro e'
# DIVERSA. Il file di archivio, a parita' di chiave, tiene la riga che ha gia';
# il database faceva INSERT OR REPLACE e si faceva sovrascrivere. Le due
# verita' del progetto restavano diverse per sempre, e la pagella avrebbe
# giudicato come previsione a scadenza zero una curva ricalcolata con le
# misure della giornata stessa.
EMESSA = "2026-09-19T03:20:00Z"
ORA_VALIDA = "2026-09-19T14:00:00Z"
store.save_issued_profile("Torbole", EMESSA,
                          [{"key": ORA_VALIDA, "wind": 10.0, "gust": 14.0}])
store.save_issued_profile("Torbole", EMESSA,
                          [{"key": ORA_VALIDA, "wind": 99.0, "gust": 99.0}])
_riga = store.connect().execute(
    "SELECT wind_kn FROM issued_profile WHERE place=? AND issued_at=? "
    "AND valid_hour=?", ("Torbole", EMESSA, ORA_VALIDA)).fetchone()
ok(_riga and abs(_riga["wind_kn"] - 10.0) < 1e-6,
   "sotto lo stesso run vince la curva ARRIVATA PER PRIMA, come nel file "
   "(letto: %s)" % (_riga and _riga["wind_kn"]))

# E le due verita' coincidono: quello che finisce nel file e' quello che sta
# nel database. E' la proprieta' vera, il resto e' il come.
for _p, _n, _nuove in archivio.esporta():
    pass
_mese = os.path.join(config.PROJECT_DIR, "storico", "emesse",
                     "Torbole-2026-09.csv.gz")
_nel_file = None
if os.path.exists(_mese):
    with gzip.open(_mese, "rt", encoding="utf-8") as fh:
        for _r in fh:
            _c = _r.strip().split(",")
            if len(_c) > 3 and _c[0] == EMESSA and _c[1] == ORA_VALIDA:
                _nel_file = float(_c[2])
ok(_nel_file is None or abs(_nel_file - 10.0) < 1e-6,
   "e il file dice lo stesso numero del database (%s)" % _nel_file)

print("%d controlli sull'archivio irripetibile" % passati)
