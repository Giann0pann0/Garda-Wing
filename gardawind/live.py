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
from .util import (FINESTRA_RICORRENTE_MIN, iso_utc, parse_dt_any,
                   recurrent_gust, sampling_cadence, utc_now,
                   window_estimable)

# Quanto passato guardare per la raffica ricorrente. Serve piu' della finestra
# stessa: la mediana su trenta minuti ha bisogno dei campioni di quei trenta
# minuti, e con qualche minuto di margine si sopravvive a un campione perso.
FINESTRA_PASSATO_MIN = 90.0


def stazione(station, adesso=None):
    """Lo stato osservato di una centralina. Nessuna stima, nessun modello."""
    adesso = adesso or utc_now()
    rows = list(store.connect().execute(
        "SELECT ts, wind_kn, gust_kn, dir_deg FROM obs_sample "
        "WHERE station=? ORDER BY ts DESC LIMIT 40", (station,)))
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

    return {
        "station": station,
        "ts": ultimo["ts"],
        "wind": ultimo["wind_kn"],
        "gust": ultimo["gust_kn"],
        "dir": ultimo["dir_deg"],
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
    for v in luoghi.values():
        v["html"] = web.now_observed_html(v)
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
