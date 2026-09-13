import os, sys, datetime as dt, math
os.environ["GARDAWIND_HOME"]="/tmp/gwcold"
import shutil; shutil.rmtree("/tmp/gwcold", ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import store, config, engine, web, model as M, features as F
from gardawind.util import iso_utc, iso_hour_utc, local_day, local_hour
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
store.init()
UTC=dt.timezone.utc

# --- 1. database completamente vuoto ---
prod=engine.full_product(force=True)
ok(all(v==[] for v in prod.values()), "database vuoto: nessuna previsione, nessuna eccezione")
h=web.page_home()
ok("Sto raccogliendo i dati" in h, "la home dice che sta raccogliendo invece di mostrare il vuoto")
d=web.page_diagnostics()
ok("non ancora addestrato" in d, "diagnostica onesta a freddo")

# --- 2. previsioni ma nessuna osservazione, nessun contesto, nessun modello ---
run=iso_utc(dt.datetime.now(UTC))
today=dt.date.fromisoformat(local_day(dt.datetime.now(UTC)))
for k in range(3):
    day=(today+dt.timedelta(days=k)).isoformat()
    base=dt.datetime.fromisoformat(day+"T00:00:00").replace(tzinfo=UTC)
    rows=[]
    for off in range(-3,27):
        t=base+dt.timedelta(hours=off)
        if local_day(t)!=day: continue
        hh=local_hour(t); sh=math.exp(-((hh-15.5)/2.8)**2)
        rows.append((iso_hour_utc(t),{"t2m":26,"rh":50,"dew":12,"precip":0,"cloud":10,"cloud_low":0,
          "mslp":1015,"rad":800*max(0,math.exp(-((hh-13)/4)**2)),"w10":3+11*sh,"d10":204,"g10":5+15*sh,
          "t925":16,"w925":13,"d925":200,"t850":9,"w850":15,"d850":205,"w700":22,"d700":210}))
    for mn in list(config.MODELS)[:4]:
        for pn in set(store.point_key(s["lat"],s["lon"]) for s in config.SPOTS.values()):
            store.save_forecast(pn, mn, run, rows)

prod=engine.full_product(force=True)
fo=prod["Torbole-Ora"]
ok(len(fo)>=3, "previsione prodotta senza contesto e senza modello (%d giorni)"%len(fo))
ok(fo[0]["source"]=="prior", "dichiara apertamente la stima fisica")
ok(0<fo[0]["prob"]<1 and fo[0]["speed"]>0, "prior: prob=%.2f attesi=%.1f kn"%(fo[0]["prob"],fo[0]["speed"]))
ok(fo[0]["lo"]<fo[0]["speed"]<fo[0]["hi"] and (fo[0]["hi"]-fo[0]["lo"])>4, "banda larga senza calibrazione (%.1f kn)"%(fo[0]["hi"]-fo[0]["lo"]))
ok(fo[0]["n_models"]==4 and fo[0]["weights"]=="prior", "4 modelli, pesi da prior")
ok(fo[0]["window"] is not None, "finestra calcolata anche senza storico")
h=web.page_home()
ok("stima fisica di partenza" in h, "la scheda avvisa che non e' ancora calibrata")
ok("Torbole" in h and "Malcesine" in h and "%" in h, "home completa a freddo (%d byte)"%len(h))

# --- 3. un solo modello disponibile (dispersione non calcolabile) ---
store.connect().execute("DELETE FROM fc_hour WHERE model<>?", (list(config.MODELS)[0],)); store.connect().commit()
engine.invalidate_product()
prod=engine.full_product(force=True)
sp=prod["Torbole-Ora"][0]["spread"]
ok(prod["Torbole-Ora"] and sp>=4.0, "un solo modello: dispersione portata a un minimo prudenziale (%.1f kn) invece di 0"%sp)

# --- 4. addestramento con dati insufficienti ---
rep=engine.train_all()
ok(all(r["status"]=="pochi dati" for r in rep), "addestramento rifiutato per mancanza di dati, senza inventare nulla")

# --- 5. osservazioni con buchi: i giorni scoperti vanno ESCLUSI, non azzerati ---
samples=[]
for k in range(1,40):
    day=(today-dt.timedelta(days=k))
    base=dt.datetime.fromisoformat(day.isoformat()+"T00:00:00").replace(tzinfo=UTC)
    hours = [11,12] if k%3==0 else list(range(11,20))   # un giorno su tre e' coperto male
    for off in range(-3,27):
        t=base+dt.timedelta(hours=off)
        if local_day(t)!=day.isoformat(): continue
        if local_hour(t) not in hours: continue
        for mnt in (0,10,20,30,40,50):
            samples.append((iso_utc(t+dt.timedelta(minutes=mnt)), 14.0, 19.0, 204.0))
store.save_samples("T0193", samples, "test")
from gardawind import aggregate; aggregate.aggregate_station("T0193")
tg=engine._targets("Torbole-Ora", use_cache=False)
ok(len(tg)==26 and all(v[0]==14.0 for v in tg.values()),
   "13 giorni con copertura insufficiente esclusi: %d giorni usabili su 39"%len(tg))
