import os, sys, math, random, datetime as dt
os.environ["GARDAWIND_HOME"]="/tmp/gwhome"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
for f in os.listdir("/tmp/gwhome"):
    os.remove(os.path.join("/tmp/gwhome",f))
from gardawind import store, config, aggregate, engine, features as F, model as M, web
from gardawind.util import iso_utc, iso_hour_utc, local_hour, local_day, parse_dt_any
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
store.init()
random.seed(3)

UTC=dt.timezone.utc
start=dt.date(2024,1,1); end=dt.date(2026,8,31)
days=[]; d=start
while d<=end: days.append(d.isoformat()); d+=dt.timedelta(days=1)

# stato sinottico giornaliero + osservazioni + archivio feature coerenti
state={}
samples_t=[]; arch_rows={}; ctx_rows={pl:{} for pl in config.CONTEXT_POINTS}
for day in days:
    doy=dt.date.fromisoformat(day).timetuple().tm_yday
    seas=math.sin(2*math.pi*(doy-100)/365.25)
    tgrad=4+4*seas+random.gauss(0,2.2)
    pgrad=random.gauss(-0.3,1.1)
    cloud=min(1,max(0,random.betavariate(2,4)+0.15*(1-seas)))
    rad=max(0.05,(1.1+0.5*seas)*(1-0.75*cloud))
    w925=abs(random.gauss(11,5)); d925=random.choice([200,210,190,30,20,280])
    precip=max(0,random.gauss(-0.4,1.0)) if cloud>0.6 else 0.0
    # Ora
    zo=0.62*tgrad-1.05*pgrad+1.25*rad-2.4*cloud-1.7*precip+0.06*(w925*math.cos(math.radians(d925-204)))-3.1
    po=1/(1+math.exp(-zo)); est_o=random.random()<po
    peak_o=max(2.0, 12.5+0.52*tgrad+0.22*(w925*math.cos(math.radians(d925-204)))+2.2*rad+random.gauss(0,2.1)) if est_o else random.uniform(2,7)
    # Peler
    zp=0.95*pgrad+0.10*(w925*math.cos(math.radians(d925-24)))-1.8*cloud-1.4*precip-0.9
    pp=1/(1+math.exp(-zp)); est_p=random.random()<pp
    peak_p=max(2.0, 11.5+1.4*pgrad+0.24*(w925*math.cos(math.radians(d925-24)))+random.gauss(0,2.0)) if est_p else random.uniform(2,6)
    state[day]=dict(tgrad=tgrad,pgrad=pgrad,cloud=cloud,rad=rad,w925=w925,d925=d925,precip=precip,
                    peak_o=peak_o,peak_p=peak_p)

    base=dt.datetime.fromisoformat(day+"T00:00:00").replace(tzinfo=UTC)
    for off in range(-3,27):
        t=base+dt.timedelta(hours=off)
        if local_day(t)!=day: continue
        h=local_hour(t)
        shape_o=math.exp(-((h-15.5)/2.6)**2); shape_p=math.exp(-((h-7.0)/2.3)**2)
        wind=max(0.6, peak_o*shape_o + peak_p*shape_p + random.gauss(0,0.7))
        direction = 204 if shape_o>=shape_p else 24
        # campioni a 10 minuti
        for mnt in range(0,60,10):
            ts=t+dt.timedelta(minutes=mnt)
            samples_t.append((iso_utc(ts), max(0.0,wind+random.gauss(0,0.5)), wind*1.4, direction))
        key=iso_hour_utc(t)
        arch_rows[key]={"t2m":18+9*seas+6*math.exp(-((h-15)/5)**2),"rh":60,"dew":11,
            "precip":precip/8.0,"cloud":cloud*100,"cloud_low":cloud*80,"mslp":1015,
            "rad":900*rad*max(0,math.exp(-((h-13)/4.2)**2)),
            "w10":max(0.5,wind*0.62+random.gauss(0,0.8)),"d10":direction,"g10":wind*0.9,
            "t925":12+8*seas,"w925":w925,"d925":d925,"t850":6+8*seas,"w850":w925*1.1,"d850":d925,
            "w700":w925*1.5,"d700":d925}
        for pl,(la,lo,side) in config.CONTEXT_POINTS.items():
            north = side=="north"
            ctx_rows[pl][key]=(key,{"mslp":1015+(pgrad/2 if north else -pgrad/2),
                                    "t2m":(18+9*seas)-(tgrad/2 if north else -tgrad/2),
                                    "cloud":cloud*100,"rad":900*rad})

print("giorni:",len(days),"campioni:",len(samples_t))
store.save_samples("T0193", samples_t, "test")
n=aggregate.aggregate_station("T0193")
ok(n>20000, "aggregazione oraria: %d ore"%n)
row=store.obs_hours("T0193")[100]
ok(row["n_samples"]==6 and row["wind_mean"] is not None and row["dir_deg"] is not None, "ora aggregata completa (n=%d)"%row["n_samples"])

pt=store.point_key(config.SPOTS["Torbole-Ora"]["lat"],config.SPOTS["Torbole-Ora"]["lon"])
store.save_archive(pt, sorted(arch_rows.items()))
for pl in ctx_rows: store.save_context(pl,"arch",sorted(ctx_rows[pl].values()))
ok(store.archive_span(pt)[2]>20000, "archivio feature: %d ore"%store.archive_span(pt)[2])

# archivio giornaliero Malcesine
store.save_day_obs("malcesine", [(d, None, max(4,state[d]["peak_o"]*1.35+random.gauss(0,2))) and (d, state[d]["peak_o"]*0.6, max(4,state[d]["peak_o"]*1.35+random.gauss(0,2)), None) for d in days], "test")
store.save_archive(store.point_key(config.SPOTS["Malcesine-Ora"]["lat"],config.SPOTS["Malcesine-Ora"]["lon"]), sorted(arch_rows.items()))

for spot in ("Torbole-Ora","Torbole-Peler","Malcesine-Giorno"):
    S=engine.build_samples(spot)
    print("  %-18s campioni=%d  instaurati=%d"%(spot,len(S),sum(1 for s in S if s["established"])))
    ok(len(S)>700, "%s: campioni costruiti"%spot)

rep=engine.train_all()
for r in rep: print("  ",r)
tt=[r for r in rep if r["spot"]=="Torbole-Ora"][0]
ok(tt["status"]=="ok" and tt["usable"], "Torbole-Ora addestrato e utilizzabile")
ok(tt["mae"]<2.8, "MAE fuori campione Torbole-Ora = %.2f kn"%tt["mae"])
tp=[r for r in rep if r["spot"]=="Torbole-Peler"][0]
ok(tp["status"]=="ok", "Torbole-Peler addestrato (%s)"%tp.get("tier"))

# ---- lato previsione ----
print("\n--- serving ---")
run=iso_utc(dt.datetime.now(UTC))
today=dt.date.fromisoformat(local_day(dt.datetime.now(UTC)))
live_ctx={pl:[] for pl in config.CONTEXT_POINTS}
for k in range(0,5):
    day=(today+dt.timedelta(days=k)).isoformat()
    st=state[days[200+k]]
    base=dt.datetime.fromisoformat(day+"T00:00:00").replace(tzinfo=UTC)
    rows=[]
    for off in range(-3,27):
        t=base+dt.timedelta(hours=off)
        if local_day(t)!=day: continue
        h=local_hour(t); key=iso_hour_utc(t)
        shape=math.exp(-((h-15.5)/2.6)**2)
        rows.append((key,{"t2m":26,"rh":55,"dew":13,"precip":st["precip"]/8,"cloud":st["cloud"]*100,
          "cloud_low":st["cloud"]*80,"mslp":1015,"rad":900*st["rad"]*max(0,math.exp(-((h-13)/4.2)**2)),
          "w10":max(0.5,st["peak_o"]*0.62*shape+2),"d10":204,"g10":st["peak_o"]*0.9*shape+3,
          "t925":16,"w925":st["w925"],"d925":st["d925"],"t850":9,"w850":st["w925"]*1.1,"d850":st["d925"],
          "w700":st["w925"]*1.5,"d700":st["d925"]}))
        for pl,(la,lo,side) in config.CONTEXT_POINTS.items():
            north=side=="north"
            live_ctx[pl].append((key,{"mslp":1015+(st["pgrad"]/2 if north else -st["pgrad"]/2),
                "t2m":26-(st["tgrad"]/2 if north else -st["tgrad"]/2),"cloud":st["cloud"]*100,"rad":900*st["rad"]}))
    for mn in list(config.MODELS)[:8]:
        jit=[(k2,{kk:(vv*(1+random.gauss(0,0.07)) if isinstance(vv,(int,float)) and kk not in ("d10","d925","d850","d700") else vv) for kk,vv in v.items()}) for k2,v in rows]
        for pname in set(store.point_key(s["lat"],s["lon"]) for s in config.SPOTS.values()):
            store.save_forecast(pname, mn, run, jit)
for pl,rr in live_ctx.items(): store.save_context(pl,"live",rr)

hours,spread,nm,origin=engine.ensemble_hours("Torbole-Ora")
ok(len(hours)>80 and nm==8, "ensemble: %d ore da %d modelli, pesi %s"%(len(hours),nm,origin))
ok(all(v>=0 for v in spread.values()) and max(spread.values())>0, "dispersione calcolata (max %.2f kn)"%max(spread.values()))

prod=engine.full_product()
fo=prod["Torbole-Ora"]
ok(len(fo)>=4, "previsione su %d giorni"%len(fo))
d0=fo[0]
print("   Torbole-Ora oggi: prob=%.0f%% attesi=%.1f kn [%.1f-%.1f] finestra=%s fonte=%s giudizio=%s"%(
   d0["prob"]*100,d0["speed"],d0["lo"],d0["hi"],d0["window"] and "%02d-%02d"%(d0["window"]["from"],d0["window"]["to"]),d0["source"],d0["grade"]))
ok(d0["source"]=="appreso", "usa il modello appreso")
ok(d0["lo"]<=d0["speed"]<=d0["hi"], "banda coerente")
ok(d0["window"] is not None and 11<=d0["window"]["from"]<=19, "finestra dentro l'orario dell'Ora")
ok(len(d0["profile"])==9, "profilo orario di %d ore"%len(d0["profile"]))
lead3=[x for x in fo if x["lead"]==3]
if lead3:
    ok((lead3[0]["hi"]-lead3[0]["lo"])>(d0["hi"]-d0["lo"]), "banda piu' larga a D+3")

mg=prod["Malcesine-Giorno"]
ok(mg and mg[0]["source"]=="appreso", "Malcesine raffica di giornata addestrata")
mo=prod["Malcesine-Ora"]
ok(mo and mo[0]["source"]=="prior", "Malcesine-Ora senza storico orario -> prior dichiarato")

h=web.page_home()
ok(len(h)>9000 and "Torbole" in h and "Malcesine" in h and "%" in h, "home renderizzata (%d byte)"%len(h))
ok("<svg" in h and "polyline" in h, "grafico presente")
dg=web.page_diagnostics()
ok("MAE fuori campione" in dg and "onest" in dg and "Skill dei singoli modelli" in dg, "diagnostica renderizzata (%d byte)"%len(dg))
ok("non ancora addestrato" in dg or "prior" in dg or "si'" in dg, "stato modelli mostrato")
open("/tmp/home.html","w").write(h); open("/tmp/diag.html","w").write(dg)
print("\nOK: file di anteprima in /tmp/home.html e /tmp/diag.html")
