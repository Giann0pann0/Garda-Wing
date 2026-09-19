"""Scadenze: archivio per-lead, memoria all'eta' giusta, fasce validate a se'.

Passa dal codice vero (store -> engine.build_samples -> validate.fit_band ->
model.predict), non da vettori costruiti a mano, perche' la domanda a cui deve
rispondere e' proprio se le due strade - addestramento ed esercizio -
costruiscono lo stesso vettore. E' l'errore che nessun test sui soli numeri
riesce a vedere.
"""
import os, sys, math, random, datetime as dt
os.environ["GARDAWIND_HOME"] = "/tmp/gwlead"
os.makedirs("/tmp/gwlead", exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
for f in os.listdir("/tmp/gwlead"):
    os.remove(os.path.join("/tmp/gwlead", f))
from gardawind import (store, config, aggregate, engine, features as F,
                       model as M, validate as V)
from gardawind.util import iso_utc, iso_hour_utc, local_hour, local_day
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
store.init()
random.seed(7)

UTC = dt.timezone.utc
SPOT = "Torbole-Peler"
spot = config.SPOTS[SPOT]
LEADS = (1, 2, 3)

start = dt.date(2024, 1, 1)
end = dt.date(2026, 6, 30)
days = []
d = start
while d <= end:
    days.append(d.isoformat())
    d += dt.timedelta(days=1)

# --------------------------------------------------------------------------
# Mondo finto, ma costruito come i dati veri: osservazioni a 10 minuti in una
# tabella, un archivio di predittori per la scadenza zero e uno per ciascuna
# scadenza, con l'errore che cresce con la scadenza.
# --------------------------------------------------------------------------
state = {}
g = 0.0
for day in days:
    g = 0.70 * g + random.gauss(0, 1.0)
    doy = dt.date.fromisoformat(day).timetuple().tm_yday
    seas = math.sin(2 * math.pi * (doy - 100) / 365.25)
    peak = max(2.0, 11.0 + 2.6 * g + 1.4 * seas + random.gauss(0, 1.9))
    state[day] = {"pgrad": g, "seas": seas, "peak": peak}

samples = []
for day in days:
    base = dt.datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=UTC)
    for off in range(-3, 27):
        t = base + dt.timedelta(hours=off)
        if local_day(t) != day:
            continue
        h = local_hour(t)
        shape = math.exp(-((h - 7.0) / 2.3) ** 2)
        wind = max(0.5, state[day]["peak"] * shape + random.gauss(0, 0.5))
        for mnt in range(0, 60, 10):
            ts = t + dt.timedelta(minutes=mnt)
            samples.append((iso_utc(ts), max(0.0, wind + random.gauss(0, 0.4)),
                            wind * 1.4, 24.0))
store.save_samples("T0193", samples, "test")
nh = aggregate.aggregate_station("T0193")
ok(nh > 15000, "osservazioni aggregate: %d ore" % nh)


def archive_for(lead):
    """Predittori come li vedeva un run emesso `lead` giorni prima.

    Ritorna anche il gradiente degradato per giorno, perche' DEVE finire anche
    nel contesto sinottico. Salvare il contesto con il gradiente vero a tutte le
    scadenze e' un errore facilissimo da fare (l'ho fatto scrivendo questo test)
    e non lascia traccia: il modello legge la pressione esatta dal contesto,
    ignora il vento degradato, e l'errore a D+3 risulta identico a quello a D+0.
    Nel prodotto e' il motivo per cui backfill_lead_features scarica anche il
    contesto dall'archivio delle run precedenti, non da quello ordinario.
    """
    rows = {}
    pg_by_day = {}
    for day in days:
        # Degrado deliberatamente forte con la scadenza: serve a poter
        # distinguere le fasce. Nei dati veri il degrado c'e' ma e' piu'
        # gentile, ed e' proprio quello che la validazione deve misurare.
        err = random.gauss(0, 0.25 + 1.6 * lead)
        pg = state[day]["pgrad"] + err
        pg_by_day[day] = pg
        seas = state[day]["seas"]
        base = dt.datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=UTC)
        for off in range(-3, 27):
            t = base + dt.timedelta(hours=off)
            if local_day(t) != day:
                continue
            h = local_hour(t)
            shape = math.exp(-((h - 7.0) / 2.3) ** 2)
            w = max(0.4, (10.5 + 2.5 * pg) * shape * 0.62 + random.gauss(0, 0.5))
            rows[iso_hour_utc(t)] = {
                "t2m": 14 + 9 * seas, "rh": 65, "dew": 9, "precip": 0.0,
                "cloud": 40, "cloud_low": 30, "mslp": 1015,
                "rad": 500 * max(0, math.exp(-((h - 13) / 4.2) ** 2)),
                "w10": w, "d10": 24.0, "g10": w * 1.4,
                "t925": 10 + 8 * seas, "w925": abs(10 + 2 * pg), "d925": 24.0,
                "t850": 5 + 8 * seas, "w850": 12, "d850": 24.0,
                "w700": 18, "d700": 24.0}
    return rows, pg_by_day


ctx_of = {}
for source in ["forecast"] + ["lead%d" % l for l in LEADS]:
    rows, pg_lead = archive_for(engine.source_lead(source))
    store.save_archive(store.point_key(spot["lat"], spot["lon"], source),
                       sorted(rows.items()))
    kind = "arch" if source == "forecast" else source
    for pl, (la, lo, side) in config.CONTEXT_POINTS.items():
        north = side == "north"
        crows = []
        for key in sorted(rows):
            day = local_day(__import__("gardawind.util", fromlist=["x"]).parse_dt_any(key))
            pg = pg_lead.get(day, 0.0)
            crows.append((key, {"mslp": 1015 + (pg / 2 if north else -pg / 2),
                                "t2m": 14, "cloud": 40, "rad": 500}))
        store.save_context(pl, kind, crows)
    ctx_of[source] = True

ok(store.archive_span(store.point_key(spot["lat"], spot["lon"], "lead3"))[2] > 15000,
   "archivio della scadenza 3 separato da quello della scadenza 0")
ok(store.archive_span(store.point_key(spot["lat"], spot["lon"], "forecast"))[2] > 15000,
   "e l'archivio ordinario e' ancora al suo posto")

# --------------------------------------------------------------------------
# 1. build_samples prende la memoria all'eta' della scadenza
# --------------------------------------------------------------------------
by_lead = {}
for lead in (0,) + LEADS:
    src = "forecast" if lead == 0 else "lead%d" % lead
    by_lead[lead] = engine.build_samples(SPOT, src)
    ok(len(by_lead[lead]) > 600, "scadenza %d: %d campioni" % (lead, len(by_lead[lead])))

targets = engine._targets(SPOT)
bad = []
for lead, rows in by_lead.items():
    for s in rows[:200]:
        atteso_giorno = (dt.date.fromisoformat(s["day"])
                         - dt.timedelta(days=lead + 1)).isoformat()
        atteso = targets.get(atteso_giorno)
        # Dove quel giorno non c'e', la memoria NON e' zero nodi: e' il valore
        # neutro (la mediana del picco), lo stesso che riceve la previsione in
        # esercizio. Lo zero era l'affermazione piu' forte possibile nella
        # direzione sbagliata, e faceva crollare la probabilita' all'1% su
        # tutto l'orizzonte quando la centralina taceva qualche giorno.
        atteso_val = atteso[0] if atteso else engine.memoria_predefinita(SPOT)
        if abs(s["features"]["persist_obs"] - atteso_val) > 1e-9:
            bad.append((lead, s["day"]))
        if s["features"]["persist_age"] != lead + 1:
            bad.append((lead, s["day"], "eta"))
ok(not bad, "la memoria e' il picco del giorno T-(scadenza+1), non T-1 (%d anomalie)"
   % len(bad))

# Il valore deve DAVVERO cambiare con la scadenza, altrimenti il test sopra
# passerebbe anche con un archivio costante.
diverse = sum(1 for a, b in zip(by_lead[0][:300], by_lead[3][:300])
              if abs(a["features"]["persist_obs"] - b["features"]["persist_obs"]) > 0.01)
ok(diverse > 250, "la memoria a D+0 e a D+3 sono ricordi diversi (%d/300)" % diverse)

# E il predittore d'ensemble deve peggiorare con la scadenza: se fosse lo
# stesso archivio replicato, tutte le metriche per scadenza sarebbero una copia.
from gardawind.util import mean
corr = {}
for lead, rows in by_lead.items():
    err = mean([abs(s["features"]["w10_win"] * 1.6 - s["peak"]) for s in rows])
    corr[lead] = err
print("   errore del solo vento grezzo per scadenza: " +
      ", ".join("D+%d=%.2f" % (l, v) for l, v in sorted(corr.items())))
ok(corr[3] > corr[0], "il predittore grezzo peggiora con la scadenza (%.2f -> %.2f)"
   % (corr[0], corr[3]))

# --------------------------------------------------------------------------
# 2. Nessun campione contiene informazione posteriore all'emissione
# --------------------------------------------------------------------------
viol = 0
for lead, rows in by_lead.items():
    for s in rows:
        age = int(s["features"]["persist_age"])
        mem = (dt.date.fromisoformat(s["day"]) - dt.timedelta(days=age))
        issue = (dt.date.fromisoformat(s["day"]) - dt.timedelta(days=lead))
        if mem >= issue:
            viol += 1
ok(viol == 0, "nessuno dei %d campioni usa un giorno non concluso all'emissione"
   % sum(len(v) for v in by_lead.values()))

# --------------------------------------------------------------------------
# 3. Fasce: ognuna con i propri campioni, le proprie metriche, la propria banda
# --------------------------------------------------------------------------
fasce = [("short", (0, 1)), ("medium", (2, 3))]
rep = engine.train_bands(SPOT, by_lead=by_lead, bands=fasce)
for line in rep:
    print("   " + str(line))
ok(all(r.get("status") == "ok" for r in rep), "entrambe le fasce addestrate")

short = store.load_learned(SPOT, "daily@short")
medium = store.load_learned(SPOT, "daily@medium")
ok(short and medium, "due modelli distinti salvati nello store")
ok(short["payload"]["lead_band"] == "short"
   and medium["payload"]["lead_band"] == "medium",
   "ogni modello porta scritta la fascia a cui appartiene")
ok(short["payload"]["occurrence"] != medium["payload"]["occurrence"],
   "i coefficienti delle due fasce sono diversi: non e' lo stesso modello copiato")

ms, mm = short["metrics"], medium["metrics"]
print("   short  MAE %.2f (grezzo %s)  Brier %.3f (clim %.3f)"
      % (ms["intensity"]["mae"], round(ms["intensity"]["mae_raw"], 2),
         ms["prob"]["brier"], ms["prob"]["brier_base"]))
print("   medium MAE %.2f (grezzo %s)  Brier %.3f (clim %.3f)"
      % (mm["intensity"]["mae"], round(mm["intensity"]["mae_raw"], 2),
         mm["prob"]["brier"], mm["prob"]["brier_base"]))
ok(mm["intensity"]["mae"] > ms["intensity"]["mae"],
   "l'errore della fascia lunga e' maggiore di quello della corta")
qs = short["payload"]["q90"] - short["payload"]["q10"]
qm = medium["payload"]["q90"] - medium["payload"]["q10"]
ok(qm > qs, "e la banda empirica e' piu' larga (%.1f kn contro %.1f)" % (qm, qs))

ok(all("lead" in e and "n_test_days" in e for e in ms["per_lead"].values()),
   "metriche separate per singola scadenza dentro la fascia")
ok(set(int(k) for k in ms["per_lead"]) == {0, 1},
   "la fascia corta riporta D+0 e D+1 separatamente: %s" % sorted(ms["per_lead"]))

# --------------------------------------------------------------------------
# 4. In esercizio ogni scadenza pesca il modello della propria fascia
# --------------------------------------------------------------------------
banda = engine.learned_by_band(SPOT)
ok(set(banda) >= {"short", "medium"}, "modelli per fascia rileggibili: %s" % sorted(banda))
feats = by_lead[3][400]["features"]
p_med = M.predict(SPOT, feats, banda["medium"], 3, spread_kn=3.0, direction=24.0)
p_shortmodel_at3 = M.predict(SPOT, feats, banda["short"], 3, spread_kn=3.0, direction=24.0)
ok(p_med["lead_band"] == "medium", "D+3 chiede alla fascia medium")
# La banda misurata si pubblica solo se lo stadio dell'intensita' ha superato
# la propria porta A QUESTA FASCIA. Qui la fascia medium batte il vento grezzo
# ma non la climatologia in modo distinguibile dal rumore, quindi non la
# pubblica: e' il comportamento giusto, non un difetto del test.
promossa = bool(mm.get("usable"))
print("   fascia medium: intensita' promossa=%s (guadagno %s), probabilita' promossa=%s (%s)"
      % (promossa, mm["gain_int"].get("significativo"),
         mm.get("usable_occurrence"), mm["gain_prob"].get("significativo")))
ok(p_med["band_source"] == ("residui misurati" if promossa
                            else "dispersione d'ensemble"),
   "la banda a D+3 viene da %s, coerente con la promozione" % p_med["band_source"])
ok(p_med["validata_int"] == promossa and p_med["validata_prob"] == bool(mm.get("usable_occurrence")),
   "e lo stato dichiarato per stadio combacia con le porte superate")
ok(p_shortmodel_at3["validata"] is False,
   "il modello della fascia corta applicato a D+3 non si dichiara validato")
ok(p_shortmodel_at3["band_source"] == "dispersione d'ensemble",
   "e non presta i propri residui a una scadenza che non ha provato")

# La previsione a una scadenza priva di modello non deve ereditare credito.
p_far = M.predict(SPOT, feats, banda.get("long"), 6, spread_kn=3.0, direction=24.0)
ok(p_far["validata"] is False and p_far["lead_band"] == "long",
   "D+6 senza modello di fascia: dichiarata non validata")

print("\nfine")
