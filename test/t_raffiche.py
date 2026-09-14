"""La raffica ricorrente e l'ingresso sostenuto.

Con il wing non si plana sul vento medio e non si plana sulla raffica di
punta. Queste due primitive definiscono la grandezza su cui si decide e
l'istante in cui si puo' entrare in acqua, e sono definite in modo CAUSALE:
sono funzioni di quello che sta dentro una finestra mobile, non di come e'
andata la giornata. Se un domani qualcuno le ridefinisce "sulle ore migliori",
questi controlli dicono che si e' riaperta la porta a una selezione fatta
sapendo il futuro.
"""
import os, sys
os.environ["GARDAWIND_HOME"] = "/tmp/gwraff"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwraff", ignore_errors=True)

from gardawind.util import recurrent_gust, sustained_onset
from gardawind import store, aggregate
from gardawind.util import iso_utc
import datetime as dt

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc


def val(series, minute):
    for t, v in series:
        if abs(t - minute) < 1e-6:
            return v
    return "assente"


# ---- la mediana mobile scarta il colpo isolato ----
# Un solo campione a 30 nodi in mezzo a campioni da 10: la mediana su tre non
# lo vede. E' tutto il punto della grandezza.
s = [(0, 10.0), (10, 10.0), (20, 30.0), (30, 10.0), (40, 10.0)]
r = recurrent_gust(s, window_min=30.0)
ok(val(r, 20) == 10.0, "un colpo isolato non alza la ricorrente (%s)" % val(r, 20))
ok(max(v for _t, v in r if v is not None) == 10.0,
   "nessun punto della ricorrente arriva al valore del colpo")

# ---- un livello che TORNA invece la alza ----
s = [(0, 10.0), (10, 22.0), (20, 21.0), (30, 23.0), (40, 10.0)]
r = recurrent_gust(s, window_min=30.0)
ok(val(r, 20) == 22.0, "tre raffiche alte di fila fanno salire la ricorrente (%s)"
   % val(r, 20))

# ---- i buchi non vengono riempiti ----
s = [(0, 15.0), (10, 15.0)]
r = recurrent_gust(s, window_min=30.0, min_points=3)
ok(all(v is None for _t, v in r), "con meno di tre campioni la ricorrente e' None")
ok(len(r) == 2, "ma i punti restano, non vengono buttati")

# ---- finestra centrata contro finestra all'indietro ----
# La centrata guarda oltre l'istante: va bene per il bersaglio (storia), non
# per il dato in diretta. Qui si verifica che siano davvero diverse, cosi' chi
# le usa deve scegliere.
s = [(0, 10.0), (10, 10.0), (20, 10.0), (30, 25.0), (40, 25.0), (50, 25.0)]
c = recurrent_gust(s, window_min=30.0, centered=True)
b = recurrent_gust(s, window_min=30.0, centered=False)
ok(val(c, 30) != val(b, 30),
   "centrata %s e all'indietro %s non coincidono" % (val(c, 30), val(b, 30)))
ok(val(b, 50) == 25.0, "all'indietro, a fine rampa, la ricorrente e' salita")

# ---- l'ingresso vuole persistenza, non un superamento puntuale ----
soglia = 17.0
# un colpo solo sopra soglia: nessun ingresso
s = [(0, 10.0), (10, 10.0), (20, 20.0), (30, 10.0), (40, 10.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) is None,
   "un solo punto sopra soglia non e' un ingresso")

# Sopra soglia per trenta minuti pieni. Un campione copre dieci minuti, quindi
# i tre campioni 10-20-30 coprono dalle 00:00 alle 00:30, e l'ingresso torna al
# CENTRO dell'intervallo del primo campione: 10 - 5 = 5.
s = [(0, 10.0), (10, 18.0), (20, 19.0), (30, 18.0), (40, 21.0), (50, 10.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) == 5.0,
   "trenta minuti consecutivi: ingresso al centro del primo intervallo (%s)"
   % sustained_onset(s, soglia, persist_min=30.0))

# Due campioni coprono venti minuti: bastano per venti, non per trenta.
s = [(0, 10.0), (10, 18.0), (20, 19.0), (30, 10.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) is None,
   "venti minuti di copertura non soddisfano una richiesta di trenta")
ok(sustained_onset(s, soglia, persist_min=20.0) == 5.0,
   "gli stessi venti minuti soddisfano una richiesta di venti (%s)"
   % sustained_onset(s, soglia, persist_min=20.0))
ok(sustained_onset([(0, 10.0), (10, 18.0), (20, 10.0)], soglia,
                   persist_min=20.0) is None,
   "un campione solo copre dieci minuti: non ne fa venti")

# un buco nei dati NON salda due tratti lontani
s = [(0, 20.0), (10, 20.0), (120, 20.0), (130, 20.0)]
ok(sustained_onset(s, soglia, persist_min=30.0, max_gap_min=15.0) is None,
   "un buco di due ore non diventa una finestra continua")

# il primo ingresso valido vince, anche se dopo ce n'e' uno piu' forte
s = [(0, 18.0), (10, 18.0), (20, 18.0), (30, 18.0),
     (200, 30.0), (210, 30.0), (220, 30.0), (230, 30.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) == -5.0,
   "si entra al primo momento buono, non al piu' ventoso (%s)"
   % sustained_onset(s, soglia, persist_min=30.0))

# ---- l'aggregazione scrive gust_rec e non la confonde con il massimo ----
store.init()
base = dt.datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
campioni = []
for i in range(6):                       # un'ora di campioni a dieci minuti
    # raffica 14, tranne un colpo isolato a 40 nel quarto campione
    g = 40.0 if i == 3 else 14.0
    campioni.append((iso_utc(base + dt.timedelta(minutes=10 * i)), 10.0, g, 200.0))
store.save_samples("TEST", campioni, "t_raffiche")
n = aggregate.aggregate_station("TEST")
ok(n == 1, "una riga oraria scritta (%d)" % n)
row = store.obs_hours("TEST")[0]
ok(abs(row["gust_max"] - 40.0) < 1e-6, "la raffica massima registra il colpo (%.0f)"
   % row["gust_max"])
ok(row["gust_rec"] is not None and abs(row["gust_rec"] - 14.0) < 1e-6,
   "la ricorrente lo ignora: %s" % row["gust_rec"])
ok(row["gust_rec"] < row["gust_max"],
   "ricorrente e massima sono due grandezze separate, non un alias")
ok(abs(row["wind_mean"] - 10.0) < 1e-6, "il vento medio resta quello che era")

# ---- la migrazione e' idempotente ----
cols = {r["name"] for r in store.connect().execute("PRAGMA table_info(obs_hour)")}
ok("gust_rec" in cols, "la colonna esiste dopo la migrazione")
store._migra(store.connect())
store._migra(store.connect())
cols2 = {r["name"] for r in store.connect().execute("PRAGMA table_info(obs_hour)")}
ok(cols == cols2, "rilanciare la migrazione non cambia niente")
