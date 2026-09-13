import os
import sys, math, random; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import model as M, features as F
from gardawind.util import sigmoid, mean, brier
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)

random.seed(11)
def make(n, signal=True):
    S=[]
    for i in range(n):
        day="2024-%02d-%02d"%(1+(i//28)%12, 1+i%28)
        f={k:0.0 for k in F.TIER_FULL}
        f["w10_win"]=random.uniform(3,14)
        f["along925"]=random.gauss(2,6)
        f["cross925"]=abs(random.gauss(4,3))
        f["tgrad"]=random.gauss(5,3)
        f["pgrad"]=random.gauss(-0.5,1.2)
        f["rad_pre"]=random.uniform(0.2,1.5)
        f["cloud_win"]=random.uniform(0,1)
        f["precip"]=max(0,random.gauss(0,0.8))
        f["stab850"]=random.gauss(-15,3); f["stab925"]=random.gauss(-8,2)
        f["w700"]=abs(random.gauss(20,8)); f["along700"]=random.gauss(0,10)
        f["dewdep"]=random.uniform(2,14); f["cloud_cool"]=random.uniform(0,1)
        f["breeze"]=random.uniform(0,5); f["w10_max"]=f["w10_win"]+random.uniform(0,4)
        f["along10"]=random.gauss(3,4); f["persist_obs"]=random.uniform(0,20); f["persist_age"]=1.0
        doy=1+i%365; f["doy_sin"]=math.sin(2*math.pi*doy/365); f["doy_cos"]=math.cos(2*math.pi*doy/365)
        if signal:
            z=0.55*f["tgrad"]-1.1*f["pgrad"]+1.3*f["rad_pre"]-2.2*f["cloud_win"]-1.6*f["precip"]+0.09*f["along925"]-3.0
            p=sigmoid(z); est=1 if random.random()<p else 0
            peak=max(0.0, 11+0.42*f["tgrad"]+0.30*f["along925"]+0.55*f["w10_win"]+random.gauss(0,2.0)) if est else random.uniform(2,7)
        else:
            est=1 if random.random()<0.45 else 0
            peak=random.uniform(4,22)
        S.append({"day":day,"features":f,"peak":peak,"established":bool(est)})
    return S

S=make(700)
chosen,all_r=M.train("Torbole-Ora",S)
ok(chosen is not None, "train restituisce un modello")
print("   livelli:", [(r["tier"], r["n"], round(r["brier"],4) if r["brier"] else None, round(r["brier_base"],4) if r["brier_base"] else None, round(r["mae"],2) if r["mae"] else None, round(r["mae_base"],2) if r["mae_base"] else None, r["usable"]) for r in all_r])
ok(chosen["usable"], "il livello scelto e' utilizzabile (%s)"%chosen["tier"])
ok(chosen["brier"]<chosen["brier_base"], "Brier batte la frequenza climatologica (%.4f < %.4f)"%(chosen["brier"],chosen["brier_base"]))
ok(chosen["mae"]<chosen["mae_base"], "MAE batte i riferimenti (%.2f < %.2f)"%(chosen["mae"],chosen["mae_base"]))
ok(chosen["tier"] in ("reduced","full"), "con 700 giorni sale a un livello ricco (%s)"%chosen["tier"])

cal=chosen["calibration"]
vals=[b[2] for b in cal]
ok(all(vals[i]<=vals[i+1]+1e-12 for i in range(len(vals)-1)), "calibrazione isotonica monotona (%d blocchi)"%len(cal))

# previsione
learned={"payload":M.serialize(chosen),"metrics":M.metrics_of(chosen)}
p0=M.predict("Torbole-Ora",S[0]["features"],learned,lead_days=0,spread_kn=3)
p1=M.predict("Torbole-Ora",S[0]["features"],learned,lead_days=1,spread_kn=3)
p3=M.predict("Torbole-Ora",S[0]["features"],learned,lead_days=3,spread_kn=3)
ok(p1["source"]=="appreso", "previsione dichiara la fonte 'appreso'")
ok(p1["lo"]<p1["speed"]<p1["hi"], "banda coerente (%.1f<%.1f<%.1f)"%(p1["lo"],p1["speed"],p1["hi"]))
# Il modello dell'archivio ordinario descrive la scadenza zero: li' presta i
# propri residui, oltre no. Al posto dei vecchi moltiplicatori a mano, la
# differenza fra le due bande ha ora un'origine dichiarata.
ok(p0["band_source"]=="residui misurati", "a D+0 la banda viene dai residui misurati")
ok(p3["band_source"]=="dispersione d'ensemble", "a D+3 la banda viene dalla dispersione, non da un moltiplicatore")
ok((p3["hi"]-p3["lo"])>(p0["hi"]-p0["lo"]), "banda piu' larga a 3 giorni che a 0 (%.1f vs %.1f)"%(p3["hi"]-p3["lo"],p0["hi"]-p0["lo"]))
ok(p0["validata"] and not p3["validata"], "validata a D+0, NON validata a D+3 (il modello non e' stato provato a quella scadenza)")
ok(p3["lead_band"]=="long" or p3["lead_band"]=="medium", "la scadenza porta la propria fascia (%s)"%p3["lead_band"])
# Nessuna attenuazione inventata: a pari vettore la probabilita' non cambia
# con la scadenza. Se a scadenza lunga il modello davvero discrimina meno, e'
# la calibrazione di QUELLA fascia a schiacciare le probabilita' verso la
# frequenza climatologica, e lo fa perche' i dati lo mostrano.
ok(abs(p3["prob"]-p1["prob"])<1e-9, "nessuna attenuazione a mano con la scadenza (%.3f = %.3f)"%(p1["prob"],p3["prob"]))
cov,n=M.verify_intervals(S,learned)
ok(cov is not None and 0.6<cov<0.95, "copertura banda 10-90%% plausibile: %.2f su n=%d"%(cov,n))

# rumore puro -> niente promozione
N=make(500, signal=False)
cn,alln=M.train("Torbole-Ora",N)
print("   rumore:", [(r["tier"], round(r["brier"],4) if r["brier"] else None, round(r["brier_base"],4) if r["brier_base"] else None, r["usable"]) for r in alln])
ok(cn is None or not cn["usable"], "su rumore puro nessun modello viene promosso")
pn=M.predict("Torbole-Ora",N[0]["features"],{"payload":M.serialize(cn),"metrics":M.metrics_of(cn)} if cn else None,1,3)
ok(pn["source"] in ("prior","misto"), "su rumore si ripiega sul prior (%s)"%pn["source"])

# pochi dati -> solo il livello semplice
few=make(60)
cf,allf=M.train("Torbole-Ora",few)
print("   60 giorni:", [(r["tier"], r["usable"]) for r in allf])
ok(all(r["tier"]!="full" for r in allf), "con 60 giorni il livello completo non viene nemmeno tentato")

# prior senza modello
pp=M.predict("Torbole-Ora",S[0]["features"],None,1,4)
ok(pp["source"]=="prior" and 0<pp["prob"]<1 and pp["speed"]>0, "prior fisico funziona da solo")
