"""Il dato osservato separato dalla previsione: live.json.

Quattro cose da difendere, e sono tutte cose che nella versione precedente
andavano storte in silenzio:

  1. live.json contiene l'ORARIO del campione, non la sua eta'. L'eta' e' una
     sottrazione e va fatta quando si guarda: scriverla nel file significa
     congelarla, ed e' il motivo per cui la pagina diceva "adesso" cinque ore
     dopo.
  2. la raffica ricorrente esce solo alla sua finestra dichiarata di 30
     minuti. Dove la cadenza non la sostiene, il campo e' None e lo stato
     dice perche': "non stimabile" non e' zero.
  3. la cadenza che conta per la raffica e' quella dei campioni CON la
     raffica. Vento ogni 10 minuti e raffica ogni 30 non sostengono una
     finestra da 30, anche se la cadenza generale direbbe di si'.
  4. il file si scrive in modo atomico: chi lo sta leggendo non trova mai
     mezzo file.
"""
import datetime as dt
import io
import json
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwlive"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwlive", ignore_errors=True)

from gardawind import config, live, store
from gardawind.util import iso_utc

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc

store.init()
ADESSO = dt.datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
ST = config.SPOTS["Torbole-Ora"]["station"]


def scrivi_campioni(station, campioni, fonte="t_live"):
    store.save_samples(station, campioni, fonte)


# --------------------------------------------------------------------------
# 1. Nessun campione: si dice, non si inventa
# --------------------------------------------------------------------------
v = live.stazione(ST, adesso=ADESSO)
ok(v["ts"] is None and v["wind"] is None and v["gust_rec"] is None,
   "senza campioni tutto None, nessuno zero")
ok(v["gust_rec_stato"] == "no_data", "e lo stato lo dice: %s" % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 2. Cadenza 10 minuti, raffica presente: la ricorrente esce
# --------------------------------------------------------------------------
camp = []
for k in range(12, 0, -1):                  # ultimi due ore, ogni 10 minuti
    t = ADESSO - dt.timedelta(minutes=10 * k)
    # raffiche 20, 21, 22 che tornano: la ricorrente deve stare fra loro,
    # non sul massimo.
    raffica = [20.0, 21.0, 22.0][k % 3]
    camp.append((iso_utc(t), 14.0, raffica, 191.0))
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["wind"] == 14.0 and v["dir"] == 191.0, "l'ultimo campione e' quello piu' recente")
ok(v["ts"] == iso_utc(ADESSO - dt.timedelta(minutes=10)),
   "e il suo orario e' scritto nel file (%s)" % v["ts"])
ok("age" not in v and "eta" not in v,
   "nel file non c'e' nessuna eta': la calcola chi guarda")
ok(v["cadenza_min"] == 10.0, "cadenza dedotta dai dati: %s" % v["cadenza_min"])
ok(v["gust_rec"] is not None and 20.0 <= v["gust_rec"] <= 22.0,
   "la ricorrente sta dentro le raffiche che tornano (%s)" % v["gust_rec"])
ok(v["gust_rec"] < 22.0 or v["gust"] == 22.0,
   "e non e' automaticamente il massimo")
ok(v["gust_rec_stato"] == "ok" and v["gust_rec_finestra_min"] == 30.0,
   "la finestra dichiarata e' 30 minuti, sempre la stessa")

# --------------------------------------------------------------------------
# 3. Vento ogni 10 minuti, raffica ogni 30: la finestra non si sostiene
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive2", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive2"
store.close()
store.init()
camp = []
for k in range(12, 0, -1):
    t = ADESSO - dt.timedelta(minutes=10 * k)
    raffica = 21.0 if (k % 3 == 0) else None
    camp.append((iso_utc(t), 14.0, raffica, 191.0))
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["cadenza_min"] == 10.0, "la cadenza generale resta 10 minuti")
ok(v["cadenza_raffica_min"] == 30.0,
   "ma quella della raffica e' 30 (%s)" % v["cadenza_raffica_min"])
ok(v["gust_rec"] is None and "cadenza troppo rada" in v["gust_rec_stato"],
   "quindi la ricorrente a 30' non e' stimabile, e non viene allargata: %s"
   % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 4. Solo vento, nessuna raffica: si dichiara, non si finge
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive3", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive3"
store.close()
store.init()
camp = [(iso_utc(ADESSO - dt.timedelta(minutes=10 * k)), 15.0, None, 191.0)
        for k in range(12, 0, -1)]
scrivi_campioni(ST, camp)
v = live.stazione(ST, adesso=ADESSO)
ok(v["wind"] == 15.0 and v["gust"] is None and v["gust_rec"] is None,
   "vento si', raffica no")
ok(v["gust_rec_stato"] == "raffica assente",
   "e lo stato distingue 'assente' da 'non stimabile': %s" % v["gust_rec_stato"])

# --------------------------------------------------------------------------
# 5. Un dato vecchio resta vecchio: il file non lo maschera
# --------------------------------------------------------------------------
shutil.rmtree("/tmp/gwlive4", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwlive4"
store.close()
store.init()
vecchio = ADESSO - dt.timedelta(hours=5)
scrivi_campioni(ST, [(iso_utc(vecchio - dt.timedelta(minutes=10 * k)),
                      12.0, 18.0, 191.0) for k in range(6, 0, -1)])
v = live.stazione(ST, adesso=ADESSO)
ok(v["ts"] == iso_utc(vecchio - dt.timedelta(minutes=10)),
   "l'orario e' quello vero, di cinque ore fa")
ok(v["gust_rec"] is not None,
   "la ricorrente si calcola comunque: e' il dato che e' vecchio, non sbagliato")

# --------------------------------------------------------------------------
# 6. snapshot e scrittura atomica
# --------------------------------------------------------------------------
snap = live.snapshot(adesso=ADESSO)
ok(set(snap["luoghi"]) == set(config.PLACES),
   "snapshot: un luogo per ciascuno di %s" % ", ".join(config.PLACES))
ok(snap["generato"] == iso_utc(ADESSO),
   "snapshot: 'generato' e' quando si scrive, ed e' un'altra cosa dall'eta' del dato")
ok(all("station" in v for v in snap["luoghi"].values()),
   "snapshot: ogni luogo dichiara da quale centralina viene")

percorso = "/tmp/gwlive4/live.json"
live.scrivi(percorso, adesso=ADESSO)
ok(os.path.exists(percorso) and not os.path.exists(percorso + ".tmp"),
   "scrivi: il file c'e' e il temporaneo e' sparito")
letto = json.load(io.open(percorso, encoding="utf-8"))
ok(letto["luoghi"]["Torbole"]["ts"] == v["ts"],
   "scrivi: quello che si rilegge e' quello che si e' misurato")
ok(json.dumps(letto) and "age_min" not in json.dumps(letto),
   "scrivi: nel JSON non finisce nessuna eta' precalcolata")

# Riscrivere sopra un file esistente non lascia residui.
live.scrivi(percorso, adesso=ADESSO + dt.timedelta(minutes=1))
letto2 = json.load(io.open(percorso, encoding="utf-8"))
ok(letto2["generato"] != letto["generato"] and not os.path.exists(percorso + ".tmp"),
   "scrivi: la seconda scrittura sostituisce, e resta un file solo")


# --------------------------------------------------------------------------
# 7. Le curve del misurato, in coordinate normalizzate
#
# Il numerone "adesso" si aggiornava da solo, la curva del misurato no:
# restava quella della costruzione della pagina. Ora entra nel file, e il
# punto delicato e' UNO: la matematica della curva deve restare in
# curva_monotona, in un posto solo. Il browser non interpola, moltiplica -
# quindi la curva scritta in coordinate 0-1 e poi mappata deve venire la
# stessa che si sarebbe disegnata direttamente nelle coordinate del grafico.
# Se non lo fosse, la pagina mostrerebbe due curve diverse per gli stessi
# campioni a seconda di chi l'ha disegnata, e nessuno se ne accorgerebbe.
# --------------------------------------------------------------------------
import re

from gardawind import engine
from gardawind.util import curva_monotona

GIORNO = dt.datetime(2026, 9, 14, 6, 0, tzinfo=UTC)   # 08:00 locali
PUNTI = [(0, 6.0, 9.0), (1, 7.0, 11.0), (2, 12.0, 18.0), (3, 19.0, 27.0),
         (4, 21.0, 30.0), (5, 20.0, 29.0), (6, 17.0, 24.0), (7, 14.0, 20.0),
         (8, 11.0, 15.0), (9, 9.0, 13.0), (10, 8.0, 12.0), (11, 7.0, 10.0),
         (12, 6.0, 9.0)]
camp = []
for k, w, g in PUNTI:
    for mezzo in (0, 10, 20, 30, 40, 50):
        camp.append((iso_utc(GIORNO + dt.timedelta(minutes=60 * k + mezzo)),
                     w, g, 200))
scrivi_campioni(ST, camp, fonte="t_live_curve")
fini = engine.campioni_fini(ST, "2026-09-14")

# Il difetto che questi due controlli impediscono di rimettere: i campioni
# dentro l'ora finivano tutti alla stessa ascissa, perche' l'ora la dava
# local_hour, che i minuti li butta. Sei campioni alla stessa ascissa con sei
# valori diversi non sono una curva: sono un salto verticale, ed e' quello che
# si vedeva nel grafico - gradini da dieci nodi in dieci minuti.
ore = [r["hour"] for r in fini]
ok(len(set(ore)) == len(ore),
   "ogni campione ha la sua ascissa, coi minuti dentro: %d campioni, %d ascisse"
   % (len(ore), len(set(ore))))
ok(any(abs(h - round(h)) > 1e-6 for h in ore),
   "e le ore non sono tutte intere: i dieci minuti esistono")

c = live.curve("Torbole", adesso=ADESSO)
ok(c is not None, "la curva del misurato esce dal file, non solo dalla pagina")
ok(c["media"].startswith("M") and "C" in c["media"] and c["raffica"],
   "sono CURVE, non spezzate - cubiche, come nel grafico - e sono due")
numeri = [float(v) for v in re.findall(r"-?\d+\.?\d*", c["media"])]
ok(min(numeri) >= 0.0 and max(numeri) <= 1.0,
   "in coordinate normalizzate: tutto fra 0 e 1 (%.4f - %.4f)"
   % (min(numeri), max(numeri)))
ok(c["ora_da"] < c["ora_a"] and c["ymax"] > 0,
   "e il file dice di che riferimento si tratta: %g-%g ore, 0-%g kn"
   % (c["ora_da"], c["ora_a"], c["ymax"]))
ok(abs(c["ultimo"]["kn"] - 6.0) < 0.01 and abs(c["ultimo"]["ora"] - 20.833) < 0.01,
   "l'ultimo punto e' l'ultima misura vera: %.1f kn alle %.2f"
   % (c["ultimo"]["kn"], c["ultimo"]["ora"]))
ok(abs(c["max_kn"] - 30.0) < 0.01,
   "e il picco della giornata e' dichiarato, raffica compresa: %.1f kn"
   % c["max_kn"])

# La prova che conta. Un grafico qualunque, con la sua scala e la sua
# finestra di ore, e due strade per la stessa curva.
W, H, pl, pr, pt, pb, top = 440.0, 280.0, 28.0, 58.0, 26.0, 50.0, 35.0
h0, h1 = 5.0, 20.0
dentro = [r for r in fini if c["ora_da"] <= r["hour"] <= c["ora_a"]
          and r.get("wind") is not None]
diretta = curva_monotona(
    [(pl + (W - pl - pr) * (r["hour"] - h0) / (h1 - h0),
      H - pb - (H - pb - pt) * min(top, r["wind"]) / top) for r in dentro])
# La mappa affine, la stessa che fa il browser. Qui e' riscritta in Python
# perche' quello che si controlla e' l'affermazione MATEMATICA: la cubica
# monotona sopravvive a una mappa affine, quindi mappare i punti di controllo
# e interpolare dopo danno la stessa curva. Che il browser la applichi per
# davvero lo controlla t_live_pagina.py, con un browser vero.
Wp, Hp = W - pl - pr, H - pb - pt
TX = pl + Wp * (c["ora_da"] - h0) / (h1 - h0)
SX = Wp * (c["ora_a"] - c["ora_da"]) / (h1 - h0)
TY, SY = H - pb, -Hp * c["ymax"] / top
mappata = re.sub(
    r"(-?[0-9.]+),(-?[0-9.]+)",
    lambda m: "%.1f,%.1f" % (TX + SX * float(m.group(1)),
                             TY + SY * float(m.group(2))),
    c["media"])
ok(re.sub(r"[-\d.]+", "", mappata) == re.sub(r"[-\d.]+", "", diretta),
   "la curva mappata ha gli stessi comandi di quella disegnata: stessi punti,"
   " stessi tratti")
a = [float(v) for v in re.findall(r"-?\d+\.?\d*", mappata)]
b = [float(v) for v in re.findall(r"-?\d+\.?\d*", diretta)]
scarto = max(abs(x - y) for x, y in zip(a, b)) if len(a) == len(b) else None
# Non si pretende l'uguaglianza delle STRINGHE: nel file le coordinate sono
# arrotondate a quattro cifre, e moltiplicate per la larghezza del disegno
# quel troncamento vale qualche centesimo di pixel - abbastanza per far
# cadere un arrotondamento da una parte o dall'altra: mezzo decimo per
# parte, un decimo in tutto, ed e' il massimo possibile. Si pretende che la
# differenza resti invisibile, e un decimo di pixel lo e'.
ok(scarto is not None and scarto <= 0.101,
   "e le passa sopra a meno di un decimo di pixel (%s): una sola matematica,"
   " in un posto solo" % ("%.3f" % scarto if scarto is not None else "?"))

# Una centralina che tace da ieri non disegna la sua curva di ieri su oggi.
ok(live.curve("Torbole", adesso=ADESSO + dt.timedelta(days=2)) is None,
   "la giornata e' quella di adesso: niente curve di ieri sul grafico di oggi")
snap2 = live.snapshot(adesso=ADESSO)
ok(snap2["luoghi"]["Torbole"].get("curve") is not None,
   "e nel file ogni luogo porta la sua curva")

# --------------------------------------------------------------------------
# 8. Malcesine: la raffica arriva da un altro canale del vento
#
# Gian: "come mai su Malcesine il vento reale non mostra le raffiche?".
# Perche' la pagina live della Fraglia da' solo la raffica massima del
# giorno, che il codice giustamente non spaccia per raffica del campione; la
# raffica dei trenta minuti sta nell'archivio intraday. Ora si chiede anche
# oggi, e i campioni fini prendono il vento da una fonte e la raffica
# dall'altra - ciascuna serie di una definizione sola - e dove la ricorrente
# non e' calcolabile (un dato ogni trenta minuti) si disegna la raffica della
# centralina COL SUO NOME.
# --------------------------------------------------------------------------
# La Fraglia, per nome: dal 2026-09 il vento di Malcesine viene da Addicted
# e la Fraglia da' la direzione, ma il comportamento a due canali (vivo senza
# raffica, intraday con) e' suo e resta da difendere.
ST_M = "malcesine"
G2 = dt.datetime(2026, 9, 15, 6, 0, tzinfo=UTC)          # 08:00 locali
vivo, intra = [], []
for k in range(0, 8 * 60, 8):                              # ogni 8 minuti, senza raffica
    vivo.append((iso_utc(G2 + dt.timedelta(minutes=k)), 10.0 + k / 60.0, None, 190.0))
for k in range(0, 8 * 60, 30):                             # ogni 30, con la raffica
    intra.append((iso_utc(G2 + dt.timedelta(minutes=k)), 9.5 + k / 60.0, 18.0 + k / 60.0, 190.0))
scrivi_campioni(ST_M, vivo, fonte="meteoproject-live")
scrivi_campioni(ST_M, intra, fonte="meteoproject-intraday")
fm = engine.campioni_fini(ST_M, "2026-09-15")
con_w = [r for r in fm if r["wind"] is not None]
con_g = [r for r in fm if r["gust"] is not None]
ok(len(con_w) == 60 and abs(con_w[0]["wind"] - 10.0) < 0.01,
   "il vento viene dal canale vivo, ogni otto minuti (%d punti)" % len(con_w))
ok(len(con_g) == 16 and abs(con_g[0]["gust"] - 18.0) < 0.01,
   "la raffica dal canale intraday, ogni trenta (%d punti)" % len(con_g))
ok(fm and fm[0]["raffica_fonte"] == "raffica della centralina",
   "e si chiama col suo nome, perche' la ricorrente sui 30' non esiste a 30' di passo")
ok(all(r["gust"] is None for r in con_w if r["hour"] * 60 % 30 != 0),
   "il vento vivo non riceve raffiche inventate negli istanti in mezzo")
sm = live.stazione(ST_M, adesso=G2 + dt.timedelta(minutes=8 * 60 + 5))
ok(sm["gust"] is not None and abs(sm["gust"] - (18.0 + 7.5)) < 0.01,
   "il riquadro dell'adesso prende l'ultima raffica data dalla centralina (%.1f)"
   % (sm["gust"] or 0))
sm2 = live.stazione(ST_M, adesso=G2 + dt.timedelta(minutes=8 * 60 + 5))
ok(sm2["wind"] is not None, "e il vento resta quello dell'ultimo campione")
cm = live.curve("Malcesine", adesso=G2 + dt.timedelta(hours=8))
ok(cm is None or "raffica" in cm,
   "la curva di Malcesine, ora da Addicted, non si rompe senza campioni Addicted")
# Con un dato ogni dieci minuti invece la ricorrente c'e', e si chiama cosi'.
ft = engine.campioni_fini(ST, "2026-09-14")
ok(ft and ft[0]["raffica_fonte"] == "ricorrente 30'",
   "a Torbole, coi dieci minuti, la raffica e' la ricorrente e lo dice")

# --------------------------------------------------------------------------
# 9. La raffica del riquadro segue la CADENZA, non un numero fisso
#
# Visto in pagina: Malcesine con il vento stampato e "raffica non disponibile"
# accanto, mentre la raffica era in archivio. Le centraline Addicted mandano
# un dato all'ora, e l'ora in corso non ha ancora il suo massimo: con una
# finestra fissa di 45 minuti il campione precedente - a sessanta - restava
# sempre fuori, e la raffica spariva ogni volta.
# --------------------------------------------------------------------------
ST_H = "oraria_prova"
G3 = dt.datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
orarie = [(iso_utc(G3 + dt.timedelta(hours=k)), 12.0 + k, 20.0 + k, None)
          for k in range(6)]
orarie.append((iso_utc(G3 + dt.timedelta(hours=6)), 18.0, None, None))  # ora in corso
scrivi_campioni(ST_H, orarie, fonte="addicted-json")
sh = live.stazione(ST_H, adesso=G3 + dt.timedelta(hours=6, minutes=20))
ok(sh["wind"] == 18.0, "il vento e' quello dell'ora in corso")
ok(sh["gust"] is not None and abs(sh["gust"] - 25.0) < 0.01,
   "e la raffica e' l'ultima che la centralina ha dato, un'ora prima (%s)"
   % sh["gust"])
ok(sh["cadenza_min"] and sh["cadenza_min"] >= 55,
   "perche' la finestra segue la cadenza dichiarata (%.0f min)" % sh["cadenza_min"])
# Una centralina fitta che tace da due ore non ripesca una raffica vecchia.
ST_F = "fitta_prova"
scrivi_campioni(ST_F, [(iso_utc(G3 + dt.timedelta(minutes=10 * k)), 12.0, 20.0, None)
                       for k in range(12)] +
                [(iso_utc(G3 + dt.timedelta(minutes=200)), 12.0, None, None)],
                fonte="prova")
sf = live.stazione(ST_F, adesso=G3 + dt.timedelta(minutes=210))
ok(sf["gust"] is None,
   "mentre una raffica di due ore prima, su una centralina da dieci minuti,"
   " resta 'non disponibile'")

# --------------------------------------------------------------------------
# 6. "non recente" segue la cadenza della centralina, non un minuto fisso
#
# Visto in pagina: "Campione e' morta" mentre Campione stava rispettando il
# suo ritmo. Le centraline Addicted pubblicano una volta all'ora: alle 23:18
# il dato piu' recente e' quello delle 23:00, e una soglia fissa di 45 minuti
# - pensata per Torbole, che aggiorna ogni dieci - ingialliva mezz'ora su
# ogni ora, come se il dato non arrivasse piu'.
#
# E' lo stesso difetto della raffica qui sopra, la seconda volta: una soglia
# fissa applicata a centraline con cadenze diverse. Percio' la soglia ha UN
# posto (web.stantia_min) e il riquadro se la porta scritta addosso, cosi'
# anche il ricalcolo nel browser usa quella e non una costante sua.
from gardawind import web as W  # noqa: E402

ok(W.stantia_min(10) == W.ETA_STANTIA_MIN,
   "una centralina da dieci minuti mantiene la soglia di sempre (%.0f)"
   % W.stantia_min(10))
ok(W.stantia_min(60) > 60 and W.stantia_min(60) == 3 * 60,
   "una centralina oraria no: la sua soglia sono tre suoi passi (%.0f min)"
   % W.stantia_min(60))
ok(W.stantia_min(None) == W.ETA_STANTIA_MIN and W.stantia_min(0) == W.ETA_STANTIA_MIN,
   "e senza cadenza dichiarata si torna alla soglia fissa: non si inventa")
snap = live.snapshot()
ok(all("stale_min" in v for v in snap["luoghi"].values()),
   "ogni luogo porta la sua soglia in live.json, cosi' il ricalcolo nel "
   "browser non ha bisogno di sapere le cadenze")
blocco = W.adesso_riquadro(config.PLACES[0],
                           {"ts": "2026-09-14T12:00:00Z", "cadenza_min": 60.0}, {})
ok('data-stale="' in blocco,
   "e il riquadro se la porta scritta addosso, cosi' il ricalcolo nel browser "
   "usa quella e non una costante sua")
ok('data-stale="180"' in blocco,
   "con il valore della SUA cadenza, non con la costante")
import inspect  # noqa: E402
ok("getAttribute('data-stale')" in inspect.getsource(W),
   "e il ricalcolo nel browser la legge da li'")

# --------------------------------------------------------------------------
# 7. La curva del misurato esce anche da una centralina ORARIA
#
# Gian: "per torbole funziona ma per campione e malcesine non si aggiorna".
# La curva richiedeva dodici campioni: due ore a Torbole, che misura ogni
# dieci minuti, e mezza giornata a Campione, che pubblica una volta all'ora.
# Cosi' il processo veloce non riconosceva la serie di una centralina oraria e
# non pubblicava la sua curva, mentre la PAGINA la disegnava dalle medie orarie
# - risultato: la curva c'era e restava ferma all'ora della costruzione.
#
# Il numero 12 stava in due posti (engine.campioni_fini e il grafico in
# web.py), che e' come questi difetti sopravvivono. Ora la regola e' una,
# util.serie_disegnabile, ed e' in ARCO DI TEMPO: quanta giornata coprono
# questi campioni, non quanti sono.
from gardawind.util import serie_disegnabile as SD  # noqa: E402

ok(SD([0.0, 60.0, 120.0]) and not SD([0.0, 60.0]),
   "tre campioni su due ore bastano; due no, quale che sia la cadenza")
ok(not SD([0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]),
   "e nove campioni stretti in quaranta minuti non fanno una curva: "
   "e' l'arco che conta, non il conto")
ok(SD([10 * k for k in range(12)]),
   "i dodici campioni da dieci minuti di prima restano disegnabili: "
   "per Torbole non cambia niente")

ST_O = "oraria_curva"
G7 = dt.datetime(2026, 9, 20, 2, 0, tzinfo=UTC)          # 04:00 locali
scrivi_campioni(ST_O, [(iso_utc(G7 + dt.timedelta(hours=k)),
                        8.0 + k, 12.0 + k, None) for k in range(4)],
                fonte="addicted-json")
fo = engine.campioni_fini(ST_O, "2026-09-20")
ok(len(fo) == 4,
   "quattro letture orarie sono una serie disegnabile (%d campioni su %g ore)"
   % (len(fo), (fo[-1]["hour"] - fo[0]["hour"]) if fo else 0))
ok(engine.campioni_fini(ST_O, "2026-09-21") == [],
   "e un giorno senza letture resta senza curva: non si inventa")
# Due letture sole - la prima ora e mezza di una centralina oraria - non
# bastano: una curva su un'ora e' un segmento, e un segmento non descrive
# una giornata.
ST_O2 = "oraria_poche"
scrivi_campioni(ST_O2, [(iso_utc(G7 + dt.timedelta(hours=k)), 8.0, 12.0, None)
                        for k in range(2)], fonte="addicted-json")
ok(engine.campioni_fini(ST_O2, "2026-09-20") == [],
   "con due letture sole non si disegna ancora niente")
