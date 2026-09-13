import os, sys, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import model as M, features as F
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
random.seed(21)

def mk(day, base, noise, peak_hour=None):
    f={k:0.0 for k in set(F.TIER_FULL+F.TIER_SURFACE+F.TIER_TIMING)}
    f.update(base)
    for k in list(f):
        if k not in ("doy_sin","doy_cos","raw_peak_hour"):
            f[k]=f[k]+random.gauss(0,noise)
    return f

# verita': il vento dipende da tgrad, pgrad, rad. ERA5 li vede esatti,
# le previsioni li vedono con rumore.
days=[]; truth={}
for i in range(1500):
    d="%04d-%02d-%02d"%(2012+i//365, 1+(i//30)%12, 1+i%28)
    tg=random.gauss(5,3); pg=random.gauss(-0.5,1.2); rad=random.uniform(.2,1.5)
    w=random.uniform(3,14)
    z=0.5*tg-1.0*pg+1.2*rad-3.0
    est=random.random()<1/(1+math.exp(-z))
    peak=max(0.,12+0.45*tg+0.5*w+random.gauss(0,2)) if est else random.uniform(2,7)
    ph=13+0.22*tg-0.5*pg+random.gauss(0,0.8)
    days.append(d); truth[d]=dict(tg=tg,pg=pg,rad=rad,w=w,est=est,peak=peak,ph=max(11,min(19,ph)))

def build(source, subset):
    n = 0.0 if source=="era5" else 1.1     # la previsione vede i gradienti sporchi
    out=[]
    for d in subset:
        t=truth[d]
        f={k:0.0 for k in set(F.TIER_FULL+F.TIER_SURFACE+F.TIER_TIMING)}
        f["tgrad"]=t["tg"]+random.gauss(0,n); f["pgrad"]=t["pg"]+random.gauss(0,n*0.4)
        f["rad_pre"]=t["rad"]+random.gauss(0,n*0.2); f["w10_win"]=t["w"]+random.gauss(0,n)
        f["w10_max"]=f["w10_win"]+2; f["along925"]=random.gauss(3,5)
        doy=int(d[8:10])+30*int(d[5:7]); f["doy_sin"]=math.sin(2*math.pi*doy/365); f["doy_cos"]=math.cos(2*math.pi*doy/365)
        f["raw_peak_hour"]=15.0+random.gauss(0,0.6)
        out.append({"day":d,"features":f,"peak":t["peak"],"established":t["est"],
                    "peak_hour":t["ph"],"onset_hour":None})
    return out

fc_days=days[-500:]              # previsioni: solo gli ultimi 500 giorni
fc=build("forecast", fc_days)
era=build("era5", days)          # rianalisi: tutti e 1500

chosen, cands = M.train("Torbole-Ora", {"forecast":fc, "era5":era})
for c in cands:
    print("   %-8s %-8s n=%-5d brier=%.4f mae=%s usable=%s"%(
        c["source"], c["tier"], c["n"], c["brier"],
        ("%.2f"%c["mae"]) if c["mae"] else "-", c["usable"]))
ok(chosen is not None, "un candidato viene scelto")
ok(all(c["n_eval"]==len(fc) for c in cands),
   "tutti i candidati valutati sullo STESSO insieme di %d giorni previsti"%len(fc))
ok(len({c["n_eval"] for c in cands})==1, "nessuno valutato sui propri dati di addestramento")
era_c=[c for c in cands if c["source"]=="era5"]
ok(era_c and era_c[0]["n"]>len(fc), "il candidato ERA5 si addestra su piu' giorni (%d vs %d)"%(era_c[0]["n"],len(fc)))

# il candidato ERA5 NON deve sembrare magicamente perfetto solo perche'
# i suoi ingressi di addestramento erano puliti
ok(all(c["brier"]>0.02 for c in cands), "nessun Brier irrealisticamente basso (min %.4f)"%min(c["brier"] for c in cands))

# orario
t=M.train_timing(fc)
ok(t is not None, "il modello dell'orario si addestra")
print("   orario: MAE %.0f min (riferimenti: climatologia %.0f min, ensemble %s) usable=%s"%(
    t["mae_minutes"], t["base_clim_hours"]*60,
    ("%.0f min"%(t["base_raw_hours"]*60)) if t["base_raw_hours"] else "-", t["usable"]))
ok(t["mae_minutes"]<t["base_mae_hours"]*60, "batte il miglior riferimento")
ok(t["usable"], "promosso")
lt={"payload":t["payload"],"metrics":{k:v for k,v in t.items() if k!="payload"}}
h,src=M.predict_timing(fc[0]["features"], lt, fc[0]["day"])
ok(11<=h<=19 and src=="appreso", "previsione orario: %.1f (%s)"%(h,src))
# senza modello -> climatologia o fallback
h2,s2=M.predict_timing(fc[0]["features"], None, fc[0]["day"], fallback=15.0)
ok(h2==15.0 and s2=="ensemble", "senza modello ripiega sull'ensemble e lo dichiara")
