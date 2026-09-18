"""Tutte le localita' sulla stessa scala di vento, e Malcesine su Addicted.

Gian: "uno vuole sapere quanto vento c'e' davvero, non quanto misura la
centralina". Tre pagine che per lo stesso vento dicevano 15, 11 e 9.

Quattro cose da difendere:

  1. la curva Addicted -> Meteotrentino si applica in UN posto (store), a
     tutti i lettori, e solo al vento medio: la raffica non si tocca, e in
     archivio resta il grezzo;
  2. Torbole (Meteotrentino) e la Fraglia (che da' solo la direzione) non
     vengono toccate;
  3. Malcesine prende il vento da Addicted e la direzione dalla Fraglia, con
     lo storico dal 2014 nel progetto;
  4. la pagina dichiara la scala e il prestito, anche nell'adesso.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwscala"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwscala", ignore_errors=True)
os.makedirs("/tmp/gwscala", exist_ok=True)

from gardawind import config, engine, live, store, web
from gardawind.util import iso_utc, local_naive_to_utc, riscala, utc_now

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


store.init()
CURVA = config.SCALA_ADDICTED_A_MT

# ---- la curva ---------------------------------------------------------------
ok(all(b[0] > a[0] and b[1] >= a[1] for a, b in zip(CURVA, CURVA[1:])),
   "la curva e' monotona: un vento piu' forte non diventa mai piu' debole")
ok(abs(riscala(CURVA, 9.0) - 12.0) < 1e-9 and abs(riscala(CURVA, 10.0) - 13.15) < 1e-9,
   "sui punti restituisce il punto, in mezzo interpola (9 -> 12.0, 10 -> 13.15)")
ok(riscala(CURVA, 0.0) == 0.0 and abs(riscala(CURVA, 34.0) - 34.0 * 20.2 / 17.0) < 1e-9,
   "zero resta zero, e oltre l'ultimo punto si tiene il suo rapporto")
ok(riscala(CURVA, None) is None and riscala(None, 7.0) == 7.0,
   "None resta None, e senza curva la lettura resta com'e'")
ok(1.2 <= riscala(CURVA, 12.0) / 12.0 <= 1.4,
   "sopra gli 8 kn il fattore e' quello misurato, ~1,3 (%.2f)" % (riscala(CURVA, 12.0) / 12.0))
ok(config.scala_vento("addicted") is CURVA and config.scala_vento("meteotrentino") is None
   and config.scala_vento("meteoproject") is None,
   "la curva vale per Addicted, e per nessun'altra fonte")

# ---- 1. un posto solo, vento medio soltanto, grezzo in archivio -------------


def ora(giorno, h):
    naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=h)
    return iso_utc(local_naive_to_utc(naive))[:13]


G = "2026-07-10"
store.upsert_obs_hours("campione", [
    {"hour": ora(G, 14), "wind_mean": 9.0, "wind_max": 10.0, "gust_max": 18.0,
     "gust_rec": None, "dir_deg": None, "dir_const": None, "n_samples": 6}])
store.upsert_obs_hours("T0193", [
    {"hour": ora(G, 14), "wind_mean": 9.0, "wind_max": 10.0, "gust_max": 18.0,
     "gust_rec": None, "dir_deg": 190.0, "dir_const": 0.9, "n_samples": 6}])
rc = store.obs_hours("campione")[0]
rt = store.obs_hours("T0193")[0]
ok(abs(rc["wind_mean"] - 12.0) < 1e-9 and abs(rc["wind_max"] - 13.15) < 1e-9,
   "obs_hours: il vento medio di Campione esce sulla scala comune (9 -> 12)")
ok(rc["gust_max"] == 18.0, "e la raffica no: 18 resta 18")
ok(rt["wind_mean"] == 9.0, "Torbole non viene toccata: 9 resta 9")
ok(store._obs_hours_grezze("campione")[0]["wind_mean"] == 9.0,
   "in archivio resta il grezzo")
ts = iso_utc(utc_now() - dt.timedelta(minutes=5))
store.save_samples("campione", [(ts, 9.0, 18.0, None)], "addicted-json")
store.save_samples("T0193", [(ts, 9.0, 18.0, 190.0)], "prova")
ok(abs(store.samples_since("campione", ts[:10])[0]["wind_kn"] - 12.0) < 1e-9,
   "samples_since: anche i campioni escono in scala")
ok(abs(store.samples_recent("campione", 1)[0]["wind_kn"] - 12.0) < 1e-9
   and store.samples_recent("T0193", 1)[0]["wind_kn"] == 9.0,
   "samples_recent: idem, e Torbole no")
v = live.stazione("campione")
ok(abs(v["wind"] - 12.0) < 1e-9 and v["gust"] == 18.0,
   "l'adesso di Campione: vento in scala, raffica com'e'")
ok(v["dir"] == 190.0 and v["dir_prestito"] == "T0193",
   "e la direzione, che Addicted non ha, viene da chi la misura, dichiarata")
cc = engine.live_reading("campione")
ok(cc and abs(cc["wind"] - 12.0) < 1e-9,
   "live_reading passa dallo stesso lettore")
html = web.now_observed_html(dict(v, age_min=5.0))
ok("(Torbole)" in html, "e la cella dell'adesso scrive da quale CENTRALINA viene la freccia")
ok(config.nome_centralina("malcesine") == "Fraglia Vela"
   and "da Fraglia Vela" in web.dettagli_panel("Malcesine", []),
   "e la dice per nome: a Malcesine il prestito viene dalla Fraglia, non"
   " 'da Malcesine'")

# Nessun lettore diretto di obs_sample fuori da store: e' l'unico modo per
# cui la scala non possa mancare da qualche parte.
import inspect
for mod in (engine, live, web):
    src = inspect.getsource(mod)
    ok("FROM obs_sample" not in src,
       "%s non legge obs_sample per conto suo" % mod.__name__)

# ---- 3. Malcesine su Addicted, con la Fraglia per la direzione --------------
sp = config.SPOTS["Malcesine-Ora"]
ok(sp["station"] == "malcesine_add" and sp["source"] == "addicted"
   and sp["addicted_slug"] == "malcesine",
   "Malcesine-Ora prende il vento dalla centralina Addicted della spiaggia")
ok(sp["direzione_da"][0] == "malcesine",
   "e la direzione dalla Fraglia, per prima")
ok(config.SPOTS["Malcesine-Giorno"]["station"] == "malcesine",
   "la raffica del giorno resta della Fraglia (archivio NOAA)")
ok(("malcesine_add", "malcesine") in engine.stazioni_addicted(),
   "il canale vivo Addicted la legge")
storico = engine.storico_addicted("malcesine")
ok(len(storico) > 90000 and storico[0][0].startswith("2013-12"),
   "lo storico dal 2014 e' nel progetto: %d ore" % len(storico))
esito = engine.promuovi_storico_addicted("malcesine_add")
ok(esito.get("malcesine_add", 0) > 90000,
   "e diventa osservato di malcesine_add (%d ore)" % esito.get("malcesine_add", 0))
ok("Meteotrentino" in web.dettagli_panel("Malcesine", [])
   and "1,3 volte" in web.dettagli_panel("Malcesine", []),
   "il cassetto dei dettagli di Malcesine dichiara la scala")
print("%d controlli sulla scala" % passati)
