"""Il voto dell'uscita e l'affidabilita' della previsione.

Stanno qui e non nella pagina perche' sono DECISIONI, non impaginazione. La
pagina traduce; questo modulo decide. E' la stessa separazione per cui la
persistenza vive in orari.py e non in tre grafici: una sola definizione, e chi
la cambia sa di cambiarla per tutti.

Due numeri, due domande diverse:

    voto()          quanto vale la sessione, SE la previsione e' giusta
    affidabilita()  quanto ci si puo' fidare che lo sia

Tenerle separate e' la cosa piu' importante di questo file. Una giornata puo'
essere fantastica e incerta - venti nodi a cinque giorni - oppure mediocre e
sicura: dodici nodi domani. Un unico punteggio che le mescolasse renderebbe le
due impossibili da distinguere, e sono esattamente le due informazioni su cui
si decide se caricare la macchina.
"""

# --------------------------------------------------------------------------
# Il voto: intensita' e durata
# --------------------------------------------------------------------------
# Due ingredienti, e sono quelli che Gian ha chiesto: quanti nodi e per quanto
# tempo. La rafficosita' non entra, ed e' una scelta dichiarata: il rapporto
# raffica/media previsto dai modelli non e' ancora validato su questo lago -
# per Torbole un modello di raffica addestrato non esiste, la centralina
# storica espone solo la media - e un ingrediente non validato che sposta un
# voto e' un voto che non sappiamo difendere. Quando la raffica ricorrente a
# 30' passera' la sua porta, questo e' il posto dove entra.
#
# Le soglie NON sono numeri liberi: vengono da quelle dello spot.
#
#   min_kn      "il regime e' entrato": sotto, non e' vento, e' aria che si
#               muove. E' anche la soglia su cui la durata si misura.
#   planing_kn  "si plana": sopra, il wing porta.
#
# E la durata si misura in mezz'ore di navigazione, non in minuti:
#
#   PERSISTENZA (30')  il minimo per dire che c'e' stata una sessione. Sotto
#                      questa, la giornata non e' navigabile per definizione,
#                      e la definizione e' quella di orari.py.
#   UN'ORA             una sessione corta ma vera.
#   DUE ORE E MEZZA    una giornata piena: e' la mediana dei minuti sopra
#                      soglia delle giornate navigabili misurate nella
#                      finestra dell'Ora (260 minuti), tagliata al ribasso.
MINUTI_SESSIONE = 60.0
MINUTI_GIORNATA = 150.0
# Quanto sopra la planata perche' non sia soltanto "si plana" ma "si plana
# comodi, con la vela che tiene": il margine fra le due soglie dello spot,
# aggiunto alla planata. A Torbole sono 3 kn (14 - 11), quindi 17.
def _soglia_pieno(spot):
    return spot["planing_kn"] + max(1.5, spot["planing_kn"] - spot["min_kn"])


VOTI = ("pessimo", "mediocre", "buono", "fantastico")
# La classe CSS non e' una quinta parola: e' la stessa scala, e sta qui perche'
# la pagina non deve reinventare la corrispondenza.
CLASSE = {"pessimo": "no", "mediocre": "meh", "buono": "go", "fantastico": "big"}


def voto(kn, minuti, spot):
    """Il voto della sessione: una parola fra VOTI, e la sua classe.

    `kn`     il vento previsto nella finestra utile (il massimo delle medie
             orarie: la grandezza su cui il modello e' addestrato).
    `minuti` i minuti sopra min_kn dentro quella stessa finestra, oppure None
             se la mezz'ora sostenuta non c'e'. None e' un'informazione, non
             un dato mancante: vuol dire "non navigabile".
    """
    if kn is None:
        return None, None
    if not minuti or kn < spot["min_kn"]:
        return "pessimo", CLASSE["pessimo"]
    if kn < spot["planing_kn"] or minuti < MINUTI_SESSIONE:
        return "mediocre", CLASSE["mediocre"]
    if kn >= _soglia_pieno(spot) and minuti >= MINUTI_GIORNATA:
        return "fantastico", CLASSE["fantastico"]
    return "buono", CLASSE["buono"]


# --------------------------------------------------------------------------
# L'affidabilita': la probabilita' che il VERDETTO sia giusto
# --------------------------------------------------------------------------
# Gian l'ha chiesta come percentuale e ha detto "lo so che è impossibile".
# Non e' impossibile: e' impossibile la percentuale che si intende di solito -
# "quanto e' giusta la previsione", che non e' nemmeno una domanda ben posta,
# perche' una previsione di quindici nodi non e' giusta o sbagliata, e'
# sbagliata di qualche nodo. La domanda ben posta e' un'altra, ed e' quella su
# cui si decide:
#
#     qual e' la probabilita' che il verdetto "si naviga / non si naviga" sia
#     quello giusto?
#
# Questa ha una risposta esatta, e non serve un modello nuovo per darla.
# Il modello del regime emette gia' una probabilita' p che la sessione sia
# navigabile, ed e' addestrata e verificata (il suo Brier contro il Brier
# climatologico e' misurato per ogni scadenza). Se quella p e' calibrata -
# cioe' se quando dice 0,7 succede davvero 7 volte su 10 - allora il verdetto
# che ne segue e' giusto con probabilita':
#
#     max(p, 1 - p)
#
# Ed e' esatto, non una stima: se p = 0,9 diciamo "si naviga" e sbagliamo una
# volta su dieci; se p = 0,1 diciamo "non si naviga" e sbagliamo una volta su
# dieci. Un giorno incerto - p = 0,5 - da' il 50%, che e' la verita': su quella
# giornata non sappiamo niente, e la pagina lo dice.
#
# Poi la calibrazione non e' perfetta, e di quanto non lo sia e' MISURATO:
# `calibration_error` e' lo scarto medio fra probabilita' dichiarata e
# frequenza osservata alla verifica. Si sottrae. E' una correzione sempre
# verso il basso, cioe' nella direzione che non promette piu' di quanto si sa.
#
# Quando a una scadenza non c'e' verifica - poche giornate, o nessuna - non si
# scrive un numero: si dice che non e' misurata. Una percentuale senza misura
# dietro sarebbe esattamente il numero inventato che non vogliamo, e sarebbe
# anche la piu' pericolosa delle scritte, perche' e' quella che chi legge usa
# per decidere quanto fidarsi di tutto il resto.
MINIMO = 50.0          # sotto, non e' un verdetto: e' una monetina


def affidabilita(prob, valutazione, fonte=None):
    """Percentuale che il verdetto sia giusto, o None se non e' misurabile.

    `prob`        la probabilita' del regime emessa dal modello (0..1).
    `valutazione` la voce di confidence.assess() per quello spot e quella
                  scadenza: serve per sapere SE c'e' verifica e quanto vale
                  la calibrazione.
    """
    # `fonte` e' la provenienza della probabilita' (`source_prob`), e senza
    # questo controllo la scheda scriveva una percentuale di affidabilita'
    # "addestrata e verificata" anche quando la probabilita' NON veniva da un
    # modello: dove lo stadio non supera la porta, predict usa il tasso
    # climatologico, uguale per tutti i giorni della fascia. Succedeva alle
    # scadenze lunghe - il caso che il README stesso dichiara, "a sette giorni
    # la probabilita' vale zero" - e usciva una percentuale costante descritta
    # come misurata. E' la scritta piu' pericolosa della pagina, perche' e'
    # quella che chi legge usa per decidere quanto fidarsi di tutto il resto.
    if fonte is not None and fonte != "appreso":
        return None
    if prob is None or not valutazione or not valutazione.get("misurato"):
        return None
    p = max(0.0, min(1.0, float(prob)))
    grezza = 100.0 * max(p, 1.0 - p)
    errore = (valutazione.get("componenti") or {}).get("cal_err")
    if errore is not None:
        grezza -= 100.0 * float(errore)
    return int(round(max(MINIMO, min(99.0, grezza))))


def scala_parole(spot):
    """La scala del voto spiegata, con le soglie di QUESTO spot.

    Sta qui e non nella pagina per la stessa ragione di tutto il resto di
    questo file: era una seconda copia del vocabolario. Le quattro parole
    erano scritte a mano nel testo dei dettagli, e il giorno in cui una soglia
    o una parola cambiasse, la spiegazione avrebbe continuato a raccontare la
    scala di prima - con l'aria di essere autorevole, perche' e' la
    spiegazione.
    """
    minimo, planata = spot["min_kn"], spot["planing_kn"]
    ore = MINUTI_GIORNATA / 60.0
    frasi = [
        "la mezz’ora sopra %.0f kn non c’è" % minimo,
        "c’è, ma sotto %.0f kn o meno di un’ora" % planata,
        "sopra %.0f kn per almeno un’ora" % planata,
        "sopra %.0f kn per almeno %s ore"
        % (_soglia_pieno(spot),
           ("due e mezza" if abs(ore - 2.5) < .1 else "%.1f" % ore)),
    ]
    return " ".join("<b>%s</b>: %s." % (p, f) for p, f in zip(VOTI, frasi))


def affidabilita_parole(pct, valutazione, fonte=None):
    """Come si spiega quel numero, in una riga. Sta qui accanto a chi lo fa.

    La frase dice cosa il numero E', non quanto e' alto: "78%" senza
    l'oggetto della scommessa e' il tipo di numero che ognuno interpreta a
    modo suo, e quasi tutti lo leggono come "la previsione e' giusta al 78%",
    che non e' quello che misura.
    """
    if pct is None:
        if fonte is not None and fonte != "appreso":
            return ("affidabilità non misurabile: a questa scadenza la "
                    "probabilità non viene da un modello addestrato ma dalla "
                    "frequenza climatologica del regime, che è la stessa per "
                    "tutti i giorni")
        motivo = (valutazione or {}).get("motivo") or "non ancora verificata"
        return "affidabilità non misurata a questa scadenza: %s" % motivo
    return ("probabilità che il verdetto “si naviga / non si naviga” "
            "sia quello giusto: %d%%. Viene dalla probabilità del regime, che "
            "è addestrata e verificata, meno l’errore di calibrazione "
            "misurato a questa scadenza." % pct)


__all__ = ["VOTI", "CLASSE", "voto", "affidabilita", "affidabilita_parole",
           "MINUTI_SESSIONE", "MINUTI_GIORNATA", "MINIMO"]
