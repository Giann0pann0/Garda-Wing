import os
import sys, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import util as U
from datetime import datetime, timezone, timedelta

ok = lambda c,m: print(("PASS " if c else "FAIL ")+m)

# --- tempo ---
d = U.parse_dt_any("2026-09-13T10:15:00+01")
ok(d == datetime(2026,9,13,9,15,tzinfo=timezone.utc), "Meteotrentino +01 -> UTC 09:15 (%s)"%d)
ok(U.parse_dt_any("2026-09-13T10:15:00+01:00")==d, "offset a 5 char equivalente")
ok(U.parse_dt_any("13/09/26 11.28", assume_offset_hours=2)==datetime(2026,9,13,9,28,tzinfo=timezone.utc), "formato Malcesine con CEST")
ok(U.parse_dt_any("")is None and U.parse_dt_any("xx") is None, "input invalido -> None")
ok(U.local_hour(datetime(2026,9,13,9,15,tzinfo=timezone.utc))==11, "ora locale estiva = UTC+2")
ok(U.local_hour(datetime(2026,1,13,9,15,tzinfo=timezone.utc))==10, "ora locale invernale = UTC+1")
ok(U.local_day(datetime(2026,6,30,22,30,tzinfo=timezone.utc))=="2026-07-01", "giorno locale attraversa mezzanotte")
ok(U.iso_hour_utc(datetime(2026,9,13,9,47,tzinfo=timezone.utc))=="2026-09-13T09:00:00Z","chiave oraria")
ok(U.day_shift("2026-03-01",-1)=="2026-02-28","day_shift")

# --- angoli ---
ok(abs(U.along_axis(10,204,204)-10)<1e-9, "along_axis concorde = +v")
ok(abs(U.along_axis(10,24,204)+10)<1e-9, "along_axis opposto = -v")
ok(abs(U.along_axis(10,294,204))<1e-9, "along_axis perpendicolare = 0")
ok(abs(U.cross_axis(10,294,204)-10)<1e-9, "cross_axis perpendicolare = v")
dm,cst = U.vector_mean_direction([(10,200),(10,210)])
ok(abs(dm-205)<0.5 and cst>0.99, "media vettoriale direzioni coerenti (%.1f, %.2f)"%(dm,cst))
dm2,cst2 = U.vector_mean_direction([(10,0),(10,180)])
ok(cst2<0.01, "direzioni opposte -> costanza ~0 (%.3f)"%cst2)

# --- ridge: recupero coefficienti noti ---
random.seed(7)
n,p = 300, 5
beta = [2.0,-1.5,0.0,0.7,3.0]; b0=4.0
X=[[random.gauss(0,1) for _ in range(p)] for _ in range(n)]
y=[b0+sum(b*x for b,x in zip(beta,r))+random.gauss(0,0.25) for r in X]
m=U.ridge_fit(X,y,lam=0.01)
ok(m is not None, "ridge_fit ritorna un modello")
err=max(abs(a-b) for a,b in zip(m.coef,beta))
ok(err<0.08, "ridge recupera i coefficienti (err max %.4f)"%err)
ok(abs(m.intercept-b0)<0.08, "ridge recupera l'intercetta (%.3f)"%m.intercept)

# colonna costante non deve rompere nulla
Xc=[r+[5.0] for r in X]
mc=U.ridge_fit(Xc,y,lam=0.5)
ok(mc is not None and abs(mc.coef[-1])<1e-9, "colonna costante -> coefficiente 0, nessun crash")

# n < p
ms=U.ridge_fit(X[:3],y[:3],lam=1.0)
ok(ms is not None, "n<p non esplode (regolarizzazione alza fino a soluzione)")

# --- logistica ---
yb=[1 if (b0+sum(b*x for b,x in zip(beta,r)))>4.0 else 0 for r in X]
lm=U.logistic_fit(X,yb,lam=0.5)
ok(lm is not None, "logistic_fit ritorna un modello")
acc=sum(1 for r,t in zip(X,yb) if (lm.predict_proba(r)>0.5)==bool(t))/n
ok(acc>0.9, "logistica separa bene (acc %.3f)"%acc)
ok(U.logistic_fit(X,[1]*n,lam=.5) is None, "classe unica -> None")

# --- CV a blocchi ---
groups=[str(i//10) for i in range(n)]
folds=U.block_folds(groups,5)
ok(len(folds)==5 and sum(len(f) for f in folds)==n, "block_folds copre tutto")
gsets=[set(groups[i] for i in f) for f in folds]
ok(all(not (gsets[i]&gsets[j]) for i in range(5) for j in range(i+1,5)), "nessun gruppo attraversa due fold")
pr,okn=U.cv_predict(X,y,groups,lambda a,b:U.ridge_fit(a,b,0.1),lambda m,r:m.predict(r))
mt=U.regression_metrics(pr,y)
ok(okn==n and mt["rmse"]<0.35, "CV out-of-fold accurata (rmse %.3f)"%mt["rmse"])

# --- metriche ---
ok(abs(U.brier([1.0]*10,[1]*10))<1e-12, "brier perfetto = 0")
cov,_=U.interval_coverage([0]*100,[10]*100,[5]*100)
ok(cov==1.0, "copertura 100%")
print("\n-- quantile --", U.quantile([1,2,3,4,5],0.5), U.quantile([1,2,3,4,5],0.1))
