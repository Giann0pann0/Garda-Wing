"""Quanto tira ADESSO, separato dalla previsione.

Sono due cose con due tempi diversi, e finche' stavano nella stessa pagina
generata nello stesso momento avevano per forza la stessa eta': il sito si
rifaceva quattro volte al giorno, e il numero delle "condizioni attuali"
poteva essere vecchio di cinque ore mentre diceva "adesso".

Questo modulo produce un file piccolo - live.json - con il solo dato
osservato. Lo scrive un processo veloce, che legge le centraline e nient'altro:
niente modelli, niente addestramento, niente scaricamento di previsioni. La
pagina lo rilegge da sola, e l'eta' del dato la calcola il browser
dall'orario del campione, non da quando e' stata costruita la pagina. Cosi'
un dato vecchio si vede invecchiare invece di restare fermo su "adesso".

Tre cose che questo file NON fa, di proposito:

  non inventa la raffica quando la centralina non la manda;
  non allarga la finestra della raffica ricorrente per farla uscire dove la
  cadenza non la sostiene - dice "non stimabile", che e' un'altra cosa da zero;
  non scrive un'eta': scrive l'ORARIO del campione. L'eta' e' una sottrazione,
  e va fatta nel momento in cui si guarda, non nel momento in cui si scrive.
"""

import json
import os

from . import config, store
from .util import (FINESTRA_RICORRENTE_MIN, clamp, curva_monotona, iso_utc,
                   local_day, parse_dt_any, recurrent_gust, sampling_cadence,
                   utc_now, window_estimable)

# Quanto passato guardare per la raffica ricorrente. Serve piu' della finestra
# stessa: la mediana su trenta minuti ha bisogno dei campioni di quei trenta
# minuti, e con qualche minuto di margine si sopravvive a un campione perso.
FINESTRA_PASSATO_MIN = 90.0

# Lo SPAZIO NORMALIZZATO delle curve del misurato. x va da 0 a 1 fra queste
# due ore, y da 0 a 1 fra zero e questi nodi. Non sono i numeri del grafico:
# sono un sistema di riferimento neutro, e il grafico ci mappa sopra il suo.
#
# Perche' non scrivere direttamente le coordinate del disegno: il file lo
# scrive un processo che non sa quanto e' alta la scala del grafico ne' da che
# ora comincia - quelle le decide la pagina quando viene costruita, e cambiano
# da un luogo all'altro e da un giorno all'altro. Ma soprattutto: la
# matematica della curva sta in curva_monotona, in un posto solo, e li' deve
# restare. Il browser NON interpola niente - riscrive le coppie di numeri di
# un percorso gia' fatto, che e' una moltiplicazione. Se invece il browser
# dovesse costruire la curva, l'interpolazione monotona avrebbe due
# residenze, una in Python e una in JavaScript, e prima o poi disegnerebbero
# due curve diverse per gli stessi campioni.
CURVA_ORA_DA, CURVA_ORA_A = 4.0, 21.0
CURVA_KN_MAX = 60.0


def stazione(station, adesso=None):
    """Lo stato osservato di una centralina. Nessuna stima, nessun modello."""
    adesso = adesso or utc_now()
    rows = store.samples_recent(station, 40)
    if not rows:
        return {"station": station, "ts": None, "wind": None, "gust": None,
                "dir": None, "gust_rec": None, "gust_rec_stato": "no_data",
                "cadenza_min": None, "n_campioni": 0}

    campioni = []
    for r in rows:
        dt = parse_dt_any(r["ts"])
        if dt is None:
            continue
        minuti = (adesso - dt).total_seconds() / 60.0
        campioni.append((-minuti, r))          # crescente nel tempo
    campioni.sort(key=lambda x: x[0])
    if not campioni:
        return {"station": station, "ts": None, "wind": None, "gust": None,
                "dir": None, "gust_rec": None, "gust_rec_stato": "no_data",
                "cadenza_min": None, "n_campioni": 0}

    ultimo = campioni[-1][1]
    tempi = [t for t, _r in campioni]
    cad = sampling_cadence(tempi)
    # La raffica del riquadro: l'ultima che la centralina ha DATO, purche'
    # vicina all'ultimo campione. A Malcesine il canale vivo non porta la
    # raffica e l'intraday si', ogni trenta minuti: prendere la raffica
    # dell'ultimo campione in assoluto avrebbe scritto "non disponibile" con
    # una raffica di dieci minuti prima in archivio.
    #
    # La finestra segue la CADENZA della centralina, non un numero fisso.
    # Con 45 minuti buoni per una centralina da dieci minuti, una da un'ora
    # (Addicted) perdeva la raffica ogni volta che l'ora in corso non aveva
    # ancora il suo massimo: il campione precedente era a sessanta minuti,
    # cioe' sempre fuori. In pagina si vedeva il vento e "raffica non
    # disponibile" accanto, con la raffica in archivio.
    t_ult = campioni[-1][0]
    indietro = max(45.0, 2.0 * (cad or 0.0))
    raffica_recente = None
    for t, r in reversed(campioni):
        if r["gust_kn"] is not None and t >= t_ult - indietro:
            raffica_recente = r["gust_kn"]
            break

    # La raffica ricorrente, alla sua finestra dichiarata di 30 minuti e non
    # a un'altra. Dove la cadenza non la sostiene non si allarga la finestra
    # tenendo il nome: si dice che non e' stimabile.
    # La finestra si conta dall'ULTIMO CAMPIONE, non da adesso. Se la
    # centralina tace da cinque ore, la ricorrente delle sue ultime mezz'ora
    # esiste ancora: e' il dato a essere vecchio, e lo dice il suo orario, una
    # volta, per tutta la lettura. Contarla da adesso avrebbe prodotto un
    # "raffica non stimabile" accanto a un vento perfettamente stampato -
    # due modi diversi di dire la stessa cosa, uno dei quali sbagliato.
    t_ultimo = campioni[-1][0]
    ric, stato = None, "ok"
    recenti = [(t, r["gust_kn"]) for t, r in campioni
               if t >= t_ultimo - FINESTRA_PASSATO_MIN and r["gust_kn"] is not None]
    # La cadenza che conta qui e' quella dei campioni CON la raffica, non
    # quella di tutti i campioni: se la centralina manda il vento ogni dieci
    # minuti e la raffica ogni trenta, la finestra da trenta non si sostiene,
    # e usare la cadenza generale la farebbe sembrare sostenibile.
    cad_raffica = sampling_cadence([t for t, _g in recenti]) if recenti else None
    if not recenti:
        stato = "raffica assente"
    elif not window_estimable(cad_raffica, FINESTRA_RICORRENTE_MIN):
        stato = "cadenza troppo rada per la finestra di %g min" % FINESTRA_RICORRENTE_MIN
    else:
        serie = recurrent_gust(recenti, centered=False, cadence_min=cad_raffica)
        validi = [v for _t, v in serie if v is not None]
        if not validi:
            stato = "campioni insufficienti nella finestra"
        else:
            ric = validi[-1]

    direzione, dir_da = ultimo["dir_deg"], None
    if direzione is None:
        direzione, dir_da = store.direzione_recente(station)

    return {
        "station": station,
        "ts": ultimo["ts"],
        "wind": ultimo["wind_kn"],
        "gust": raffica_recente,
        "dir": direzione,
        "dir_prestito": dir_da,
        "gust_rec": ric,
        "gust_rec_stato": stato,
        "gust_rec_finestra_min": FINESTRA_RICORRENTE_MIN,
        "cadenza_min": cad,
        "cadenza_raffica_min": cad_raffica,
        "n_campioni": len(campioni),
    }


def _station_of(place):
    return next((config.SPOTS[s]["station"] for s in config.SPOTS
                 if config.SPOTS[s]["place"] == place), None)


def curve(place, adesso=None):
    """Le curve del vento MISURATO oggi, in coordinate normalizzate.

    Il numerone "adesso" si aggiornava da solo, la curva del misurato no: era
    quella della costruzione della pagina, quindi vecchia di ore, e il
    confronto fra le due - un 22 kn scritto grande sopra una riga che si
    fermava a mezzogiorno - faceva sembrare rotto il grafico. Qui la curva
    viene riscritta ogni volta che si rilegge il file.

    Una scelta da dichiarare: la giornata e' quella di ADESSO, non quella
    dell'ultimo campione. Se la centralina tace da ieri non si disegna la sua
    curva di ieri sul grafico di oggi: si lascia quella della costruzione e
    l'eta' del dato, che la pagina scrive accanto, dice perche'.

    I campioni li legge engine.campioni_fini, che e' la stessa lettura della
    pagina costruita: una fonte sola per giornata, la raffica ricorrente a
    trenta minuti. Una seconda lettura scritta qui avrebbe riportato i gradini
    da dieci nodi che quella regola ha tolto.
    """
    adesso = adesso or utc_now()
    st = _station_of(place)
    if not st:
        return None
    from . import engine
    fini = [r for r in engine.campioni_fini(st, local_day(adesso))
            if CURVA_ORA_DA <= r.get("hour", -1) <= CURVA_ORA_A]
    # Fuori finestra si SCARTA, non si schiaccia al bordo: un campione delle
    # tre di notte appoggiato sulle quattro disegnerebbe un tratto orizzontale
    # che nessuno ha misurato. In altezza invece si schiaccia, perche' e' la
    # stessa cosa che fa il grafico con la previsione: una punta oltre la
    # scala si vede al bordo della scala, non si butta.
    def ux(h):
        return clamp((h - CURVA_ORA_DA) / (CURVA_ORA_A - CURVA_ORA_DA), 0.0, 1.0)

    def uy(v):
        return clamp(float(v) / CURVA_KN_MAX, 0.0, 1.0)

    media = [(ux(r["hour"]), uy(r["wind"])) for r in fini
             if r.get("wind") is not None]
    raffica = [(ux(r["hour"]), uy(r["gust"])) for r in fini
               if r.get("gust") is not None]
    if len(media) < 2:
        return None
    ultimo = [r for r in fini if r.get("wind") is not None][-1]
    picco = max([r["wind"] for r in fini if r.get("wind") is not None]
                + [r["gust"] for r in fini if r.get("gust") is not None])
    return {
        "ora_da": CURVA_ORA_DA, "ora_a": CURVA_ORA_A, "ymax": CURVA_KN_MAX,
        "media": curva_monotona(media, cifre=4),
        "raffica": (curva_monotona(raffica, cifre=4)
                    if len(raffica) >= 2 else None),
        "max_kn": round(picco, 1),
        "ultimo": {"x": round(ux(ultimo["hour"]), 4),
                   "y": round(uy(ultimo["wind"]), 4),
                   "ora": round(ultimo["hour"], 3),
                   "kn": round(ultimo["wind"], 1)},
        "n": len(media),
    }


def snapshot(adesso=None):
    """Il contenuto di live.json: un luogo per centralina, piu' l'ora di scrittura.

    "generato" serve a sapere quando il file e' stato scritto, cioe' se il
    processo veloce sta ancora girando. E' un'informazione diversa dall'eta'
    del dato, e vanno tenute distinte: il file puo' essere stato scritto un
    minuto fa e contenere una lettura di due ore fa, e in quel caso il
    problema e' la centralina, non la pubblicazione.
    """
    adesso = adesso or utc_now()
    luoghi = {}
    for place in config.PLACES:
        st = _station_of(place)
        if st:
            luoghi[place] = stazione(st, adesso=adesso)
    # Ogni luogo porta anche il suo pezzo di pagina gia' scritto. Le parole -
    # i punti cardinali, "da nord-est", "raffica non disponibile" - restano
    # definite in web.py, in un posto solo: se il browser dovesse ricostruirle
    # da se', ci sarebbero due versioni della stessa frase, e prima o poi
    # direbbero due cose diverse. L'import e' qui dentro e non in testa per
    # non legare il processo veloce all'intero modulo della pagina quando
    # serve solo il dato.
    from . import web
    for place, v in luoghi.items():
        v["html"] = web.now_observed_html(v)
        # Da quanti minuti questo dato e' "non recente": dipende dalla
        # cadenza della centralina, e la pagina non la conosce - gliela
        # portiamo insieme al dato, come le parole.
        v["stale_min"] = web.stantia_min(v.get("cadenza_min"))
        v["curve"] = curve(place, adesso=adesso)
    return {"generato": iso_utc(adesso), "versione": config.APP_VERSION,
            "luoghi": luoghi}


def scrivi(path, adesso=None):
    """Scrive live.json. Atomico: chi lo sta leggendo non trova mezzo file."""
    dati = snapshot(adesso=adesso)
    cartella = os.path.dirname(os.path.abspath(path))
    if cartella:
        os.makedirs(cartella, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False, default=str, indent=1)
    os.replace(tmp, path)
    return dati
