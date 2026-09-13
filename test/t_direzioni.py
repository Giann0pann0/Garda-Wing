"""Lo strumento che deve decidere l'asse del Peler trova quello che c'e'?

Si costruisce un archivio con la risposta NOTA - due mode a 354 e 54 gradi, piu'
un settentrionale sinottico pomeridiano - e si verifica che moda, mediana
circolare, bimodalita' e separazione per ora del picco vengano fuori giuste.
Uno strumento diagnostico non verificato non e' una diagnosi, e' un'opinione
con dei numeri accanto.
"""
import os, sys, math, random, datetime as dt
os.environ["GARDAWIND_HOME"] = "/tmp/gwdir"
os.makedirs("/tmp/gwdir", exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
for f in os.listdir("/tmp/gwdir"):
    os.remove(os.path.join("/tmp/gwdir", f))
from gardawind import store, config, aggregate, regimes
from gardawind.util import (circular_median, circular_mean, circular_modes,
                            angle_diff, iso_utc, local_day, local_hour, median)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
store.init()
random.seed(19)
UTC = dt.timezone.utc

# --------------------------------------------------------------------------
# 1. Le funzioni circolari, su casi in cui la risposta si sa a mente
# --------------------------------------------------------------------------
ok(abs(circular_median([350, 355, 0, 5, 10]) - 0) < 2 or
   abs(circular_median([350, 355, 0, 5, 10]) - 360) < 2,
   "mediana circolare di 350..10 sta attorno a 0 (%.0f), non a 180"
   % circular_median([350, 355, 0, 5, 10]))
ok(abs(median([350, 355, 0, 5, 10]) - 10) < 1,
   "...mentre la mediana ordinaria darebbe %g: e' il motivo per cui serve quella circolare"
   % median([350, 355, 0, 5, 10]))
mu, R = circular_mean([10, 12, 8, 11, 9])
ok(abs(mu - 10) < 1 and R > 0.99, "media circolare 10 gradi, concentrazione %.2f" % R)
_mu2, R2 = circular_mean([0, 90, 180, 270])
ok(R2 < 0.01, "quattro direzioni opposte -> concentrazione ~0 (%.3f)" % R2)

due = [354 + random.gauss(0, 8) for _ in range(300)] + \
      [54 + random.gauss(0, 8) for _ in range(220)]
modes, dip = circular_modes(due, bin_deg=10)
cent = sorted(m[0] % 360 for m in modes[:2])
ok(len(modes) >= 2, "distribuzione a due gobbe riconosciuta come bimodale (%d mode)"
   % len(modes))
ok(any(abs(((c - 354 + 180) % 360) - 180) < 12 for c in cent)
   and any(abs(((c - 54 + 180) % 360) - 180) < 12 for c in cent),
   "e le mode sono dove le ho messe: %s" % [round(c) for c in cent])
ok(dip is not None and dip < 0.6,
   "il ventre fra le due e' al %.0f%% della seconda: davvero separate" % (100 * dip))

una = [24 + random.gauss(0, 20) for _ in range(500)]
m1, d1 = circular_modes(una, bin_deg=10)
ok(len(m1) == 1, "una gobba sola resta una gobba sola (%d)" % len(m1))

# --------------------------------------------------------------------------
# 2. Un archivio finto con la risposta nota, letto dal codice vero
# --------------------------------------------------------------------------
# Peler vero: mattina presto, direzione 354. Un secondo ramo a 54.
# Settentrionale sinottico: stessa meta' di rosa, ma nel POMERIGGIO.
spot = config.SPOTS["Torbole-Peler"]
start = dt.date(2019, 1, 1)
rows = []
atteso = {"peler": 0, "sinottico": 0}
for i in range(1200):
    day = (start + dt.timedelta(days=i)).isoformat()
    u = random.random()
    if u < 0.40:
        direzione, ora_picco, forza = 354 + random.gauss(0, 7), 7.0, 15.0
        atteso["peler"] += 1
    elif u < 0.62:
        direzione, ora_picco, forza = 54 + random.gauss(0, 7), 7.5, 14.0
        atteso["peler"] += 1
    elif u < 0.75:
        # sinottico da nord ma nel pomeriggio: fuori dalla finestra del Peler
        # tranne la coda, e con l'ora del picco spostata in fondo alla finestra
        direzione, ora_picco, forza = 10 + random.gauss(0, 25), 10.0, 13.0
        atteso["sinottico"] += 1
    else:
        direzione, ora_picco, forza = random.uniform(0, 360), 8.0, 4.0
    base = dt.datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=UTC)
    for off in range(-3, 27):
        t = base + dt.timedelta(hours=off)
        if local_day(t) != day:
            continue
        h = local_hour(t)
        if not (spot["window"][0] - 1 <= h <= spot["window"][1] + 1):
            continue
        w = max(0.5, forza * math.exp(-((h - ora_picco) / 2.2) ** 2))
        for mnt in range(0, 60, 10):
            rows.append((iso_utc(t + dt.timedelta(minutes=mnt)),
                         max(0.0, w + random.gauss(0, 0.3)), w * 1.35,
                         direzione % 360))
store.save_samples("T0193", rows, "test")
aggregate.aggregate_station("T0193")

cls = regimes.classify_days(store.obs_hours("T0193"), window=spot["window"])
windy = [(r["dir"], r["peak"], r["peak_hour"]) for r in cls.values()
         if r.get("dir") is not None and r["peak"] >= regimes.MIN_REGIME_KN]
ok(len(windy) > 500, "%d giornate ventose ricostruite dall'archivio" % len(windy))

dirs = [d for d, _p, _h in windy]
med = circular_median(dirs)
modes, dip = circular_modes(dirs, bin_deg=10)
print("   mediana circolare %.0f  |  mode %s  |  ventre %s"
      % (med, [round(m[0]) for m in modes[:3]],
         ("%.2f" % dip) if dip else "-"))
ok(len(modes) >= 2, "sui dati veri del finto archivio la bimodalita' si vede")
cent = [m[0] % 360 for m in modes[:2]]
ok(any(angle_diff(c, 354) < 15 for c in cent) and any(angle_diff(c, 54) < 15 for c in cent),
   "entrambe le mode ritrovate: %s" % [round(c) for c in cent])

# La cosa che conta: l'asse dichiarato (24) NON e' dove sta la roba.
scarto = angle_diff(med, spot["axis"])
print("   asse dichiarato %g, mediana circolare %.0f, scarto %.0f gradi"
      % (spot["axis"], med, scarto))
ok(scarto > 8, "lo strumento segnala che l'asse dichiarato non e' centrato "
   "(scarto %.0f gradi)" % scarto)

# E il criterio non circolare: dentro/fuori settore separati per ORA del picco.
half = regimes.SETTORI[regimes.PELER][1]
dentro = [h for d, _p, h in windy if angle_diff(d, spot["axis"]) <= half and h]
fuori = [h for d, _p, h in windy if angle_diff(d, spot["axis"]) > half and h]
# Nel mondo finto entrambe le mode (354 e 54) cadono dentro +/-45 da 24: quasi
# tutto risulta "dentro". E' esattamente cio' che succede nei dati veri (94%
# entro +/-45), ed e' il motivo per cui la quota dentro/fuori NON basta a
# giudicare l'asse: serve guardare dove sta la massa, non quanta ne e' dentro.
ok(len(dentro) > 50 and len(fuori) >= 10,
   "dentro %d gg, fuori %d gg: un settore largo inghiotte quasi tutto"
   % (len(dentro), len(fuori)))
ok(abs(median(dentro) - median(fuori)) >= 1.5,
   "ma l'ora del picco separa i due gruppi (%.1f contro %.1f): e' il criterio "
   "non circolare" % (median(dentro), median(fuori)))
print("   ora mediana del picco: dentro %.1f, fuori %.1f"
      % (median(dentro), median(fuori)))

# --------------------------------------------------------------------------
# 3. Il comando gira per intero senza rompersi
# --------------------------------------------------------------------------
from gardawind.__main__ import cmd_direzioni
print()
cmd_direzioni("Torbole-Peler")
ok(True, "il comando --direzioni gira fino in fondo")
