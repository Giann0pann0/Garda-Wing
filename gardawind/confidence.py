"""Quanto ci si puo' fidare di QUESTA previsione, per questo spot e questo giorno.

Due cose separate, e la separazione e' il punto di tutto il modulo:

  scadenza      quanto e' lontano il giorno. E' un fatto di calendario e non
                dice niente sulla qualita': "tra tre giorni" e' la stessa
                distanza per il Pelèr di Torbole e per l'Ora di Malcesine.
  affidabilita' quanto quella previsione, a quella scadenza, su quello spot,
                ha dimostrato di valere. E' una misura, e cambia da spot a
                spot anche a parita' di scadenza.

Legare le due cose - "tre giorni quindi tendenza" - sarebbe comodo e falso.
Se il Pelèr di Torbole a D+2 batte i riferimenti con un intervallo che non
attraversa lo zero, merita di essere presentato come affidabile; se l'Ora di
Malcesine a D+2 non li batte, non lo merita, e prometterlo perche' "e' lo
stesso orizzonte" e' esattamente il tipo di promessa che questo progetto sta
cercando di non fare.

Come si decide
--------------
Una scala a scendere, non una somma pesata. Si parte dal livello piu' alto e
si scende al primo requisito che manca, annotando QUALE manca. Una somma
pesata darebbe un numero unico in cui un timing disastroso si compensa con una
bella calibrazione, e chi legge non saprebbe mai di cosa fidarsi.

I requisiti guardano:

  1. quanti giorni di prova ci sono a QUELLA scadenza;
  2. quanto si batte il riferimento banale, e se il guadagno regge al bootstrap;
  3. quanto e' calibrata la probabilita';
  4. quanto vale l'errore di intensita', misurato in unita' di decisione;
  5. quanto sono d'accordo i modelli oggi;
  6. se la direzione prevista e' dentro il settore del regime o sul bordo.

L'ORARIO NON ENTRA NELL'ETICHETTA, e la prima versione di questo modulo
sbagliava a farcelo entrare. La verifica sui dati veri dice che l'errore
sull'ora del picco sta fra i settanta e i novanta minuti su tutti gli spot e
tutte le scadenze, e che il modello dell'orario non batte la semplice media
stagionale. Con l'orario dentro la scala, ogni riga sarebbe scesa a "tendenza"
per un motivo che non riguarda cio' che la scheda promette: l'etichetta
risponde a "entra?" e "quanto forte?", che sono le due domande misurate e
promosse. L'orario e' una terza domanda, a cui oggi si risponde male, e
merita una riga propria che lo dica - non di trascinare in basso un giudizio
su altro. Resta fra le componenti, resta nella nota tecnica, e la scheda lo
dichiara sempre separatamente.

Sulle soglie, per onesta'. I punti 1-5 confrontano numeri misurati con soglie
EDITORIALI: dove tagliare fra "alta" e "buona" e' una scelta di prodotto, non
una stima. Le soglie sono pero' ancorate a qualcosa di reale invece che
inventate: il guadagno e' relativo al riferimento banale, e l'errore di
intensita' e' rapportato alla differenza fra soglia di regime e soglia di
planata, cioe' al margine che davvero cambia la decisione di andare o non
andare. I numeri grezzi restano comunque visibili nella diagnostica, sempre,
cosi' chi vuole giudicare da se' puo' farlo.
"""

from . import config
from .util import clamp

ALTA = 3
BUONA = 2
TENDENZA = 1
OUTLOOK = 0

ETICHETTE = {
    ALTA: "alta affidabilità",
    BUONA: "buona affidabilità",
    TENDENZA: "tendenza",
    OUTLOOK: "outlook",
}

# Frase breve che dice a cosa serve quel livello, non quanto e' bravo il
# modello: e' la domanda che si fa chi deve decidere se mettere il materiale
# in macchina.
# Parlano di SE il vento entra e di QUANTO forte: sono le due domande misurate.
# Sull'ora si pronuncia una riga a parte, perche' li' il modello e' debole e
# fingere il contrario in questa frase sarebbe la scorciatoia piu' facile.
USO = {
    ALTA: "l'intensità e la probabilità reggono; l'orario si legge a parte",
    BUONA: "l'indicazione tiene, i dettagli possono spostarsi",
    TENDENZA: "utile per capire dove sta andando, non per decidere",
    OUTLOOK: "solo un'idea di massima, da riguardare avvicinandosi",
}


# --- la seconda voce: l'orario, con una scala propria ---------------------
# Non un'appendice della prima. Una scheda che dice "alta affidabilita'" e
# basta fa credere che sia affidabile anche l'ora; una che scende a "tendenza"
# per colpa dell'ora sottovaluta cio' che invece e' solido. Due voci separate
# tolgono entrambi gli equivoci, e ognuna risponde della propria domanda.
TIMING_ETICHETTE = {3: "buona precisione", 2: "precisione media",
                    1: "bassa precisione", 0: "non misurato"}
TIMING_SOGLIE = {3: 30.0, 2: 60.0}      # minuti di errore sull'ora del picco
ORARIO_FINE_MIN = TIMING_SOGLIE[2]      # sotto questa soglia si scrivono i minuti


def timing_voice(metrics_lead):
    """Voce indipendente sull'orario: livello, etichetta, minuti misurati."""
    t = ((metrics_lead or {}).get("timing") or {}).get("mae_min")
    if t is None:
        return {"livello": 0, "etichetta": TIMING_ETICHETTE[0], "minuti": None,
                "testo": "Timing: non misurato a questa scadenza",
                "fine": False}
    liv = 3 if t <= TIMING_SOGLIE[3] else 2 if t <= TIMING_SOGLIE[2] else 1
    return {"livello": liv, "etichetta": TIMING_ETICHETTE[liv], "minuti": t,
            "testo": "Timing: %s, ±%d min" % (TIMING_ETICHETTE[liv], round(t)),
            "fine": t <= ORARIO_FINE_MIN}


def orario_affidabile(metrics_lead):
    """Si possono scrivere i minuti? Dipende SOLO dall'errore sull'orario."""
    return timing_voice(metrics_lead)["fine"]


def nota_orario(metrics_lead):
    return timing_voice(metrics_lead)["testo"]

# --- soglie editoriali, dichiarate ---------------------------------------
MIN_GIORNI = {ALTA: 120, BUONA: 60, TENDENZA: 30}
MIN_SKILL = {ALTA: 0.25, BUONA: 0.10}          # guadagno relativo sul riferimento
MAX_CAL_ERR = {ALTA: 0.06, BUONA: 0.10}        # scarto medio dichiarato/osservato
MAX_SPREAD_KN = {ALTA: 4.0, BUONA: 6.5}        # disaccordo fra i modelli, oggi
MIN_DIR_PENALTY = {ALTA: 0.90, BUONA: 0.60}    # direzione dentro il settore



def lead_label(lead):
    """La scadenza in italiano, senza sigle."""
    if lead <= 0:
        return "Oggi"
    if lead == 1:
        return "Domani"
    if lead == 2:
        return "Dopodomani"
    return "Tra %d giorni" % lead


def _skill(metrics_lead):
    """Guadagno relativo su intensita' e probabilita', con la significativita'."""
    inten = (metrics_lead or {}).get("intensity") or {}
    prob = (metrics_lead or {}).get("prob") or {}
    gi = (metrics_lead or {}).get("gain_int") or {}
    gp = (metrics_lead or {}).get("gain_prob") or {}

    base = None
    for key in ("mae_raw", "mae_clim"):
        v = inten.get(key)
        if v:
            base = v if base is None else min(base, v)
    skill_int = None
    if base and inten.get("mae") is not None:
        skill_int = 1.0 - inten["mae"] / base
    skill_prob = None
    if prob.get("brier") is not None and prob.get("brier_base"):
        skill_prob = 1.0 - prob["brier"] / prob["brier_base"]
    return {
        "skill_int": skill_int, "skill_prob": skill_prob,
        "sig_int": bool(gi.get("significativo")),
        "sig_prob": bool(gp.get("significativo")),
        "mae": inten.get("mae"),
        "cal_err": prob.get("calibration_error"),
        "timing_min": ((metrics_lead or {}).get("timing") or {}).get("mae_min"),
        "n_giorni": (metrics_lead or {}).get("n_test_days") or 0,
    }


def assess(spot_name, lead, metrics_lead=None, spread_kn=None,
           dir_penalty=None, dir_offset=None, ambiguo=False):
    """Livello di affidabilita' con il motivo per cui non e' piu' alto.

    metrics_lead : la voce per-scadenza prodotta da validate.fit_band, oppure
                   None se a questa scadenza non e' stato misurato nulla.
    spread_kn    : dispersione fra i modelli su questa giornata.
    dir_penalty  : quanto la direzione prevista sta dentro il settore (1 = si').
    dir_offset   : scarto in gradi fra direzione prevista e asse del regime.
    ambiguo      : il regime osservabile e' di attribuzione incerta.
    """
    spot = config.SPOTS[spot_name]
    # Margine di decisione: la distanza fra "il regime e' entrato" e "si plana".
    # Un errore piu' piccolo di questo margine non cambia la scelta di andare;
    # piu' grande, la cambia. E' l'unita' giusta in cui misurare un errore di
    # intensita' quando si deve decidere se caricare la macchina.
    margine = max(1.5, spot["planing_kn"] - spot["min_kn"])

    s = _skill(metrics_lead)
    motivi = []

    if not metrics_lead or s["n_giorni"] < MIN_GIORNI[TENDENZA]:
        return {
            "livello": OUTLOOK,
            "etichetta": ETICHETTE[OUTLOOK],
            "uso": USO[OUTLOOK],
            "motivo": ("a questa scadenza non ci sono ancora misure di verifica"
                       if not metrics_lead else
                       "solo %d giornate di verifica a questa scadenza" % s["n_giorni"]),
            "misurato": False,
            "componenti": s,
            "lead": lead,
            "scadenza": lead_label(lead),
        }

    def requisiti(livello):
        """Cosa manca per essere a questo livello. Lista vuota = ci siamo."""
        mancano = []
        if s["n_giorni"] < MIN_GIORNI[livello]:
            mancano.append("solo %d giornate di verifica (ne servono %d)"
                           % (s["n_giorni"], MIN_GIORNI[livello]))
        # Almeno uno dei due stadi deve battere il proprio riferimento in modo
        # distinguibile dal rumore. Per il livello alto, entrambi.
        ok_int = s["sig_int"] and (s["skill_int"] or 0) >= MIN_SKILL[livello]
        ok_prob = s["sig_prob"] and (s["skill_prob"] or 0) >= MIN_SKILL[livello]
        if livello == ALTA and not (ok_int and ok_prob):
            quale = "sull'intensità" if not ok_int else "sulla probabilità"
            mancano.append("il guadagno %s non raggiunge il %d%% "
                           "distinguibile dal rumore" % (quale, 100 * MIN_SKILL[livello]))
        if livello == BUONA and not (ok_int or ok_prob):
            mancano.append("nessuno dei due stadi batte il riferimento banale "
                           "in modo distinguibile dal rumore")
        if s["cal_err"] is not None and s["cal_err"] > MAX_CAL_ERR[livello]:
            mancano.append("probabilità calibrata solo entro %.0f punti"
                           % (100 * s["cal_err"]))
        if s["mae"] is not None and s["mae"] > margine * (1.0 if livello == ALTA else 1.8):
            mancano.append("errore di intensità ±%.1f kn, oltre il margine che "
                           "cambia la decisione (%.1f kn)" % (s["mae"], margine))
        if spread_kn is not None and spread_kn > MAX_SPREAD_KN[livello]:
            mancano.append("i modelli non sono d'accordo (±%.1f kn fra loro)" % spread_kn)
        if dir_penalty is not None and dir_penalty < MIN_DIR_PENALTY[livello]:
            mancano.append("la direzione prevista è %s"
                           % ("fuori dal settore del regime" if dir_penalty < 0.5
                              else "sul bordo del settore del regime"))
        return mancano

    # Il motivo e' sempre "perche' non sta un gradino piu' su", non "perche' sta
    # qui": e' la domanda che si fa chi legge. Senza questo, un livello
    # intermedio arrivava all'interfaccia senza spiegazione.
    scelto, motivo = TENDENZA, None
    for livello in (ALTA, BUONA):
        mancano = requisiti(livello)
        if not mancano:
            scelto = livello
            break
        if livello == ALTA:
            motivo = mancano[0]          # perche' non e' "alta"
        else:
            scelto, motivo = TENDENZA, mancano[0]
            break

    # Retrocessioni che valgono a qualunque livello: sono condizioni di oggi,
    # non proprieta' del modello, e non possono essere compensate da una buona
    # statistica storica.
    if ambiguo and scelto > TENDENZA:
        scelto -= 1
        motivo = "il regime di oggi è di attribuzione incerta"
    if dir_penalty is not None and dir_penalty < 0.4 and scelto > TENDENZA:
        scelto = TENDENZA
        motivo = ("la direzione prevista è fuori dal settore del regime"
                  + (" (%d gradi dall'asse)" % round(dir_offset) if dir_offset else ""))

    return {
        "livello": scelto,
        "etichetta": ETICHETTE[scelto],
        "uso": USO[scelto],
        "motivo": motivo,
        "misurato": True,
        "componenti": s,
        "lead": lead,
        "scadenza": lead_label(lead),
    }


def nota_tecnica(valutazione):
    """Una riga per la diagnostica: i numeri grezzi dietro l'etichetta."""
    c = valutazione.get("componenti") or {}
    bits = ["%d giornate di verifica" % (c.get("n_giorni") or 0)]
    if c.get("skill_int") is not None:
        bits.append("guadagno intensità %+.0f%%%s"
                    % (100 * c["skill_int"], "" if c.get("sig_int") else " (non significativo)"))
    if c.get("skill_prob") is not None:
        bits.append("guadagno probabilità %+.0f%%%s"
                    % (100 * c["skill_prob"], "" if c.get("sig_prob") else " (non significativo)"))
    if c.get("mae") is not None:
        bits.append("MAE ±%.1f kn" % c["mae"])
    if c.get("cal_err") is not None:
        bits.append("errore di calibrazione %.3f" % c["cal_err"])
    if c.get("timing_min") is not None:
        bits.append("orario ±%d min" % round(c["timing_min"]))
    return " · ".join(bits)


def sintesi_giorno(valutazioni):
    """Il livello del giorno e' il PIU' BASSO fra gli spot mostrati.

    Un giorno non e' affidabile perche' uno dei due spot lo e': chi legge
    l'intestazione la legge come un giudizio sul giorno, e se poi una delle due
    righe sotto e' un azzardo l'intestazione ha mentito. Il livello per spot
    resta comunque su ciascuna riga, che e' dove serve davvero.
    """
    vals = [v for v in valutazioni if v]
    if not vals:
        return None
    return min(vals, key=lambda v: v["livello"])
