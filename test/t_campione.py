"""Campione: la terza localita', con la direzione in prestito.

Tre cose da difendere:

  1. una localita' e' una riga di config: pagina, navigazione, file, riquadri
     e grafici nascono da PLACES/SPOTS e non vanno toccati altrove;
  2. la direzione che Addicted non misura si prende in prestito da una
     centralina vicina, in UN posto (store.obs_hours), dichiarata riga per
     riga, e nella tabella non si scrive niente;
  3. lo storico Addicted diventa osservato solo per le stazioni che hanno
     Addicted come fonte, e non sovrascrive il canale vivo.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwcampione"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwcampione", ignore_errors=True)
os.makedirs("/tmp/gwcampione", exist_ok=True)

from gardawind import config, engine, store, web
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

# ---- 1. una riga di config -------------------------------------------------
ok("Campione" in config.PLACES and config.PLACES.index("Campione") == 2,
   "Campione e' la terza localita'")
ok({"Campione-Ora", "Campione-Peler"} <= set(config.SPOT_ORDER),
   "con i suoi due regimi")
ok(config.SPOTS["Campione-Ora"]["station"] == "campione"
   and config.SPOTS["Campione-Ora"]["source"] == "addicted",
   "la centralina e' quella Addicted del Vela Club")
ok(("campione", "campione") in engine.stazioni_addicted()
   and all(st != "T0193" for st, _s in engine.stazioni_addicted()),
   "ha Addicted come fonte, e Torbole resta Meteotrentino")
ok(web._slug("Campione") == "campione" and 'href="/campione"' in web.nav_luoghi("Torbole"),
   "la pagina e la navigazione nascono da config")
ok(addicted.url_json("2026-09-18", "campione")
   == "https://it.addicted-sports.com/forecast/gardasee/campione/?json=wind&from=2026-09-18",
   "l'indirizzo della serie oraria e' quello della stazione, sullo stesso schema")
ok(addicted.url_json("2026-09-18") == addicted.url_json("2026-09-18", "torbole"),
   "e senza stazione resta Torbole, com'era")
ok("body.p3{" in web.CSS, "la terza localita' ha il suo colore")


# ---- 2. la direzione in prestito -------------------------------------------
def ora(giorno, h):
    naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=h)
    return iso_utc(local_naive_to_utc(naive))[:13]


G = "2026-07-10"
# Campione: vento senza direzione. Malcesine: direzione solo alle 14 e 15.
# Torbole: direzione a tutte le ore, ma diversa - deve entrare solo dove
# Malcesine manca.
store.upsert_obs_hours("campione", [
    {"hour": ora(G, h), "wind_mean": 15.0, "wind_max": None, "gust_max": 24.0,
     "gust_rec": None, "dir_deg": None, "dir_const": None, "n_samples": 6}
    for h in (13, 14, 15, 16)])
store.upsert_obs_hours("malcesine", [
    {"hour": ora(G, h), "wind_mean": 14.0, "wind_max": 15.0, "gust_max": 22.0,
     "gust_rec": None, "dir_deg": 190.0, "dir_const": 0.95, "n_samples": 6}
    for h in (14, 15)])
store.upsert_obs_hours("T0193", [
    {"hour": ora(G, h), "wind_mean": 13.0, "wind_max": 14.0, "gust_max": 20.0,
     "gust_rec": None, "dir_deg": 200.0, "dir_const": 0.9, "n_samples": 6}
    for h in (13, 14, 15, 16)])

righe = {r["hour"]: r for r in store.obs_hours("campione")}
ok(len(righe) == 4, "le quattro ore di Campione ci sono")
ok(righe[ora(G, 14)]["dir_deg"] == 190.0 and righe[ora(G, 14)]["dir_prestito"] == "malcesine",
   "alle 14 la direzione viene da Malcesine, e lo dice")
ok(righe[ora(G, 13)]["dir_deg"] == 200.0 and righe[ora(G, 13)]["dir_prestito"] == "T0193",
   "alle 13, dove Malcesine non c'e', viene da Torbole, e lo dice")
ok(righe[ora(G, 14)]["dir_const"] == 0.95,
   "e con la direzione viaggia la sua costanza")
grezze = {r["hour"]: r for r in store._obs_hours_grezze("campione")}
ok(all(r["dir_deg"] is None for r in grezze.values()),
   "nella tabella non si scrive niente: obs_hour di Campione resta senza direzione")
ok(all(r["dir_prestito"] is None for r in store.obs_hours("T0193")),
   "e Torbole, che la misura, non ha prestiti")
# Il bersaglio del modello legge da store.obs_hours: con la direzione in
# prestito nel settore dell'Ora la giornata e' "entrata".
targets = engine._compute_targets("Campione-Ora")
ok(G in targets and targets[G][1],
   "il bersaglio vede un Ora entrato a Campione grazie alla direzione in prestito")
store.upsert_obs_hours("T0193", [
    {"hour": ora(G, h), "wind_mean": 13.0, "wind_max": 14.0, "gust_max": 20.0,
     "gust_rec": None, "dir_deg": 20.0, "dir_const": 0.9, "n_samples": 6}
    for h in (13, 16)])
store.upsert_obs_hours("malcesine", [
    {"hour": ora(G, h), "wind_mean": 14.0, "wind_max": 15.0, "gust_max": 22.0,
     "gust_rec": None, "dir_deg": 20.0, "dir_const": 0.95, "n_samples": 6}
    for h in (14, 15)])
targets = engine._compute_targets("Campione-Ora")
ok(G in targets and not targets[G][1],
   "e con un nordico sulle centraline vicine quello stesso vento NON e' Ora")
# Le donatrici si dicono col nome della CENTRALINA, non del luogo: a
# Malcesine il donatore e' la Fraglia, e "in prestito da Malcesine" sarebbe
# vero e inutile.
_det = web.dettagli_panel("Campione", [])
ok("prestito" in _det and "Fraglia Vela" in _det and "Torbole" in _det,
   "il cassetto dei dettagli dichiara il prestito, e da quali centraline")
ok("prestito" not in web.dettagli_panel("Torbole", []),
   "e a Torbole no")

# ---- 3. lo storico Addicted diventa osservato -------------------------------
c = store.connect()
for h, w, g in ((10, 8.0, 14.0), (11, 9.0, 15.0), (14, 99.0, 99.0)):
    c.execute("INSERT OR REPLACE INTO addicted_hour(station,hour,wind_mean_kn,"
              "hourly_max_kn,source,series_group,raw_origin) VALUES(?,?,?,?,?,?,?)",
              ("campione", ora(G, h) + ":00:00Z", w, g, "addicted-sports-history",
               "campione", "prova"))
    c.execute("INSERT OR REPLACE INTO addicted_hour(station,hour,wind_mean_kn,"
              "hourly_max_kn,source,series_group,raw_origin) VALUES(?,?,?,?,?,?,?)",
              ("torbole", ora(G, h) + ":00:00Z", w, g, "addicted-sports-history",
               "torbole", "prova"))
c.commit()
esito = engine.promuovi_storico_addicted("campione")
ok(esito == {"campione": 2}, "promosse le ore che mancavano, e solo quelle: %s" % esito)
righe = {r["hour"]: r for r in store._obs_hours_grezze("campione")}
ok(righe[ora(G, 10)]["wind_mean"] == 8.0 and righe[ora(G, 10)]["gust_max"] == 14.0
   and righe[ora(G, 10)]["n_samples"] == engine.N_CAMPIONI_ORA_ADDICTED,
   "con medio, massimo e il numero di campioni dichiarato")
ok(righe[ora(G, 14)]["wind_mean"] == 15.0,
   "l'ora che c'era gia' dal canale vivo NON viene sovrascritta dallo storico")
ok(not store._obs_hours_grezze("torbole") and
   all(r["wind_mean"] == 13.0 for r in store._obs_hours_grezze("T0193")),
   "e Torbole non viene toccata: la sua pagina mostra Meteotrentino, non Addicted")

# Il canale vivo scrive obs_hour E un campione per ora, senza direzione.
n = engine.salva_ore_addicted("campione", [(ora(G, 17) + ":00:00Z", 12.0, 19.0, None)])
ok(n == 1 and store._obs_hours_grezze("campione", ora(G, 17), ora(G, 17))[0]["wind_mean"] == 12.0,
   "la lettura viva finisce in obs_hour")
camp = list(c.execute("SELECT wind_kn, gust_kn, dir_deg, source FROM obs_sample "
                      "WHERE station='campione'"))
ok(len(camp) == 1 and camp[0][0] == 12.0 and camp[0][2] is None
   and camp[0][3] == "addicted-json",
   "e in obs_sample, cosi' l'adesso ha da leggere - senza direzione inventata")

# ---- 4. lo storico nel progetto, per il database di GitHub -----------------
# Il censimento Addicted e' stato fatto una volta, sul Mac; il database con
# cui GitHub costruisce il sito e' un altro. Senza il file nel progetto,
# Campione online sarebbe rimasta senza storico e senza modello.
c.execute("DELETE FROM addicted_hour WHERE station='campione'")
c.commit()
dal_file = engine.storico_addicted("campione")
ok(len(dal_file) > 60000 and dal_file[0][0].startswith("2017-10")
   and all(isinstance(m, float) for _h, m, _g in dal_file[:100]),
   "senza addicted_hour lo storico viene dal file nel progetto: %d ore dal %s"
   % (len(dal_file), dal_file[0][0][:10] if dal_file else "?"))
ok(engine.storico_addicted("brenzone") == [],
   "e per una stazione senza file ne' tabella, niente: non si inventa")
esito = engine.promuovi_storico_addicted("campione")
ok(esito.get("campione", 0) > 60000,
   "e la promozione le porta in obs_hour (%d)" % esito.get("campione", 0))

# ---- 5. una localita' nuova non pubblica il modello grezzo ------------------
# Il difetto visto in pagina il 19/09: Campione aveva 66.507 ore di
# osservazioni e NESSUN modello, e i numeri pubblicati erano il prior fisico,
# cioe' il vento grezzo d'ensemble. Due cause, entrambe strutturali:
# i predittori storici del suo punto si scaricavano solo allo scadere di un
# orologio, e dove il modello manca la previsione ripiegava sul prior.
from gardawind import model as M  # noqa: E402

PUNTO = store.point_key(config.SPOTS["Campione-Ora"]["lat"],
                        config.SPOTS["Campione-Ora"]["lon"])

# a) la copertura, non l'orologio
scoperti = dict((p, (ha, serve)) for p, ha, serve in engine.predittori_scoperti())
ok(PUNTO in scoperti and scoperti[PUNTO][0] is None,
   "il punto di Campione e' dichiarato scoperto: osservazioni dal %s, predittori nessuno"
   % scoperti[PUNTO][1])
ok(scoperti[PUNTO][1] >= "2021",
   "e cio' che serve e' limitato dall'orizzonte dell'archivio, non il 2017 (%s)"
   % scoperti[PUNTO][1])
# Due punti diversi hanno bisogni diversi: Torbole misura dal 2012, Campione
# dal 2017, e chiedere a entrambi la stessa data era traffico buttato.
ok(engine._inizio_utile(["campione"], "2010-01-01") == "2017-10-19"
   and engine._inizio_utile(["T0193"], "2010-01-01")
   != engine._inizio_utile(["campione"], "2010-01-01"),
   "ogni punto parte da dove partono le SUE osservazioni")

store.save_archive(PUNTO, [(scoperti[PUNTO][1] + "T12:00:00Z", {"w10": 9.0})])
ok(any(p == PUNTO for p, _h, _s in engine.predittori_scoperti()) is False,
   "appena i predittori arrivano dove arrivano le osservazioni, non e' piu' scoperto")
c.execute("DELETE FROM arch_hour WHERE point=?", (PUNTO,))
c.commit()
ok(any(p == PUNTO for p, _h, _s in engine.predittori_scoperti()),
   "e se si svuotano torna scoperto")
store.meta_set("predittori_tentati_%s" % PUNTO, "2000-01-01")
ok(all(p != PUNTO for p, _h, _s in engine.predittori_scoperti()),
   "ma un punto GIA' tentato da quella data non e' scoperto: riprovare a ogni "
   "ciclo sarebbe traffico infinito")
store.meta_set("predittori_tentati_%s" % PUNTO, "2099-01-01")

# b) dove il modello manca, la previsione e' la climatologia MISURATA
clim = engine.climatologia_osservata("Campione-Ora")
ok(clim and clim["n"] > 2000 and clim["clim_median"] is not None,
   "la climatologia osservata si calcola dalle sole osservazioni: %s giornate, "
   "mediana del picco %.1f kn"
   % ((clim or {}).get("n"), (clim or {}).get("clim_median") or -1))
ok(clim["clim_median"] >= config.SPOTS["Campione-Ora"]["min_kn"],
   "ed e' la mediana delle giornate ENTRATE, quindi non sotto la soglia (%.1f)"
   % clim["clim_median"])
ok(0.0 < clim["base_rate"] < 1.0 and clim["solo_climatologia"],
   "viaggia con la frequenza d'ingresso, e si dichiara per quello che e'")
salvata = engine._salva_climatologia("Campione-Ora", "pochi dati: 4 giornate")
ok(salvata is not None
   and store.load_learned("Campione-Ora", "daily")["metrics"]["solo_climatologia"],
   "e finisce in archivio come il modello che non c'e'")

# Il numero pubblicato cambia, e cambia la parola che lo accompagna.
finti = {"w10_win": 4.0, "g10_win": 6.0, "w10_max": 5.0, "pgrad": 1.0,
         "tgrad": 1.0, "doy_sin": 0.0, "doy_cos": 1.0}
senza = M.predict("Campione-Ora", finti, None, 0, 3.0)
con = M.predict("Campione-Ora", finti,
                store.load_learned("Campione-Ora", "daily"), 0, 3.0)
ok(senza["source_int"] == "prior" and con["source_int"] == "climatologia",
   "senza nulla in archivio la previsione e' il modello grezzo; con la "
   "climatologia e' una misura")
ok(con["speed"] > senza["speed"],
   "e il numero sale, perche' il modello grezzo sul Garda legge meno del vero "
   "(%.1f -> %.1f kn)" % (senza["speed"], con["speed"]))

# c) un modello vero non viene declassato da un giro andato male
store.save_learned("Campione-Ora", "daily", "full", 1200, {"tier": "full"},
                   {"tier": "full", "usable": True, "n": 1200})
ok(engine._salva_climatologia("Campione-Ora", "pochi dati") is None
   and store.load_learned("Campione-Ora", "daily")["tier"] == "full",
   "la climatologia non sovrascrive un modello appreso")

# d) la pagina di diagnostica dice PERCHE', non solo 'non ancora addestrato'
c.execute("DELETE FROM learned WHERE spot='Campione-Ora'")
c.commit()
engine._salva_climatologia("Campione-Ora", "pochi dati: 4 giornate allineate")
diag = web.page_diagnostics()
ok("climatologia misurata" in diag and "4 giornate allineate" in diag,
   "la diagnostica dichiara il motivo e cosa si pubblica al suo posto")
riga = [r for r in diag.split("<tr>") if "Campione · Ora" in r]
ok(riga and "non ancora addestrato" not in riga[0],
   "e la riga di Campione non viene liquidata con 'non ancora addestrato'")
print("%d controlli su Campione (totale)" % passati)
