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
import os
import re
import sys

os.environ.setdefault("GARDAWIND_HOME", "/tmp/gwdef")
os.makedirs("/tmp/gwdef", exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gardawind import analogs, config, orari, regimes, web

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
# 5. Il raccordo del livello non puo' fabbricare una giornata
# --------------------------------------------------------------------------
ok(analogs._raccordo_min() * 2 <= orari.PERSISTENZA_MIN,
   "il raccordo intero (%g') resta sotto la persistenza (%g'): un falso"
   " allarme non puo' nascere dall'aritmetica"
   % (analogs._raccordo_min() * 2, orari.PERSISTENZA_MIN))

print("%d controlli di struttura" % passati)
