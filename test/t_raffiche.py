"""La raffica ricorrente, l'ingresso sostenuto, e il tempo misurato in minuti.

Con il wing non si plana sul vento medio e non si plana sulla raffica di
punta. Queste primitive definiscono la grandezza su cui si decide e l'istante
in cui si puo' entrare in acqua. Due proprieta' vanno difese:

CAUSALITA': sono funzioni di quello che sta dentro una finestra mobile, non di
come e' andata la giornata. Se un domani qualcuno le ridefinisce "sulle ore
migliori", si e' riaperta la porta a una selezione fatta sapendo il futuro.

INDIPENDENZA DALLA CADENZA: la prima versione aveva dentro tre costanti vere
solo per Torbole (3 campioni per finestra, 12 campioni = due ore, ogni
campione = 10 minuti). A Malcesine, che campiona ogni 15-30 minuti, la raffica
ricorrente usciva None su tutto, le durate sbagliavano di un fattore tre e
l'ingresso non si trovava mai - senza che niente lo segnalasse.
"""
import os, sys, io, contextlib
os.environ["GARDAWIND_HOME"] = "/tmp/gwraff"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwraff", ignore_errors=True)

from gardawind.util import (FINESTRA_RICORRENTE_MIN, covered_minutes,
                            gust_level, iso_utc, recurrent_gust,
                            sampling_cadence, sustained_onset, time_above,
                            window_estimable)
from gardawind import store, aggregate
import datetime as dt

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc


def val(series, minute):
    for t, v in series:
        if abs(t - minute) < 1e-6:
            return v
    return "assente"


# ======================= causalita' e robustezza =======================

# un colpo isolato non alza la ricorrente: e' tutto il punto della grandezza
s = [(0, 10.0), (10, 10.0), (20, 30.0), (30, 10.0), (40, 10.0)]
r = recurrent_gust(s)
ok(val(r, 20) == 10.0, "un colpo isolato non alza la ricorrente (%s)" % val(r, 20))
ok(max(v for _t, v in r if v is not None) == 10.0,
   "nessun punto della ricorrente arriva al valore del colpo")

# un livello che TORNA invece la alza
s = [(0, 10.0), (10, 22.0), (20, 21.0), (30, 23.0), (40, 10.0)]
ok(val(recurrent_gust(s), 20) == 22.0,
   "tre raffiche alte di fila fanno salire la ricorrente")

# i buchi non vengono riempiti
r = recurrent_gust([(0, 15.0), (600, 15.0)])
ok(all(v is None for _t, v in r), "due campioni a dieci ore di distanza: None")
ok(len(r) == 2, "ma i punti restano, non vengono buttati")

# centrata contro all'indietro: devono essere diverse, cosi' chi le usa scegli
s = [(0, 10.0), (10, 10.0), (20, 10.0), (30, 25.0), (40, 25.0), (50, 25.0)]
c = recurrent_gust(s, centered=True)
b = recurrent_gust(s, centered=False)
ok(val(c, 30) != val(b, 30),
   "centrata %s e all'indietro %s non coincidono" % (val(c, 30), val(b, 30)))
ok(val(b, 50) == 25.0, "all'indietro, a fine rampa, la ricorrente e' salita")

# ======================= indipendenza dalla cadenza =======================

t10 = [(i * 10.0, 14.0) for i in range(12)]      # Torbole
t30 = [(i * 30.0, 15.0) for i in range(12)]      # Malcesine

ok(sampling_cadence([t for t, _v in t10]) == 10.0, "cadenza 10 min riconosciuta")
ok(sampling_cadence([t for t, _v in t30]) == 30.0, "cadenza 30 min riconosciuta")
# un buco non e' cadenza
ok(sampling_cadence([0.0, 10.0, 20.0, 600.0, 610.0]) == 10.0,
   "un buco di dieci ore non entra nella cadenza")

# La finestra della ricorrente NON si allarga mai. Una versione precedente, a
# cadenza 30, la portava a 90 minuti e continuava a chiamarla "ricorrente":
# faceva sembrare due centraline confrontabili quando misuravano due grandezze
# diverse. Ora la risposta e' "non stimabile".
ok(window_estimable(10.0, 30.0), "a 10 min la ricorrente a 30' e' stimabile")
ok(window_estimable(15.0, 30.0), "a 15 min lo e' ancora (tre campioni esatti)")
ok(not window_estimable(30.0, 30.0),
   "a 30 min NON lo e': un campione solo dentro mezz'ora")
ok(not window_estimable(None, 30.0), "senza cadenza nota, non stimabile")

r10 = recurrent_gust(t10)
n10 = sum(1 for _t, v in r10 if v is not None)
ok(n10 == len(t10) - 2, "a cadenza 10 la ricorrente si calcola (%d su %d)"
   % (n10, len(t10)))
# Il primo e l'ultimo punto hanno mezza finestra e restano None: ai bordi di
# una serie la finestra centrata e' davvero incompleta, e dirlo e' giusto.
ok(r10[0][1] is None and r10[-1][1] is None,
   "ai bordi della serie la finestra e' incompleta: None, non un mezzo valore")

r30 = recurrent_gust(t30)
ok(all(v is None for _t, v in r30),
   "a cadenza 30 la ricorrente resta None: non si finge di saperla")

# Per un livello su una finestra piu' larga si chiede esplicitamente quella
# finestra, e il nome della grandezza cambia di conseguenza.
g90 = gust_level(t30, 90.0)
n90 = sum(1 for _t, v in g90 if v is not None)
ok(n90 == len(t30) - 2,
   "il livello sostenuto su 90' invece si calcola (%d su %d)" % (n90, len(t30)))
ok(FINESTRA_RICORRENTE_MIN == 30.0,
   "la finestra canonica sta scritta in un posto solo")

# durate: minuti veri, non numero di righe per dieci
ok(time_above(t10, 14.0) == 120.0, "12 campioni a 10 min = 120 minuti (%s)"
   % time_above(t10, 14.0))
ok(time_above(t30, 14.0) == 360.0,
   "12 campioni a 30 min = 360 minuti, non 120 (%s)" % time_above(t30, 14.0))
ok(time_above(t30, 99.0) == 0.0, "sotto soglia, zero minuti")

# copertura: i buchi non si contano come tempo coperto
ok(covered_minutes([0.0, 10.0, 20.0]) == 30.0, "tre campioni a 10 min coprono 30 min")
cop = covered_minutes([0.0, 10.0, 600.0, 610.0])
ok(cop == 40.0, "un buco di dieci ore non diventa copertura (%s)" % cop)

# Ingresso a cadenza 30: si deve trovare. Con max_gap fisso a 15 minuti ogni
# intervallo spezzava la serie e non si trovava MAI. Qui la serie e' il vento
# osservato, non la ricorrente - ed e' il motivo per cui il timing si puo'
# misurare sui quattordici anni di Torbole senza aspettare le raffiche.
ing30 = sustained_onset(t30, 14.0, persist_min=30.0)
ok(ing30 is not None, "a cadenza 30 l'ingresso si trova (%s)" % ing30)
ok(ing30 == -15.0, "ed e' il centro del primo intervallo coperto (%s)" % ing30)

# ======================= persistenza dell'ingresso =======================

soglia = 17.0
ok(sustained_onset([(0, 10.0), (10, 10.0), (20, 20.0), (30, 10.0)], soglia,
                   persist_min=30.0) is None,
   "un solo punto sopra soglia non e' un ingresso")
s = [(0, 10.0), (10, 18.0), (20, 19.0), (30, 18.0), (40, 21.0), (50, 10.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) == 5.0,
   "trenta minuti consecutivi: ingresso al centro del primo intervallo")
s = [(0, 10.0), (10, 18.0), (20, 19.0), (30, 10.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) is None,
   "venti minuti di copertura non soddisfano una richiesta di trenta")
ok(sustained_onset(s, soglia, persist_min=20.0) == 5.0,
   "gli stessi venti minuti soddisfano una richiesta di venti")
ok(sustained_onset([(0, 20.0), (10, 20.0), (120, 20.0), (130, 20.0)], soglia,
                   persist_min=30.0) is None,
   "un buco di due ore non diventa una finestra continua")
s = [(0, 18.0), (10, 18.0), (20, 18.0), (30, 18.0),
     (200, 30.0), (210, 30.0), (220, 30.0), (230, 30.0)]
ok(sustained_onset(s, soglia, persist_min=30.0) == -5.0,
   "si entra al primo momento buono, non al piu' ventoso")

# ======================= aggregazione =======================

store.init()
base = dt.datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
campioni = []
for i in range(6):
    g = 40.0 if i == 3 else 14.0        # un colpo isolato dentro l'ora
    campioni.append((iso_utc(base + dt.timedelta(minutes=10 * i)), 10.0, g, 200.0))
store.save_samples("TEST", campioni, "t_raffiche")
ok(aggregate.aggregate_station("TEST") == 1, "una riga oraria scritta")
row = store.obs_hours("TEST")[0]
ok(abs(row["gust_max"] - 40.0) < 1e-6, "la raffica massima registra il colpo")
ok(row["gust_rec"] is not None and abs(row["gust_rec"] - 14.0) < 1e-6,
   "la ricorrente lo ignora: %s" % row["gust_rec"])
ok(row["gust_rec"] < row["gust_max"],
   "ricorrente e massima sono due grandezze separate, non un alias")
ok(abs(row["wind_mean"] - 10.0) < 1e-6, "il vento medio resta quello che era")

# A cadenza rada l'aggregazione NON scrive un valore preso da un'altra
# finestra: lascia NULL.
base2 = dt.datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
camp2 = [(iso_utc(base2 + dt.timedelta(minutes=30 * i)), 10.0, 16.0, 200.0)
         for i in range(8)]
store.save_samples("RADA", camp2, "t_raffiche")
aggregate.aggregate_station("RADA")
righe_rade = store.obs_hours("RADA")
ok(righe_rade and all(r["gust_rec"] is None for r in righe_rade),
   "a cadenza 30 min gust_rec resta NULL su tutte le ore (%d righe)"
   % len(righe_rade))
ok(righe_rade and all(r["gust_max"] is not None for r in righe_rade),
   "ma la raffica massima, che non ha bisogno di finestra, c'e'")

cols = {r["name"] for r in store.connect().execute("PRAGMA table_info(obs_hour)")}
ok("gust_rec" in cols, "la colonna esiste dopo la migrazione")
store._migra(store.connect())
cols2 = {r["name"] for r in store.connect().execute("PRAGMA table_info(obs_hour)")}
ok(cols == cols2, "rilanciare la migrazione non cambia niente")

# ============ la raffica non filtra lo storico (il guasto delle 9 giornate) ===
# Uno storico lungo di solo vento, con la raffica solo negli ultimi giorni:
# il blocco del vento medio deve vedere TUTTE le giornate, non solo quelle con
# la raffica. Era esattamente il contrario, e trasformava quattordici anni in
# nove giorni senza dirlo.
shutil.rmtree("/tmp/gwraff2", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwraff2"
store.close()
store.init()
b0 = dt.datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
camp = []
for d in range(80):
    for k in range(0, 24 * 6):
        t = b0 + dt.timedelta(days=d, minutes=10 * k)
        camp.append((iso_utc(t), 13.0, 19.0 if d >= 75 else None, 200.0))
store.save_samples("T0193", camp, "t_raffiche")
from gardawind.__main__ import cmd_raffiche
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cmd_raffiche("Torbole-Ora")
uscita = buf.getvalue()
import re
m_medio = re.search(r"VENTO MEDIO\s+-\s+(\d+) giornate", uscita)
m_raff = re.search(r"RAFFICA\s+-\s+(\d+) giornate", uscita)
ok(m_medio is not None and int(m_medio.group(1)) >= 75,
   "il vento medio vede lo storico intero: %s giornate"
   % (m_medio.group(1) if m_medio else "?"))
ok(m_raff is not None and int(m_raff.group(1)) <= 6,
   "la raffica dichiara le sue poche giornate: %s"
   % (m_raff.group(1) if m_raff else "?"))
ok("raffica storica disponibile solo di recente" in uscita,
   "e lo dichiara in testa, invece di lasciarlo dedurre")
ok(int(m_medio.group(1)) > int(m_raff.group(1)) * 5,
   "i due livelli non sono mescolati")
