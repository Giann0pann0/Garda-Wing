"""Un'idea, un posto. Il censimento delle definizioni che possono divergere.

Questo file nasce da una domanda: "a furia di modificare il codice non abbiamo
reso le cose piu' complesse di quello che sono?". La risposta misurata e' che
il problema non e' la quantita' di codice - e' che alcune idee sono scritte in
piu' di un posto, e OGNI difetto delle ultime ventiquattr'ore era una copia
che aveva preso una strada sua:

  - la porta del motore analogico misurava venti minuti credendone trenta,
    perche' la persistenza era riscritta li' invece di venire da orari.py;
  - la ripidezza congelata era misurata su tutta la curva e quella del codice
    dentro la finestra dell'Ora: due definizioni della stessa parola, e la
    porta non poteva aprire;
  - la sagoma del test non era riportata a picco 1 e quella del prodotto si':
    due programmi diversi che si credevano lo stesso.

Nessuno di questi era un bug di logica. Erano tutti la stessa cosa: un
concetto con due residenze. Quindi qui non si prova un comportamento, si
prova la STRUTTURA - dove vive ogni numero che decide, e quali relazioni fra
i luoghi devono restare vere. Quando una relazione si rompe, questo file lo
dice prima che lo dica un utente guardando una curva sbagliata.

Un numero scritto due volte prima o poi diventa due numeri.
"""
import inspect
import os
import re
import sys

os.environ.setdefault("GARDAWIND_HOME", "/tmp/gwdef")
os.makedirs("/tmp/gwdef", exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gardawind import analogs, config, orari, regimes, util, web

RADICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gardawind")
passati = 0


def ok(cond, msg):
    global passati
    if cond:
        passati += 1
        print("PASS " + msg)
    else:
        print("FAIL " + msg)


def sorgenti():
    for nome in sorted(os.listdir(RADICE)):
        if nome.endswith(".py"):
            with open(os.path.join(RADICE, nome), encoding="utf-8") as f:
                yield nome, f.read()


def righe_di_codice(testo):
    """Le righe che il computer esegue: via i commenti e le docstring.

    Serve perche' i numeri compaiono spesso nelle spiegazioni, e una
    spiegazione che cita "trenta minuti" non e' una seconda definizione - e'
    esattamente cio' che si vuole che ci sia.
    """
    fuori = re.sub(r'"""(?:.|\n)*?"""', "", testo)
    fuori = re.sub(r"'''(?:.|\n)*?'''", "", fuori)
    out = []
    for riga in fuori.splitlines():
        taglio = riga.split("#", 1)[0]
        if taglio.strip():
            out.append(taglio)
    return out


# --------------------------------------------------------------------------
# 1. La persistenza: una sola, in orari.py
# --------------------------------------------------------------------------
ok(orari.PERSISTENZA_MIN == 30.0,
   "la persistenza vive in orari.py e vale %g minuti" % orari.PERSISTENZA_MIN)
ok(web.PERSISTENZA_CARD_MIN is orari.PERSISTENZA_MIN
   or web.PERSISTENZA_CARD_MIN == orari.PERSISTENZA_MIN,
   "la scheda usa quella, non una copia")
ok(analogs._persistenza_min() == orari.PERSISTENZA_MIN,
   "e anche la porta del motore analogico")

copie = []
for nome, testo in sorgenti():
    if nome == "orari.py":
        continue
    for riga in righe_di_codice(testo):
        if re.search(r"(persist\w*\s*=\s*30|PERSISTENZA\w*\s*=\s*30)", riga):
            copie.append((nome, riga.strip()))
ok(not copie,
   "e nessun modulo riscrive il numero 30 come persistenza (%s)" % copie[:2])

# --------------------------------------------------------------------------
# 2. Le finestre: quella del prodotto decide, le altre le devono contenere
# --------------------------------------------------------------------------
# Non devono essere LA STESSA finestra: classificare un regime osservato e
# prevedere una sessione sono due mestieri. Ma la finestra con cui si
# classifica deve contenere quella con cui si prevede, altrimenti una
# giornata prevista come Ora non verrebbe riconosciuta come Ora quando
# arriva, e la verifica misurerebbe un regime contro un altro.
for nome, chiave in (("Torbole-Ora", regimes.ORE_ORA),
                     ("Malcesine-Ora", regimes.ORE_ORA),
                     ("Torbole-Peler", regimes.ORE_PELER),
                     ("Malcesine-Peler", regimes.ORE_PELER)):
    h0, h1 = config.SPOTS[nome]["window"]
    ok(chiave[0] <= h0 and h1 <= chiave[1],
       "la finestra di classificazione %s contiene quella di previsione di %s"
       " (%s)" % (chiave, nome, (h0, h1)))

# La finestra della porta e' congelata col benchmark: se la configurazione
# cambia, i numeri congelati non parlano piu' di quella finestra e vanno
# rimisurati. Questo controllo e' l'allarme, non l'accoppiamento.
h0, h1 = config.SPOTS["Torbole-Ora"]["window"]
ok(analogs.FINESTRA_ORA == (h0 * 60, (h1 + 1) * 60),
   "la finestra della porta (%s) e' ancora quella configurata per l'Ora a"
   " Torbole: se cambi config, il benchmark va rimisurato"
   % (analogs.FINESTRA_ORA,))

# --------------------------------------------------------------------------
# 3. Le soglie: tre numeri con tre mestieri, e un ordine da rispettare
# --------------------------------------------------------------------------
# min_kn e' "c'e' vento", planing_kn e' "si plana", e la soglia della porta e'
# quella con cui la forma e' stata validata. Sono legittimamente diverse: il
# giorno che si cambia la planabilita' non si deve invalidare un benchmark. Ma
# la soglia della porta deve stare DENTRO la banda del prodotto, altrimenti la
# porta sta misurando una giornata che al prodotto non interessa.
ora = config.SPOTS["Torbole-Ora"]
ok(ora["min_kn"] <= analogs.SOGLIA_PORTA <= ora["planing_kn"],
   "la soglia della porta (%.0f) sta fra 'c'e' vento' (%.0f) e 'si plana'"
   " (%.0f)" % (analogs.SOGLIA_PORTA, ora["min_kn"], ora["planing_kn"]))
peler = config.SPOTS["Torbole-Peler"]
ok(analogs.SOGLIA_PELER == peler["min_kn"],
   "e la soglia della mattina e' quella configurata per il Peler (%.0f)"
   % analogs.SOGLIA_PELER)

# --------------------------------------------------------------------------
# 4. Il passo della griglia: uno, e dichiarato
# --------------------------------------------------------------------------
passo = analogs.GRID_MIN[1] - analogs.GRID_MIN[0]
ok(passo == analogs.PASSO_MIN,
   "il passo della griglia (%d') e' quello che le metriche credono di contare"
   " (%d')" % (passo, analogs.PASSO_MIN))
ok(analogs._punti_persistenza() == int(orari.PERSISTENZA_MIN / passo) + 1,
   "e i campioni della persistenza si contano dagli intervalli, non dai punti")

# --------------------------------------------------------------------------
# 5. Le scadenze promosse: una tupla, non otto copie
# --------------------------------------------------------------------------
# Erano scritte a mano in otto posti - choose, apply_to_profile, tre volte in
# validation_report, la promozione, il motore e il comando. Aggiungere una
# scadenza voleva dire trovarle tutte, e dimenticarne una avrebbe prodotto la
# peggiore delle incoerenze: un giorno con la forma nuova che la porta non
# misura, o misurato e non mostrato.
ok(isinstance(analogs.LEADS, tuple) and analogs.LEADS == (1, 2, 3, 4, 5),
   "le scadenze promosse sono una tupla dichiarata: %s" % (analogs.LEADS,))
copie_leads = []
for nome, testo in sorgenti():
    for riga in righe_di_codice(testo):
        if re.search(r"\(\s*1\s*,\s*2\s*,\s*3\s*(,\s*4\s*(,\s*5\s*)?)?\)",
                     riga) \
                and "LEADS" not in riga and "VERIFY_LEADS" not in riga:
            copie_leads.append((nome, riga.strip()[:70]))
ok(not copie_leads,
   "e nessun modulo le riscrive a mano (%s)" % copie_leads[:2])
ok(1 in analogs.LEADS and 0 not in analogs.LEADS,
   "D+0 non c'e': oggi la forma non si tocca, il nowcast e' strada chiusa")
ok(max(analogs.LEADS) in analogs.BENCHMARK,
   "e ogni scadenza promossa ha i suoi numeri congelati nel benchmark: la"
   " piu' lontana e' D+%d" % max(analogs.LEADS))
ok(set(analogs.BENCHMARK) == set(analogs.LEADS),
   "ne' piu' ne' meno - un benchmark senza scadenza sarebbe un numero morto,"
   " una scadenza senza benchmark sarebbe una forma non misurata")

# Ogni banda deve avere un numero misurato sotto: una tolleranza su una
# grandezza che nessuno misura e' un cancello che non si apre mai, e il
# messaggio dice "atteso None".
senza_misura = [(lead, chiave) for chiave in analogs.TOLLERANZA_BENCHMARK
                for lead in analogs.BENCHMARK
                if chiave not in analogs.BENCHMARK[lead]]
ok(not senza_misura,
   "ogni banda dichiarata ha il suo numero misurato (%s)" % senza_misura[:2])

# --------------------------------------------------------------------------
# 5-bis. La scalatura della sagoma e' UN percorso, e la porta passa da la'
# --------------------------------------------------------------------------
# E' il difetto piu' costoso di questa settimana, tre volte: la persistenza,
# la ripidezza e la normalizzazione avevano ciascuna due implementazioni che
# si credevano uguali. Qui il rischio e' il peggiore di tutti, perche' e' la
# porta a misurare: se il prodotto scalasse la sagoma in un modo e la porta in
# un altro, la porta darebbe il permesso a una configurazione che non si
# spedisce. Il modo di esserne certi non e' rileggere il codice: e' che sia lo
# stesso codice.
for funzione in ("apply_to_profile", "validation_report"):
    ok("scala_sagoma(" in inspect.getsource(getattr(analogs, funzione)),
       "%s porta la sagoma al livello chiamando scala_sagoma, non un calcolo"
       " che le assomiglia" % funzione)
# E l'ancora vive dentro scala_sagoma, in un posto solo. apply_to_profile non
# chiama livello_orario e non deve: il profilo del motore ha un punto per ora,
# quindi il suo massimo nella finestra E' GIA' il massimo delle medie orarie.
# Chiamarla la' sarebbe una seconda definizione della stessa cosa.
ok("livello_orario(" in inspect.getsource(analogs.scala_sagoma),
   "l'ancora - il massimo delle medie orarie - si calcola dentro"
   " scala_sagoma, e da nessun'altra parte")
fuori = [n for n, t in sorgenti()
         if "def livello_orario" not in t and "medie_orarie" in t]
ok(not fuori, "e nessun modulo se la riscrive (%s)" % fuori[:2])

# --------------------------------------------------------------------------
# 5-ter. Il voto e l'affidabilita' vivono FUORI dalla pagina
# --------------------------------------------------------------------------
# La pagina traduce, non decide: e' la stessa separazione per cui la
# persistenza vive in orari.py e non in tre grafici. Se le parole del voto
# fossero scritte in web.py, la prossima pagina - o un'app, o una notifica -
# ne avrebbe una seconda copia, e il giorno in cui una soglia cambia le due
# direbbero due cose diverse sulla stessa giornata.
from gardawind import giudizio

testo_web = dict(sorgenti())["web.py"]
# Si guardano le righe di CODICE, non i commenti: la parola "mediocre" dentro
# un commento che spiega perche' oggi il misurato prevale sulla previsione e'
# prosa, non una seconda definizione.
codice_web = "\n".join(righe_di_codice(testo_web))
copie = [p for p in giudizio.VOTI if '"%s"' % p in codice_web
         or "'%s'" % p in codice_web]
ok(not copie, "le parole del voto non sono riscritte nella pagina (%s)" % copie)
ok("giudizio.voto(" in testo_web and "giudizio.affidabilita(" in testo_web,
   "la pagina chiama giudizio per il voto e per l'affidabilita'")

# E le soglie del voto vengono dallo spot, non da numeri liberi: 11 e 14 kn
# sono min_kn e planing_kn di Torbole, e un voto che li riscrivesse a mano
# smetterebbe di seguire la configurazione di uno spot nuovo.
testo_giudizio = dict(sorgenti())["giudizio.py"]
numeri = re.findall(r"spot\[\"(min_kn|planing_kn)\"\]", testo_giudizio)
ok("min_kn" in numeri and "planing_kn" in numeri,
   "il voto legge le soglie dallo spot")
soglie_a_mano = re.findall(r"(?<![\w.])(1[0-9]|2[0-9])\.0(?!\d)",
                           testo_giudizio)
ok(not soglie_a_mano,
   "e non ci sono soglie in nodi scritte a mano in giudizio.py (%s)"
   % soglie_a_mano[:3])

# --------------------------------------------------------------------------
# 5-quater. Una pagina per localita', e la lista e' una sola
# --------------------------------------------------------------------------
# Aggiungere una localita' deve essere una riga in config.PLACES. Quindi la
# pagina e l'esportazione non possono scrivere a mano "Torbole" o
# "Malcesine": pagina, navigazione, rotte e nomi dei file vengono tutti da
# quella lista, altrimenti una localita' nuova comparirebbe in un posto e
# mancherebbe nell'altro - una voce di menu senza pagina dietro.
#
# engine.py e nowcast.py sono ESCLUSI, e non per comodita': la' il nome di
# Torbole non decide cosa mostrare, dice che la forma analogica e' validata su
# QUELLA centralina (la libreria e' costruita sul T0193, e il suo archivio non
# esiste per altri posti). E' un fatto del modello, e vive accanto al modello.
nomi_a_mano = []
for nome, testo in sorgenti():
    if nome not in ("web.py", "export.py"):
        continue
    for riga in righe_di_codice(testo):
        if re.search(r'["\'](Torbole|Malcesine)["\']', riga) \
                and "SPOTS[" not in riga and "PLACES" not in riga:
            nomi_a_mano.append((nome, riga.strip()[:60]))
ok(not nomi_a_mano,
   "pagina ed esportazione non scrivono a mano il nome di una localita' (%s)"
   % nomi_a_mano[:2])

# --------------------------------------------------------------------------
# 6. Il raccordo del livello non puo' fabbricare una giornata
# --------------------------------------------------------------------------
ok(analogs._raccordo_min() * 2 <= orari.PERSISTENZA_MIN,
   "il raccordo intero (%g') resta sotto la persistenza (%g'): un falso"
   " allarme non puo' nascere dall'aritmetica"
   % (analogs._raccordo_min() * 2, orari.PERSISTENZA_MIN))

# --------------------------------------------------------------------------
# 7. Quando una serie e' una curva: una regola, non due costanti
# --------------------------------------------------------------------------
# Il numero 12 stava in due posti - engine.campioni_fini e il grafico in
# web.py - e la conseguenza si e' vista in pagina: una centralina oraria non
# arrivava mai a dodici campioni prima delle sedici, quindi il processo veloce
# non pubblicava la sua curva mentre la pagina la disegnava dalle medie orarie.
# La curva c'era e non si aggiornava, a Campione e a Malcesine.
soglie_a_mano = []
for nome, testo in sorgenti():
    for riga in righe_di_codice(testo):
        if re.search(r'len\(\s*(oss_)?fini\s*\)\s*[<>]=?\s*\d', riga) \
                or re.search(r'len\(\s*minuti\s*\)\s*<\s*\d\d', riga):
            soglie_a_mano.append((nome, riga.strip()[:70]))
ok(not soglie_a_mano,
   "nessuno decide da se' se una serie e' disegnabile: si chiede a"
   " util.serie_disegnabile (%s)" % soglie_a_mano[:2])
ok(util.CURVA_MIN_ARCO_MIN >= 10 * 11,
   "e la soglia e' un ARCO (%g minuti), che per una centralina da dieci minuti"
   " vale quanto i dodici campioni di prima" % util.CURVA_MIN_ARCO_MIN)

print("%d controlli di struttura" % passati)
