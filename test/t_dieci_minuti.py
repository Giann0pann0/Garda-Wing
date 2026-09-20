"""Il profilo a dieci minuti, dalla libreria alla pagina.

Questo file esiste per un motivo preciso: quando il motore analogico e'
arrivato, tutti i 992 controlli erano verdi e non ne esercitavano nemmeno uno
il percorso nuovo. Il motivo e' che in prova la libreria storica non esiste,
`choose()` fallisce chiuso e restituisce il profilo di prima - quindi la suite
provava il codice vecchio e diceva che andava bene.

Un controllo che non attraversa il codice nuovo non e' un controllo verde: e'
un controllo assente. Qui il percorso si attraversa per intero, con una
libreria finta ma una forma vera - un gradino come quello dell'Ora - e si
pretendono tre cose:

  1. il profilo che esce ha 103 punti e ore FRAZIONARIE, perche' il gradino
     vive nei dieci minuti e un ricampionamento orario lo distrugge;
  2. il picco resta quello del motore. La forma cambia, il livello no: se
     cambiasse anche il livello, tutte le porte del modello - probabilita',
     bande, verifica - starebbero misurando una cosa diversa da quella
     mostrata;
  3. la PAGINA regge quel profilo. Il grafico, il marcatore "adesso", la
     scheda del Peler e la riga dello scarto sono stati scritti quando il
     profilo aveva una riga per ora, e tre di loro cercano l'ora esatta.
"""
import os
import re
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwdieci"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwdieci", ignore_errors=True)
os.makedirs("/tmp/gwdieci", exist_ok=True)

from gardawind import analogs, config, engine, store, web

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
store.init()

N = len(analogs.GRID_MIN)
I_ORA = analogs.GRID_MIN.index(13 * 60 + 40)      # il gradino alle 13:40


def gradino():
    """Una forma normalizzata come l'Ora vera: piatta, poi su in mezz'ora."""
    out = []
    for i in range(N):
        if i < I_ORA:
            out.append(0.18)
        elif i < I_ORA + 3:
            out.append(0.18 + (i - I_ORA + 1) / 3.0 * 0.72)
        else:
            out.append(0.90 + 0.10 * min(1.0, (i - I_ORA - 3) / 12.0))
    return tuple(out)


def profilo_orario(base=20.0):
    out = []
    for h in range(4, 21):
        w = base * (0.3 + 0.7 * max(0.0, 1 - abs(h - 16) / 6.0))
        out.append({"hour": h, "key": "2026-09-14T%02d:00:00Z" % h,
                    "wind": w, "gust": w * 1.4, "lo": max(0.0, w - 2),
                    "hi": w + 2, "dir": 200.0, "t2m": 24.0, "cloud": 20.0,
                    "precip": 0.0})
    return out


# --------------------------------------------------------------------------
# 1. Il percorso nuovo viene attraversato davvero
# --------------------------------------------------------------------------
base = profilo_orario()
vecchio_choose = analogs.choose
analogs.choose = lambda day, lead, current=None: (
    gradino(), {"k": 3, "days": ["2018-07-03", "2019-08-11", "2021-06-28"],
                "distances": [0.4, 0.5, 0.6], "training_days": 4020,
                "source": "finto, per il controllo"})
try:
    forma, meta = analogs.apply_to_profile("2026-09-16", 1, base)
finally:
    analogs.choose = vecchio_choose

ok(forma is not base and meta is not None,
   "con la libreria disponibile il profilo viene SOSTITUITO, non restituito")
ok(len(forma) == N == 103,
   "e ha i 103 punti della griglia a dieci minuti (%d)" % len(forma))
ore = [r["hour"] for r in forma]
ok(any(abs(h - round(h)) > 1e-9 for h in ore),
   "con ore frazionarie: se fossero tutte intere il gradino sarebbe perduto")
ok(abs(ore[1] - ore[0] - 1.0 / 6.0) < 1e-9,
   "il passo e' dieci minuti (%.4f h)" % (ore[1] - ore[0]))

# Il LIVELLO: la forma cambia, il livello no - e "livello" e' il massimo delle
# medie ORARIE, che e' la grandezza che il motore prevede. Il picco istantaneo
# della curva a dieci minuti puo' e deve stare piu' alto: una raffica di
# mezz'ora non e' la media dell'ora. Prima qui si pretendeva che i due
# coincidessero, e quella pretesa era il difetto: metteva il numero previsto
# per una grandezza al posto di un'altra, l'11% piu' bassa.
livello_prima = max(r["wind"] for r in base)     # il base ha un punto per ora
livello_dopo = analogs.livello_orario(
    [(float(r["hour"]) * 60.0, float(r["wind"])) for r in forma],
    analogs.GRID_MIN[0], analogs.GRID_MIN[-1] + 1)
ok(livello_dopo is not None and abs(livello_prima - livello_dopo) < 1e-6,
   "il livello del motore resta identico (%.2f -> %.2f)"
   % (livello_prima, livello_dopo or -1))
ok(max(r["wind"] for r in forma) >= livello_prima - 1e-9,
   "e il picco istantaneo non sta SOTTO il livello (%.2f, livello %.2f)"
   % (max(r["wind"] for r in forma), livello_prima))
ok(meta.get("livello_orario_preservato") == livello_prima,
   "e la diagnostica dichiara il livello, invece di lasciarlo da verificare")

# La ripidezza: e' il numero per cui tutto questo esiste. Va misurata sulla
# stessa mezz'ora di orologio per entrambe, altrimenti si confrontano due
# griglie invece di due curve - ed e' l'errore che questo controllo ha fatto
# alla prima scrittura, contando tre PASSI invece di trenta MINUTI.
def ripidezza(righe, minuti=30.0):
    pts = sorted((float(r["hour"]) * 60.0, float(r["wind"])) for r in righe)

    def a_minuto(m):
        for i in range(len(pts) - 1):
            xa, ya = pts[i]
            xb, yb = pts[i + 1]
            if xa <= m <= xb:
                if xb == xa:
                    return ya
                return ya + (m - xa) / (xb - xa) * (yb - ya)
        return None

    peggio = 0.0
    m = pts[0][0]
    while m + minuti <= pts[-1][0]:
        a, b = a_minuto(m), a_minuto(m + minuti)
        if a is not None and b is not None:
            peggio = max(peggio, b - a)
        m += 10.0
    return peggio


r_forma, r_base = ripidezza(forma), ripidezza(base)
ok(r_forma > 3.0 * r_base,
   "la forma analogica sale molto piu' ripida della liscia: %.1f contro %.1f"
   " kn in mezz'ora vera" % (r_forma, r_base))
ok(r_base < 2.0,
   "e la liscia non arriva a due nodi in mezz'ora: e' il difetto che il"
   " motore analogico esiste per togliere (%.1f)" % r_base)
ok(all(r["gust"] >= r["wind"] for r in forma),
   "e la raffica non scende mai sotto la media")
ok(all(r["lo"] <= r["wind"] <= r["hi"] for r in forma),
   "la banda contiene sempre la sua curva")

# Oltre l'ultima scadenza promossa non si tocca niente. Attenzione: questo
# controllo va fatto CON la libreria disponibile, altrimenti passa per il
# motivo sbagliato - senza libreria choose() fallisce chiuso e restituisce il
# profilo di prima per qualunque scadenza, compresa una promossa. Era
# esattamente cosi' finche' le scadenze erano (1,2,3): quando D+4 e' entrato,
# la riga diceva ancora "oltre D+3" ed era verde perche' in prova la libreria
# non c'e'. Un controllo verde per il motivo sbagliato e' un controllo assente.
analogs.choose = lambda day, lead, current=None: (
    gradino(), {"k": 3, "days": ["a", "b", "c"], "distances": [.4, .5, .6],
                "training_days": 4020, "source": "finto"})
try:
    ultima = max(analogs.LEADS)
    dentro, m_dentro = analogs.apply_to_profile("2026-09-20", ultima, base)
    fuori, m_fuori = analogs.apply_to_profile("2026-09-21", ultima + 1, base)
finally:
    analogs.choose = vecchio_choose
ok(dentro is not base and m_dentro is not None,
   "l'ultima scadenza promossa (D+%d) riceve la forma analogica" % ultima)
ok(fuori is base and m_fuori is None,
   "la prima NON promossa (D+%d) resta quella del motore" % (ultima + 1))
ok(ultima == 5,
   "e l'ultima promossa oggi e' D+5, entrata il 2026-09-17 passando i sette"
   " criteri che il codice pretende dalle altre - non perche' il limite sia"
   " stato allargato: e' stato stretto, da 25 a 12 minuti")

# --------------------------------------------------------------------------
# 2. La pagina regge il profilo a dieci minuti
# --------------------------------------------------------------------------
# Tre pezzi della pagina sono stati scritti quando il profilo aveva una riga
# per ora, e cercano l'ora esatta: il grafico, la scheda del Peler e la riga
# dello scarto. Se uno dei tre non trova piu' niente, la pagina non si rompe -
# smette solo di dire quello che diceva, che e' peggio.
GG = []
for lead in range(5):
    GG.append({
        "day": "2026-09-%02d" % (14 + lead), "lead": lead,
        "sessions": {
            "Torbole-Ora": {"prob": .86, "speed": 18.0, "lo": 16.0, "hi": 20.0,
                            "grade": "BUONO", "source": "appreso",
                            "peak_hour": 16.2, "mae": 1.8, "validata": True,
                            "band_source": "residui", "n_models": 8,
                            "weights": "verificato",
                            "affidabilita": {"livello": 2, "etichetta": "buona",
                                             "motivo": "x", "uso": "y",
                                             "componenti": {"timing_min": 83.0}},
                            "window": {"from": 14, "to": 18, "gust": 25.0}},
            "Torbole-Peler": {"prob": .55, "speed": 12.0, "lo": 10.0, "hi": 14.0,
                              "grade": "BUONO", "source": "appreso",
                              "peak_hour": 8.0, "mae": 1.8, "validata": True,
                              "band_source": "residui", "n_models": 8,
                              "weights": "verificato",
                              "affidabilita": {"livello": 1, "etichetta": "tendenza",
                                               "motivo": "x", "uso": "y",
                                               "componenti": {"timing_min": 90.0}},
                              "window": {"from": 6, "to": 10, "gust": 17.0}},
        },
        "places": {
            "Torbole": {"profile": forma,          # <- quello a dieci minuti
                        "live": {"wind": 14.0, "gust": 20.0, "dir": 200.0,
                                 "ts": "2026-09-14T11:40:00Z", "age_min": 6.0,
                                 "stale": False}},
            "Malcesine": {"profile": profilo_orario(13.0),
                          "live": {"wind": 8.0, "gust": 12.0, "dir": 30.0,
                                   "ts": "2026-09-14T11:40:00Z", "age_min": 8.0,
                                   "stale": False}},
        },
    })

engine.by_day = lambda product=None: [dict(g) for g in GG]
H = web.page_home()
ok(len(H) > 40000, "la pagina si costruisce (%d byte)" % len(H))

# Il grafico deve avere i 103 vertici, non diciassette.
# Le curve sono percorsi cubici: i vertici sono i punti di arrivo dei
# segmenti C (piu' la M iniziale), che per costruzione sono i dati.
poli = re.findall(r'<path d="([^"]+)" fill="none" stroke="var\(--pc\)"', H)
vertici = [len([1 for pezzo in d.replace("M", " ").split("C") if pezzo.strip()])
           for d in poli]
ok(any(v >= 100 for v in vertici),
   "la curva disegnata ha tutti i punti dei dieci minuti (%s)" % vertici[:4])

# I due riquadri continuano a trovare le loro finestre e le loro soglie. Non
# c'e' piu' una scheda del Peler diversa da quella dell'Ora: e' lo stesso
# riquadro chiamato due volte, ed e' il motivo per cui possono avere la
# stessa dimensione.
ok(H.count('class="rq ') == 2 * len(GG),
   "due riquadri per giornata, uno per regime (%d su %d giornate)"
   % (H.count('class="rq '), len(GG)))
ok("finestra" in H and "affidabilit" in H,
   "i riquadri sopravvivono al profilo fine")
fin = re.search(r"<dd>(\d\d):(\d\d) ?\u2013", H)
ok(fin is not None and int(fin.group(1)) >= 6,
   "e la prima finestra utile resta un'ora vera, non 04:00 (%s)"
   % (fin.group(0)[-5:] if fin else "assente"))

# La riga dello scarto cerca l'ora ESATTA del campione osservato: con la
# griglia a dieci minuti le ore intere ci sono ancora, e questo lo verifica -
# se un domani la griglia cambiasse passo, la riga smetterebbe di comparire in
# silenzio e questo controllo diventerebbe rosso.
oss = {"raffica_fonte": "ricorrente 30'", "ultima_ora": 12,
       "righe": [{"hour": 11, "wind": 9.0, "gust": 13.0},
                 {"hour": 12, "wind": 11.0, "gust": 15.0}]}
sc = web.scarto_line(forma, oss)
ok(sc is not None and sc["hour"] == 12,
   "la riga dello scarto trova ancora l'ora intera nel profilo fine (%s)"
   % (sc if sc is None else sc["hour"]))
ok(sc is not None and sc["previsto"] is not None,
   "e ha un valore previsto con cui confrontare il misurato")

ore_intere = [r["hour"] for r in forma if abs(r["hour"] - round(r["hour"])) < 1e-9]
ok(len(ore_intere) == 18,
   "le diciotto ore intere sono tutte sulla griglia: e' cio' che tiene in"
   " piedi la riga dello scarto (%d)" % len(ore_intere))

# --------------------------------------------------------------------------
# 3. Le scritte che contengono un'ora devono sapere che l'ora ha i minuti
# --------------------------------------------------------------------------
# Tre posti nella pagina stampavano l'ora con "%02d:00", cioe' troncando: con
# la griglia fine dicevano 13:00 sei volte di fila, ognuna con numeri diversi,
# e il tooltip arrivava a scrivere "13.166666666666666:00". Nessuno di questi
# rompe la pagina - e' peggio, la pagina resta in piedi e dice il falso.
tabelle = re.findall(r'<details class="tbl">.*?</details>', H, re.S)
# Una pagina, una localita': una tabella per giornata, non due. Prima la
# pagina teneva dentro tutte le localita' e i conteggi si moltiplicavano.
ok(len(tabelle) == len(GG),
   "una tabella per giornata, su una pagina di una localita' (%d)"
   % len(tabelle))
orari_tab = [t for t, _v in
             re.findall(r"<tr><td>(\d\d:\d\d)</td><td class='num'>([\d.]+)</td>",
                        "".join(tabelle))]
ok(any(t.endswith((":10", ":20", ":40", ":50")) for t in orari_tab),
   "la tabella dei numeri stampa i minuti veri, non tutto :00")
doppi = []
for t in tabelle:
    orari = re.findall(r"<tr><td>(\d\d:\d\d)</td>", t)
    doppi += [o for o in set(orari) if orari.count(o) > 1]
ok(not doppi,
   "e DENTRO una tabella nessun orario si ripete: con il troncamento le"
   " righe dei dieci minuti dicevano sei volte la stessa ora (%s)" % doppi[:3])
# Su una pagina sola compaiono solo i profili di QUELLA localita': il titolo
# dice il passo di ciascuno, e con la forma analogica su D+1..D+5 e il
# profilo orario oltre, la pagina di Torbole porta entrambe le diciture.
ok("i numeri, passo per passo" in H,
   "il titolo della tabella dice quale passo ha il profilo che mostra")

# Il tooltip: l'ora si ricava dai minuti, non si concatena a ':00'.
ok("Math.round(best.h*60)" in H and "best.h+':00'" not in H,
   "il tooltip formatta l'ora dai minuti: con l'ora frazionaria la"
   " concatenazione scriveva 13.1666...:00")

# La legenda spiega la fetta chiara solo dove la fetta esiste.
# Dalla testa del grafico (titolo e legenda) alla tabella dei numeri.
grafici = re.findall(r'<div class="gtesta">.*?</details>', H, re.S)
# L'opacita' del velo si legge da web.VELO_UTILE e non si riscrive qui: era
# scritta a mano come ".045" e quando il velo e' stato schiarito (si perdeva al
# sole) questo controllo ha iniziato a contare zero fette senza che nulla fosse
# rotto.
_velo = 'opacity="%.3f"' % web.VELO_UTILE
con_fetta = sum(1 for g in grafici if _velo in g)
con_voce = sum(1 for g in grafici if "finestra utile</span>" in g)
ok(con_fetta > 0 and con_voce == con_fetta,
   "la voce di legenda c'e' in ogni grafico che disegna la fetta utile, e"
   " solo la' (%d con fetta, %d con voce)" % (con_fetta, con_voce))

# L'etichetta dentro la banda si accorcia invece di sbordare: la fetta del
# Peler a Torbole e' larga ~80 punti su 440, e la scritta intera ne vuole 82.
ok("utile da 07:10" in H or "utile 07:10" in H,
   "la fetta utile del Peler porta scritto il suo inizio")
lunghe = re.findall(r">utile (\d\d:\d\d)\u2013(\d\d:\d\d)<", H)
ok(all(a < b for a, b in lunghe),
   "e dove c'e' spazio per l'intervallo, l'intervallo e' in ordine (%s)"
   % lunghe[:2])
