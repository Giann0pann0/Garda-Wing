"""L'avviso che non e' una previsione: "l'Ora e' arrivata".

Il processo veloce legge le centraline ogni dieci minuti. Sa gia' - con la
stessa funzione del report e della scheda - se la mezz'ora sostenuta sopra
soglia e' cominciata. Quando succede, lo dice: su Telegram, a chi ha scelto
di riceverlo.

Non prevede niente. MISURA. E' l'avviso piu' onesto che esista, e chi e' in
ufficio a Rovereto alle 12:40 vuole esattamente questo messaggio.

Tre cose, dichiarate:

  1. "arrivata" e' la definizione di orari.py: vento medio sopra min_kn per
     PERSISTENZA_MIN di seguito, con la direzione dentro il settore del
     regime. Diciassette nodi da nord al mattino non sono l'Ora, e non
     mandano nessun avviso dell'Ora.

  2. Un avviso per regime per giorno, il primo istante in cui la mezz'ora e'
     completa. Poi silenzio: il vento oscilla, e un avviso che va e viene ogni
     dieci minuti e' peggio di nessun avviso. Lo stato ("gia' detto") vive
     nel database del processo veloce, che sopravvive fra un'esecuzione e
     l'altra.

  3. Se il token non c'e', il modulo non fa niente e non si lamenta: il
     processo veloce deve continuare a scrivere live.json anche per chi non
     ha mai configurato un bot.

Il token NON sta in questo file, ne' in un altro file del repository: viene
dall'ambiente (TELEGRAM_BOT_TOKEN, un segreto del repository) e il canale da
TELEGRAM_CHAT. Un token in un file e' un token pubblico.
"""
import json
import os
import urllib.parse
import urllib.request

from . import config, orari, store
from .util import (angle_diff, iso_utc, local_day, parse_dt_any,
                   sampling_cadence, sustained_onset, to_local, utc_now)

API = "https://api.telegram.org/bot%s/sendMessage"
TIMEOUT_S = 15


def _spot_hourly():
    for name in config.SPOT_ORDER:
        spot = config.SPOTS[name]
        if spot.get("target") == "hourly":
            yield name, spot


def stato_regime(name, giorno=None, adesso=None):
    """E' arrivato oggi, e quando. Solo misura, nessuna stima.

    Ritorna None se il regime oggi non e' (ancora) arrivato, altrimenti
    {"minuto", "vento", "raffica", "dir"} dell'ingresso e dell'ultimo campione.
    """
    spot = config.SPOTS[name]
    adesso = adesso or utc_now()
    giorno = giorno or local_day(adesso)
    try:
        inizio, fine = orari.finestra_utile_del_giorno(name, giorno)
    except (KeyError, ValueError, TypeError):
        return None
    if fine <= inizio:
        return None
    campioni = store.samples_since(
        spot["station"], (giorno + "T00:00:00Z"))
    serie, ultimo = [], None
    per_ist = {}
    for r in campioni:
        dt = parse_dt_any(r["ts"])
        if dt is None or local_day(dt) != giorno or r.get("wind_kn") is None:
            continue
        per_ist.setdefault(iso_utc(dt), (dt, r))
    for _k, (dt, r) in sorted(per_ist.items()):
        loc = to_local(dt)
        minuto = loc.hour * 60.0 + loc.minute
        if not (inizio <= minuto <= fine):
            continue
        # Il regime E' una direzione: un campione fuori settore vale zero,
        # cosi' non puo' contribuire alla mezz'ora. Non si butta via il
        # campione - la serie deve restare continua - si dice che quel vento
        # non e' questo regime.
        d = r.get("dir_deg")
        dentro = (d is not None and angle_diff(float(d), float(spot["axis_obs"]))
                  <= config.REGIME_SECTOR_DEG)
        serie.append((minuto, float(r["wind_kn"]) if dentro else 0.0))
        ultimo = (minuto, r)
    if len(serie) < 3:
        return None
    cad = sampling_cadence([m for m, _v in serie])
    onset = sustained_onset(serie, float(spot["min_kn"]),
                            persist_min=orari.PERSISTENZA_MIN, cadence_min=cad)
    if onset is None:
        return None
    m_ult, r_ult = ultimo
    return {"spot": name, "giorno": giorno, "minuto": float(onset),
            "vento": float(r_ult["wind_kn"]),
            "raffica": r_ult.get("gust_kn"), "dir": r_ult.get("dir_deg"),
            "ultimo_minuto": m_ult, "soglia": spot["min_kn"]}


def _chiave(name, giorno):
    return "avviso:%s:%s" % (name, giorno)


def testo(stato):
    """Il messaggio, in italiano, corto. Il nome del prodotto e' la notizia."""
    spot = config.SPOTS[stato["spot"]]
    regime = spot["regime"]
    if regime == "ORA":
        titolo = "l’Ora è arrivata"
    elif regime == "PELER":
        titolo = "il Pelèr è arrivato"
    else:
        titolo = "%s è arrivato" % regime.lower()
    h, m = int(stato["minuto"] // 60), int(round(stato["minuto"] % 60))
    riga = "%02d:%02d · %.0f kn" % (h, m, stato["vento"])
    if stato.get("raffica"):
        riga += ", raffica %.0f" % float(stato["raffica"])
    return ("%s · %s\n%s\nda mezz’ora sopra %.0f kn"
            % (spot["place"], titolo, riga, stato["soglia"]))


def da_inviare(adesso=None):
    """Gli avvisi non ancora mandati, e li segna come mandati SOLO dopo l'invio."""
    adesso = adesso or utc_now()
    giorno = local_day(adesso)
    out = []
    for name, _spot in _spot_hourly():
        if store.meta_get(_chiave(name, giorno)):
            continue
        st = stato_regime(name, giorno, adesso)
        if st:
            out.append(st)
    return out


def segna_inviato(stato):
    store.meta_set(_chiave(stato["spot"], stato["giorno"]), iso_utc(utc_now()))


def invia(token, chat, messaggio, opener=None):
    """Una richiesta a Telegram. Solleva su errore: chi chiama decide."""
    dati = urllib.parse.urlencode({"chat_id": chat, "text": messaggio,
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(API % token, data=dati)
    apri = opener or urllib.request.urlopen
    with apri(req, timeout=TIMEOUT_S) as r:
        risposta = json.loads(r.read().decode("utf-8"))
    if not risposta.get("ok"):
        raise RuntimeError("telegram: %s" % risposta.get("description", "?"))
    return risposta


def esegui(token=None, chat=None, adesso=None, opener=None):
    """Il ciclo del processo veloce: trova, manda, segna. Righe di log."""
    token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat if chat is not None else os.environ.get("TELEGRAM_CHAT", "")
    righe = []
    if not token or not chat:
        righe.append("avvisi: non configurati (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT)")
        return righe
    for st in da_inviare(adesso):
        msg = testo(st)
        try:
            invia(token, chat, msg, opener)
        except Exception as e:                      # rete, token, canale
            righe.append("avvisi: NON inviato %s (%s)" % (st["spot"], str(e)[:120]))
            continue
        segna_inviato(st)
        righe.append("avvisi: inviato %s" % msg.replace("\n", " / "))
    if len(righe) == 0:
        righe.append("avvisi: niente da dire")
    return righe


__all__ = ["stato_regime", "da_inviare", "testo", "invia", "esegui"]
