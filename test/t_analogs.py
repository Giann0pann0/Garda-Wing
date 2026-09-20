"""Controlli del motore analogico: proteggono il protocollo, non solo la sintassi."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gardawind import analogs

passati = 0

def ok(cond, msg):
    global passati
    if cond:
        passati += 1; print("PASS " + msg)
    else:
        print("FAIL " + msg)

# Standardizzazione sorgente-specifica.
v = {k: float(i + 1) for i, k in enumerate(analogs.FEATURES)}
st = {k: (v[k] - 2.0, 2.0) for k in analogs.FEATURES}
z = analogs._z(v, st)
ok(z is not None and all(abs(x - 1.0) < 1e-9 for x in z),
   "z-score usa le statistiche passate, non valori assoluti")

# k e' un iperparametro scelto sul 2024 con un criterio scritto PRIMA, e
# confermato una volta sola sul 2025-2026. Il 2026-09-17 e' passato da 3 a 9,
# perche' il 3 era stato scelto con l'ancora sbagliata (vedi il commento su K).
ok(analogs.K == 9, "k=9 e' bloccato dal protocollo validato")

# La mediana di k gradini conserva un gradino maggioritario. Le curve finte
# sono K, non tre scritte a mano: _median_template pretende esattamente K
# vicini, e con tre copie fisse questo controllo e' diventato muto il giorno
# in cui k e' cambiato - restituiva None e l'asserzione non se ne accorgeva.
n = len(analogs.GRID_MIN)


def _gradino(i0):
    return {"curve": tuple(0.2 if i < i0 else 1.0 for i in range(n))}


def _k_vicini(*curve):
    """Le curve date, ripetute fino a fare esattamente K vicini."""
    fuori = [dict(c) for c in curve]
    while len(fuori) < analogs.K:
        fuori += [dict(c) for c in curve][:analogs.K - len(fuori)]
    return fuori[:analogs.K]


meta_finta = {"k": analogs.K, "days": ["a"] * analogs.K}
t = analogs._median_template(_k_vicini(_gradino(50), _gradino(51),
                                       _gradino(80)))
ok(t is not None and t[50] < .5 and t[51] > .9,
   "la mediana di k vicini conserva il gradino maggioritario")

# Nessun onset alignment: la doppia gobba deve rimanere sulla griglia assoluta.
left = {"curve": tuple(1.0 if i < 35 else .2 for i in range(n))}
right = {"curve": tuple(.2 if i < 70 else 1.0 for i in range(n))}
both = {"curve": tuple(1.0 if i < 35 or i >= 70 else .2 for i in range(n))}
t2 = analogs._median_template(_k_vicini(left, right, both))
ok(t2 is not None and t2[20] > .9 and t2[55] < .3 and t2[80] > .9,
   "nessun allineamento dell'ingresso: Peler e Ora non si sovrappongono")

# Applicazione: 10 minuti, stesso picco, nessuna modifica D+0.
base = []
for h in range(4, 22):
    base.append({"hour": float(h), "key": "x", "wind": 8.0,
                 "gust": 12.0, "lo": 6.0, "hi": 10.0,
                 "dir": 180.0, "t2m": 20.0, "cloud": 20.0, "precip": 0.0})
old = analogs.choose
try:
    analogs.choose = lambda day, lead, current=None: (
        tuple(.25 if i < 55 else 1.0 for i in range(n)), dict(meta_finta))
    shaped, meta = analogs.apply_to_profile("2026-09-16", 1, base)
finally:
    analogs.choose = old
ok(len(shaped) == 103 and abs(shaped[1]["hour"] - shaped[0]["hour"] - 1/6) < 1e-9,
   "profilo analogico resta sulla griglia reale di 10 minuti")
ok(abs(max(r["wind"] for r in shaped) - 8.0) < 1e-9,
   "su una sagoma con un plateau lungo un'ora, il livello e il picco"
   " coincidono e restano quelli del motore")
ok(meta and meta["grid_minutes"] == 10,
   "diagnostica dichiara la griglia da 10 minuti")

# --------------------------------------------------------------------------
# Cosa resta invariato: il LIVELLO, non il picco istantaneo
# --------------------------------------------------------------------------
# E' il difetto piu' costoso di questo modulo, e il controllo che lo avrebbe
# preso non c'era. Il motore prevede il massimo delle medie ORARIE; la curva
# mostrata ha un punto ogni dieci minuti e il suo massimo istantaneo e' piu'
# alto - deve esserlo, una raffica di mezz'ora non e' la media dell'ora.
# Imponendo il massimo istantaneo si metteva il numero previsto per una
# grandezza al posto di un'altra, l'11% piu' bassa, e la curva prometteva due
# ore di vento dove ce n'erano dieci minuti (falsi allarmi 36% invece di 6%).
#
# La sagoma qui ha una PUNTA di dieci minuti: il suo massimo istantaneo e'
# molto piu' alto delle sue medie orarie, quindi le due ancore danno numeri
# diversi e il controllo distingue.
punta = tuple(1.0 if i == 60 else .3 for i in range(n))
old = analogs.choose
try:
    analogs.choose = lambda day, lead, current=None: (punta, dict(meta_finta))
    con_punta, meta_p = analogs.apply_to_profile("2026-09-16", 1, base)
finally:
    analogs.choose = old
liv = analogs.livello_orario([(r["hour"] * 60.0, r["wind"]) for r in con_punta],
                             analogs.GRID_MIN[0], analogs.GRID_MIN[-1] + 1)
picco = max(r["wind"] for r in con_punta)
ok(liv is not None and abs(liv - 8.0) < 1e-6,
   "il LIVELLO del motore resta esattamente quello: massimo delle medie"
   " orarie %.3f su 8.00" % (liv or -1))
ok(picco > 8.0 + 1e-6,
   "e il picco istantaneo lo SUPERA, come fa una curva a dieci minuti"
   " (%.2f kn): imporglielo uguale era l'errore" % picco)
ok(meta_p and abs(meta_p.get("livello_orario_preservato", 0) - 8.0) < 1e-9,
   "e la diagnostica dichiara il livello conservato, non il picco")
unchanged, m0 = analogs.apply_to_profile("2026-09-15", 0, base)
ok(unchanged == base and m0 is None, "D+0 non usa implicitamente il modello D+1")

# Ripidezza: un gradino da 3 a 10 in 30 minuti deve misurare 7, non essere smussato.
curve = tuple(3.0 if i < 60 else 10.0 for i in range(n))
ok(abs(analogs._steepness(curve) - 7.0) < 1e-9,
   "metrica di ripidezza protegge le transizioni in 30 minuti")

# --------------------------------------------------------------------------
# Il banco della porta: UN rapporto finto, costruito dai numeri congelati
# --------------------------------------------------------------------------
# Era scritto due volte, e le due copie si sono subito disallineate. Qui e'
# uno: parte da BENCHMARK, cosi' se i numeri congelati cambiano il banco li
# segue invece di contraddirli, e porta accanto la curva liscia e il nullo
# MISURATI - perche' la porta nuova confronta relazioni, non solo valori, e un
# rapporto senza il riferimento non e' un rapporto.
def rapporto(n_giorni=None):
    if n_giorni is None:
        n_giorni = analogs.EXPECTED_CONFIRM_DAYS
    r = {
        "usable": True, "n": n_giorni, "leads": {},
        "from": "2025-01-01", "to": "2026-09-12",
        # Il nullo misurato: PAREGGIA col modello nell'Ora (93,8% di colpi
        # contro 93,3%). E' il numero che ha cambiato la porta.
        "null": {"hits": .938, "false_alarms": .070, "minute_error": 72.9,
                 "bias_minutes": -3.7, "steepness": 5.57,
                 "true_steepness": 6.99, "steepness_gap": 2.43},
        # La curva liscia misurata: vince sul binario e sbaglia la durata di
        # quarantadue minuti.
        "liscia": {"hits": .981, "false_alarms": .065, "minute_error": 67.0,
                   "bias_minutes": 42.4, "steepness": 1.86,
                   "true_steepness": 6.99, "steepness_gap": 4.97,
                   "peler": {"hits": .973, "false_alarms": .114,
                             "minute_error": 34.4, "bias_minutes": 23.1,
                             "steepness": .56, "true_steepness": 3.89,
                             "steepness_gap": 3.19}},
    }
    for lead, vals in analogs.BENCHMARK.items():
        row = dict(vals)
        row["true_steepness"] = analogs.RIPIDEZZA_VERA_ORA
        row["steepness_gap"] = 2.2
        row["peler"] = {"hits": .929, "false_alarms": .043,
                        "minute_error": 25.0, "bias_minutes": 1.0,
                        "steepness": 2.51, "true_steepness": 3.89,
                        "steepness_gap": 1.58}
        r["leads"][lead] = row
    return r


gate, why = analogs.benchmark_gate(rapporto())
ok(gate and not why, "gate apre sui numeri del benchmark congelato: %s" % why[:1])
rep = rapporto()
rep["leads"][1]["steepness"] = 3.0
gate, why = analogs.benchmark_gate(rep)
ok(not gate and why, "gate chiude se la curva torna liscia")

# --------------------------------------------------------------------------
# La persistenza e' UNA, e viene da fuori
# --------------------------------------------------------------------------
# Era il difetto piu' silenzioso della prima stesura: `run >= 3` su una
# griglia di dieci minuti sono VENTI minuti, non trenta, perche' tre campioni
# coprono due intervalli. La porta misurava quindi una cosa piu' facile della
# specifica, e i suoi numeri non erano confrontabili con il benchmark.
from gardawind.orari import PERSISTENZA_MIN

ok(analogs._persistenza_min() == PERSISTENZA_MIN,
   "la mezz'ora della porta e' quella di orari.py, non una copia (%g)"
   % analogs._persistenza_min())
ok(analogs._punti_persistenza() == 4,
   "trenta minuti su griglia da dieci sono QUATTRO campioni, non tre (%d)"
   % analogs._punti_persistenza())

n = len(analogs.GRID_MIN)
i11 = analogs.GRID_MIN.index(11 * 60)


def con_tratto(punti_sopra, da=i11 + 6):
    """Una curva piatta a 6 kn con un tratto a 14 kn lungo `punti_sopra`."""
    return tuple(14.0 if da <= i < da + punti_sopra else 6.0 for i in range(n))


ok(not analogs._sustained(con_tratto(3)),
   "venti minuti sopra soglia NON sono una giornata navigabile")
ok(analogs._sustained(con_tratto(4)),
   "trenta minuti si': e' la stessa mezz'ora della climatologia")
ok(analogs._minutes_above(con_tratto(4)) == 40,
   "i minuti sopra soglia contano i campioni per dieci (%d)"
   % analogs._minutes_above(con_tratto(4)))

# --------------------------------------------------------------------------
# La porta deve poter APRIRE, non solo chiudere
# --------------------------------------------------------------------------
# Con il controllo esatto sul campione, una giornata di differenza
# nell'archivio - un buco di centralina che si chiude, una run in piu' -
# chiudeva la porta per sempre con un messaggio che non diceva niente. La
# tolleranza e' dichiarata, e il conteggio vero si stampa sempre.
# --------------------------------------------------------------------------
# La porta guarda anche la MATTINA, e sa cosa pretendere
# --------------------------------------------------------------------------
# La forma analogica cambia tutta la giornata, ma la porta misurava solo
# 11:00-20:00: la mattina veniva sostituita e promossa sulla base di numeri
# che parlavano del pomeriggio. Ora si misura anche il Peler, e si pretende
# cio' che il metodo ha: calibrazione, non discriminazione.
senza_mattina = rapporto(analogs.EXPECTED_CONFIRM_DAYS)
for row in senza_mattina["leads"].values():
    row.pop("peler")
gm, wm = analogs.benchmark_gate(senza_mattina)
ok(not gm and any("mattina non misurata" in x for x in wm),
   "una mattina non misurata non passa piu': %s" % wm[:1])

liscia_mattina = rapporto(analogs.EXPECTED_CONFIRM_DAYS)
for row in liscia_mattina["leads"].values():
    row["peler"] = dict(row["peler"], steepness=0.3, bias_minutes=-46.0)
gl, wl = analogs.benchmark_gate(liscia_mattina)
ok(not gl and any("troppo liscia" in x for x in wl)
   and any("sbilanciata" in x for x in wl),
   "e una mattina piatta e corta come la curva liscia chiude la porta"
   " dicendo entrambe le cose")

# Ma NON si pretendono colpi sulla mattina: separando forma e livello - col
# picco vero regalato dentro la finestra - il nullo ne prende quanti il
# modello (83,3% contro 83,0%), quindi chiedere
# discriminazione vorrebbe dire chiudere la porta per un merito che il metodo
# non ha mai dichiarato di avere. Quella la decide il livello della sessione.
colpi_scarsi = rapporto(analogs.EXPECTED_CONFIRM_DAYS)
for row in colpi_scarsi["leads"].values():
    row["peler"] = dict(row["peler"], hits=.50, false_alarms=.44)
gc, wc = analogs.benchmark_gate(colpi_scarsi)
ok(gc and not wc,
   "colpi deboli sulla mattina, con la durata giusta, non chiudono nulla")

atteso = analogs.EXPECTED_CONFIRM_DAYS
tol = analogs.TOLLERANZA_CONFERMA_GG
g1, _w = analogs.benchmark_gate(rapporto(atteso - 3))
ok(g1, "tre giornate in meno non chiudono la porta")
g2, w2 = analogs.benchmark_gate(rapporto(atteso - tol - 40))
ok(not g2 and any("campione" in x for x in w2),
   "ma un campione molto diverso la chiude, dicendo il conteggio: %s" % w2[:1])
g3, w3 = analogs.benchmark_gate({"usable": False, "reason": "confirm_days"})
ok(not g3 and w3 and "confirm_days" in str(w3),
   "e senza misura la porta dice PERCHE' non ha misurato, non solo che e' chiusa")

# --------------------------------------------------------------------------
# Anche la LIBRERIA deve poter esistere con un archivio che cresce
# --------------------------------------------------------------------------
# La finestra di addestramento e' chiusa nel 2023, ma i dati di quelle
# giornate no: un recupero di storico della centralina cambia il conteggio, e
# col controllo esatto il motore si spegneva per sempre senza dirlo. Qui si
# pretende che una libreria vicina si costruisca e che una molto diversa no,
# dicendo il numero vero.
import datetime as _dt


def _finta_libreria(n_giorni):
    giorno = _dt.date(2013, 1, 1)
    era, curve = {}, {}
    for i in range(n_giorni):
        d = (giorno + _dt.timedelta(days=i)).isoformat()
        era[d] = {k: float((i * 7 + j * 13) % 100) for j, k in enumerate(analogs.FEATURES)}
        curve[d] = tuple(0.3 if x < 50 else 1.0 for x in range(n))
    return era, curve


def _con_libreria(n_giorni):
    va, vo = analogs._archive_daily, analogs._observed_curves
    era, curve = _finta_libreria(n_giorni)
    analogs._archive_daily = lambda source, a, b: era
    analogs._observed_curves = lambda *a, **k: curve
    try:
        return analogs._build_library()
    finally:
        analogs._archive_daily, analogs._observed_curves = va, vo


lib, st_era, diag = _con_libreria(analogs.EXPECTED_TRAIN_DAYS)
ok(lib is not None and len(lib) == analogs.EXPECTED_TRAIN_DAYS,
   "con il campione congelato la libreria si costruisce (%s)" % diag.get("reason"))
lib2, _s2, d2 = _con_libreria(analogs.EXPECTED_TRAIN_DAYS + 12)
ok(lib2 is not None and len(lib2) == analogs.EXPECTED_TRAIN_DAYS + 12,
   "dodici giornate recuperate dallo storico non spengono il motore (%s)"
   % d2.get("reason"))
lib3, _s3, d3 = _con_libreria(analogs.EXPECTED_TRAIN_DAYS - 300)
ok(lib3 is None and d3.get("reason") == "training_days"
   and d3.get("n") == analogs.EXPECTED_TRAIN_DAYS - 300,
   "trecento in meno la spengono, e la diagnostica dice quante ce n'erano (%s)"
   % d3)
ok(d3.get("tolerance") == analogs.TOLLERANZA_ADDESTRAMENTO_GG,
   "con la tolleranza dichiarata accanto, non da indovinare")

# --------------------------------------------------------------------------
# Ogni finestra di regime tiene il SUO livello
# --------------------------------------------------------------------------
# Anche il Peler e' una curva, e con un solo fattore per la giornata la
# mattina ereditava il picco del pomeriggio. Misurato sulle 617 giornate di
# conferma, nella finestra utile del Peler a 10 kn: falsi allarmi 37,7% col
# picco della giornata, 20,3% col livello per finestra, e i colpi dal 58,9%
# all'83,0%. Il picco della giornata, del resto, cade nella finestra dell'Ora
# solo nel 65% dei giorni.
FIN2 = ((4 * 60.0, 11 * 60.0), (11 * 60.0, 21 * 60.0 + 1))
bassa_alta = []
for h in range(4, 22):
    w = 8.0 if h < 11 else 20.0
    bassa_alta.append({"hour": float(h), "key": "x", "wind": w, "gust": w * 1.3,
                       "lo": w - 2, "hi": w + 2, "dir": 200.0, "t2m": 20.0,
                       "cloud": 10.0, "precip": 0.0})
mezzo_uno = tuple(.5 if m < 11 * 60 else 1.0 for m in analogs.GRID_MIN)
old = analogs.choose
try:
    analogs.choose = lambda day, lead, current=None: (
        mezzo_uno, {"k": 3, "days": ["a", "b", "c"]})
    senza, _ms = analogs.apply_to_profile("2026-09-17", 1, bassa_alta)
    con, mc = analogs.apply_to_profile("2026-09-17", 1, bassa_alta, FIN2)
    piatta = tuple(1.0 for _m in analogs.GRID_MIN)
    analogs.choose = lambda day, lead, current=None: (
        piatta, {"k": 3, "days": ["a", "b", "c"]})
    piatto, _mp = analogs.apply_to_profile("2026-09-17", 1, bassa_alta, FIN2)
finally:
    analogs.choose = old


def picco_mattina(p):
    return max(r["wind"] for r in p if r["hour"] * 60 < 11 * 60)


ok(abs(picco_mattina(senza) - 10.0) < 1e-6,
   "col picco della giornata la mattina esce a 10 kn da una previsione di 8"
   " (%.2f)" % picco_mattina(senza))
ok(picco_mattina(con) < 8.5,
   "col livello per finestra torna alla previsione del Peler (%.2f)"
   % picco_mattina(con))
ok(abs(max(r["wind"] for r in con) - 20.0) < 1e-9,
   "e il picco della giornata resta ESATTAMENTE quello del motore: e' il"
   " numero di cui parlano probabilita', bande e verifica")
ok(mc.get("livelli_per_finestra") and len(mc["livelli_per_finestra"]) == 2,
   "la diagnostica dichiara un livello per finestra (%s)"
   % (mc.get("livelli_per_finestra"),))

# Il raccordo: c'e', ed e' piu' corto della persistenza. Se fosse lungo come
# lei, la fine della mattina tirata verso il livello dell'Ora potrebbe da sola
# produrre la mezz'ora sopra soglia - un falso allarme fabbricato dal
# raccordo, non dalla previsione.
ok(analogs._raccordo_min() * 2 <= PERSISTENZA_MIN,
   "il raccordo intero (%g') non supera la persistenza (%g')"
   % (analogs._raccordo_min() * 2, PERSISTENZA_MIN))
liv = [r["wind"] for r in piatto]
dentro = [v for v in liv if 8.0 + 1e-9 < v < 20.0 - 1e-9]
ok(dentro and len(dentro) <= int(PERSISTENZA_MIN / 10),
   "con forma piatta il passaggio fra i due livelli dura pochi campioni,"
   " meno della persistenza (%d)" % len(dentro))
ok(dentro == sorted(dentro),
   "e li attraversa in salita, senza gradini inventati")

# Chi decide sulla DIMENSIONE del campione e' uno solo: la porta. Dentro
# validation_report il confronto col numero congelato era un secondo giudice
# senza tolleranza, e vinceva lui - la misura non veniva nemmeno prodotta. Il
# vincolo che resta li' e' un altro: i tre lead devono misurare le STESSE
# giornate. Questo controllo e' strutturale perche' il difetto e' strutturale:
# non si vede nei numeri, si vede in chi confronta cosa.
import inspect

sorgente = inspect.getsource(analogs.validation_report)
ok("!= EXPECTED_CONFIRM_DAYS" not in sorgente
   and "> EXPECTED_CONFIRM_DAYS" not in sorgente,
   "dentro la misura il numero congelato non fa da giudice, solo da etichetta")
ok('v.get("n") != len(days)' in sorgente,
   "ma i tre lead devono aver misurato le stesse giornate, non un numero fisso")
ok("EXPECTED_CONFIRM_DAYS" in inspect.getsource(analogs.benchmark_gate)
   and "TOLLERANZA_CONFERMA_GG" in inspect.getsource(analogs.benchmark_gate),
   "e il confronto col campione congelato vive nella porta, con la tolleranza")

# --------------------------------------------------------------------------
# La misura si attraversa per intero, non solo si legge
# --------------------------------------------------------------------------
# validation_report non era mai stato eseguito: in prova la libreria non
# esiste, quindi esce al primo controllo e tutti i controlli restavano verdi
# senza toccare una riga di misura. Qui si finge SOLO l'accesso ai dati -
# archivio, curve, curve grezze - e si pretende che la misura arrivi in fondo
# con le due finestre, il nullo e la curva liscia.
def _finto_archivio(giorni, mattina_forte):
    """Curve vere di forma: mattina a scelta, Ora sempre a gradino."""
    i11 = analogs.GRID_MIN.index(11 * 60)
    i14 = analogs.GRID_MIN.index(14 * 60)
    era, curve, grezze = {}, {}, {}
    for j, d in enumerate(giorni):
        forte = mattina_forte(j)
        y = []
        for i, m in enumerate(analogs.GRID_MIN):
            if i < i11:
                y.append(13.0 if forte else 4.0)
            elif i < i14:
                y.append(5.0)
            else:
                y.append(22.0)
        picco = max(y)
        curve[d] = tuple(v / picco for v in y)
        grezze[d] = tuple(y)
        era[d] = {k: float((j * 3 + q * 5) % 40) + (10.0 if forte else 0.0)
                  for q, k in enumerate(analogs.FEATURES)}
    return era, curve, grezze


gg_tr = [(_dt.date(2013, 3, 1) + _dt.timedelta(days=i)).isoformat()
         for i in range(analogs.EXPECTED_TRAIN_DAYS)]
gg_cf = [(_dt.date(2025, 7, 1) + _dt.timedelta(days=i)).isoformat()
         for i in range(40)]
era_tr, curve_tr, _gr = _finto_archivio(gg_tr, lambda j: j % 2 == 0)
era_cf, curve_cf, grezze_cf = _finto_archivio(gg_cf, lambda j: j % 2 == 0)

sa, so, sr, sc = (analogs._archive_daily, analogs._observed_curves,
                  analogs._raw_curve, dict(analogs._CACHE))
try:
    analogs._CACHE.update({"library": None, "era_stats": None,
                           "lead_stats": {}, "at": 0.0})
    analogs._archive_daily = lambda source, a, b: (
        era_tr if source == "era5" else era_cf)
    analogs._observed_curves = lambda *a, **k: (
        curve_cf if a and a[0] >= "2025" else curve_tr)
    analogs._raw_curve = lambda day: grezze_cf.get(day)
    rap = analogs.validation_report("2025-07-01", "2025-08-09")
finally:
    (analogs._archive_daily, analogs._observed_curves,
     analogs._raw_curve) = sa, so, sr
    analogs._CACHE.clear(); analogs._CACHE.update(sc)

ok(rap.get("usable"), "la misura arriva in fondo (%s)"
   % (rap.get("reason") or rap.get("diagnostic") or "ok"))
ok(rap.get("n") == len(gg_cf),
   "su tutte le giornate del campione (%s)" % rap.get("n"))
uno = (rap.get("leads") or {}).get(1) or {}
ok(uno.get("hits") is not None and uno.get("peler", {}).get("hits") is not None,
   "e misura DUE finestre, non una: Ora %s, Peler %s"
   % (uno.get("hits"), (uno.get("peler") or {}).get("hits")))
ok((uno.get("peler") or {}).get("navigabili", 0) > 0,
   "con giornate di Peler davvero navigabili nel campione (%s)"
   % (uno.get("peler") or {}).get("navigabili"))
ok(rap.get("liscia") and (rap["liscia"].get("peler") or {}).get("hits") is not None,
   "e accanto c'e' la curva liscia, calcolata dalla libreria")
ok(rap.get("null") is not None, "e il nullo, che resta obbligatorio")
# La finestra del Peler NON e' quella del regime: a luglio comincia alle 06:00
# per l'ora pratica, non alle 04:00.
a_lug, b_lug = analogs._finestra_peler("2025-07-15")
ok(a_lug >= 6 * 60 and b_lug <= 11 * 60,
   "la finestra del Peler e' quella utile, non le sette ore del regime"
   " (%02d:%02d-%02d:%02d)" % (a_lug // 60, a_lug % 60, b_lug // 60, b_lug % 60))

# --------------------------------------------------------------------------
# Il nullo e' un controllo di SANITA', non una gara da vincere
# --------------------------------------------------------------------------
# Con l'ancora oraria il nullo - le stesse sagome assegnate al giorno
# sbagliato - pareggia col modello nella finestra dell'Ora: vantaggio +1,0
# punti, intervallo da -2,7 a +5,0, cioe' zero. La scelta dei vicini non
# discrimina meglio del caso, e la mattina lo diceva gia'.
#
# Quindi la porta non puo' pretendere un vantaggio sul nullo: pretenderebbe un
# merito che il metodo non ha mai avuto, e si chiuderebbe per sempre. Quello
# che si pretende e' che il nullo non sia MEGLIO: se rimescolare le giornate
# migliora le previsioni, il legame fra condizioni e sagoma e' rotto.
nullo_pari = rapporto()
nullo_pari["null"] = dict(nullo_pari["null"], hits=.938, false_alarms=.070)
g4, w4 = analogs.benchmark_gate(nullo_pari)
ok(g4 and not w4,
   "un nullo che PAREGGIA non chiude la porta: e' il risultato misurato,"
   " non un difetto (%s)" % w4[:1])

nullo_bravo = rapporto()
nullo_bravo["null"] = dict(nullo_bravo["null"], hits=.99, false_alarms=.01)
g5, w5 = analogs.benchmark_gate(nullo_bravo)
ok(not g5 and any("nullo fa" in x and "MEGLIO" in x for x in w5),
   "ma un nullo chiaramente migliore la chiude, dicendo i punti: %s" % w5[:1])

senza_nullo = rapporto()
senza_nullo["null"] = {}
g6, w6 = analogs.benchmark_gate(senza_nullo)
ok(not g6 and any("nullo non misurato" in x for x in w6),
   "e senza nullo la porta non apre per fiducia")

# --------------------------------------------------------------------------
# La curva liscia e' il riferimento, e la porta la pretende
# --------------------------------------------------------------------------
# Senza di lei "93% di colpi" non e' un numero che vuol dire qualcosa: la
# liscia ne fa 98, e lo paga promettendo quarantadue minuti di troppo. E'
# l'unico modo di dire cosa la forma guadagna e cosa costa.
senza_liscia = rapporto()
senza_liscia.pop("liscia")
g7, w7 = analogs.benchmark_gate(senza_liscia)
ok(not g7 and any("liscia non misurata" in x for x in w7),
   "senza la curva liscia la porta non apre: %s" % w7[:1])

# Il non-degrado sul binario: la forma sta 3,8 punti sotto la liscia e va
# bene, perche' il merito e' altrove. Un crollo no - e il valore scelto qui
# sta DENTRO la banda dei numeri congelati, altrimenti il controllo passerebbe
# per un'altra ragione e non proverebbe niente.
crollo = rapporto()
crollo["leads"][1] = dict(crollo["leads"][1], hits=.875)
g8, w8 = analogs.benchmark_gate(crollo)
ok(not g8 and any("crollo" in x for x in w8),
   "una forma che crolla sul binario chiude la porta, e lo dice cosi': %s"
   % w8[:1])

# La calibrazione: e' l'unica cosa che la porta pretende come VANTAGGIO,
# perche' e' l'unica che la forma ha davvero. E si pretende come DIFFERENZA:
# se un giorno la curva liscia fosse calibrata - fosse un altro modello, o
# cambiasse il lago - la forma dovrebbe riguadagnarsi il suo merito, non
# ereditarlo da un confronto vinto nel 2026.
liscia_brava = rapporto()
liscia_brava["liscia"] = dict(liscia_brava["liscia"], bias_minutes=20.0)
g9, w9 = analogs.benchmark_gate(liscia_brava)
ok(not g9 and any("sulla durata la forma guadagna solo" in x for x in w9),
   "contro una liscia calibrata il merito va riguadagnato: %s" % w9[:1])

# E lo scarto di ripidezza, che e' diverso dalla ripidezza mediana: una curva
# sempre ripida ha la mediana giusta e sbaglia tutti i giorni piatti.
sempre_ripida = rapporto()
sempre_ripida["leads"][1] = dict(sempre_ripida["leads"][1], steepness_gap=4.9)
g10, w10 = analogs.benchmark_gate(sempre_ripida)
ok(not g10 and any("piu' vicina al vero" in x for x in w10),
   "e una ripidezza che non e' piu' vicina al vero della liscia la chiude: %s"
   % w10[:1])

# Sui falsi allarmi il requisito e' il BUDGET, e sta da solo: una banda
# centrata sul 5,5% misurato sarebbe piu' stretta del budget, quindi il budget
# non potrebbe mai scattare - due guardie sullo stesso numero, di cui una muta.
ok("false_alarms" not in analogs.TOLLERANZA_BENCHMARK,
   "i falsi allarmi non hanno una banda: hanno un budget, e uno solo")
ok(analogs.BUDGET_FALSI > analogs.BENCHMARK[1]["false_alarms"],
   "il budget dei falsi (%.0f%%) e' sopra il misurato (%.1f%%): e' un limite,"
   " non una taratura"
   % (100 * analogs.BUDGET_FALSI, 100 * analogs.BENCHMARK[1]["false_alarms"]))
oltre = rapporto()
oltre["leads"][1] = dict(oltre["leads"][1], false_alarms=.20)
g11, w11 = analogs.benchmark_gate(oltre)
ok(not g11 and any("budget" in x for x in w11),
   "e oltre il budget la porta si chiude dicendo il budget: %s"
   % [x for x in w11 if "budget" in x][:1])

# --------------------------------------------------------------------------
# Il comando che STAMPA la validazione, lanciato per davvero
# --------------------------------------------------------------------------
# Il 17 settembre la porta e' rimasta chiusa per una riga di stampa: il
# comando nominava una costante della porta che era stata cancellata, e
# moriva DOPO le tabelle e PRIMA di promuovere. Sullo schermo sembrava tutto
# andato bene - i numeri erano quelli giusti - e non apriva niente.
#
# Il banco non lo prese perche' controllava la porta e non il comando che la
# chiama. Adesso il comando si lancia: se un giorno si rinomina una soglia,
# questo controllo casca subito e non dopo, sul Mac, alle nove di sera.
import io as _io
import contextlib as _ctx

from gardawind import indagini as cli

# La promozione NON deve toccare il database: un rapporto finto che apre la
# porta vera sarebbe il peggior effetto collaterale possibile di un test - chi
# lancia questo file a mano si troverebbe il prodotto promosso senza aver
# validato niente. Quindi si intercetta la scrittura e si controlla COSA
# avrebbe scritto, che e' anche un controllo in piu'.
from gardawind import store as _store

vr, ms = analogs.validation_report, _store.meta_set
scritto = []
try:
    analogs.validation_report = lambda *a, **k: rapporto()
    _store.meta_set = lambda chiave, valore: scritto.append((chiave, valore))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cli.cmd_analoghi_validazione()
    uscita = buf.getvalue()
finally:
    analogs.validation_report, _store.meta_set = vr, ms

ok("PORTA APERTA" in uscita,
   "il comando di validazione arriva fino al verdetto e lo stampa")
ok(scritto == [(analogs.GATE_KEY, analogs.GATE_SIGNATURE)],
   "e la promozione scrive la firma dichiarata, una volta sola (%s)" % scritto)
for atteso in ("D+1", "nullo", "liscia", "PELER", "VANTAGGIO"):
    ok(atteso in uscita, "e stampa la riga '%s'" % atteso)

# E non deve nominare soglie che non esistono: se la stampa cita una costante,
# quella costante deve stare in analogs, o il comando muore a meta'.
import re as _re

citate = set(_re.findall(r"analogs\.([A-Z][A-Z0-9_]{3,})",
                         inspect.getsource(cli.cmd_analoghi_validazione)))
mancanti = sorted(c for c in citate if not hasattr(analogs, c))
ok(not mancanti,
   "ogni costante citata dal comando esiste in analogs (%s)" % mancanti)

# La mattina, sulla durata, DEVE battere la liscia: e' il posto dove k=9 ha
# guadagnato di piu' (25 minuti di errore contro 34).
mattina_lunga = rapporto()
for row in mattina_lunga["leads"].values():
    row["peler"] = dict(row["peler"], minute_error=33.0)
g12, w12 = analogs.benchmark_gate(mattina_lunga)
ok(not g12 and any("sulla mattina la forma non batte la liscia" in x
                   for x in w12),
   "una mattina che sbaglia la durata come la liscia chiude la porta: %s"
   % w12[:1])

print("%d controlli analoghi" % passati)
