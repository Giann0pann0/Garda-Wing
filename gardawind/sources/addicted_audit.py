"""Audit dell'archivio addicted-sports, stazione per stazione.

Prima di usare una fonte storica bisogna sapere cosa contiene davvero, e la
risposta non puo' venire da come e' fatta l'interfaccia: viene da avere
scaricato i giorni e guardato cosa e' arrivato.

Il canale e' quello che la pagina usa per il suo grafico:

    <pagina della stazione>?json=wind&from=YYYY-MM-DD

e risponde con array paralleli: "arch" (le chiavi degli slot, ora LOCALE),
"mavg" (media misurata), "mmax" (massimo misurato), "dir" (direzione
PREVISTA, non misurata).

IL CONTROLLO CHE VIENE PRIMA DI TUTTI. Un server puo' ignorare "from" e
rispondere sempre con la giornata di oggi. Se non lo si verifica, una sonda
conclude "ci sono anni di storico" mentre sta rileggendo mille volte lo stesso
giorno - ed e' l'errore piu' costoso possibile qui, perche' non si vede: i
dati ci sono, sono solo sempre gli stessi. Quindi ogni risposta viene
confrontata con il giorno RICHIESTO, e se le chiavi non cadono in quel giorno
la giornata e' marcata "from ignorato" e non conta come storico.

Due Malcesine restano due stazioni. Non si uniscono qui: due centraline che
misurano lo stesso lago a qualche chilometro di distanza vanno prima
confrontate, e unirle prima del confronto vorrebbe dire non poterlo piu' fare.

Niente di questo modulo scrive nel database delle osservazioni: scrive file
grezzi separati per stazione e restituisce fatti. La decisione di ingerire
viene dopo, e la prende chi legge l'audit.
"""

import hashlib
import json as _json
import os
import re

from .. import config, store
from ..util import iso_utc, median, sampling_cadence, utc_now
from .http import FetchError, fetch_text

PARSER_VERSION = "addicted-audit/1"

# Le stazioni del lago sulla stessa struttura di indirizzo. Gli slug sono
# quelli dell'indirizzo pubblico; se uno non esiste, l'audit lo dice invece di
# fermarsi - sapere che una stazione NON c'e' e' un risultato.
SLUG_STAZIONI = ("torbole", "limone", "malcesine", "campione", "malcesinenord")

BASE = "https://it.addicted-sports.com/forecast/gardasee/%s/"

# I passi con cui si cerca l'orizzonte: prima a salti, poi per bisezione.
# Andare giorno per giorno su quattordici anni sarebbe cinquemila richieste a
# un sito che non ci ha chiesto niente.
SALTI_GIORNI = (1, 3, 7, 14, 30, 60, 120, 240, 365, 730, 1095, 1825, 3650)


def url_stazione(slug):
    return BASE % slug


def url_json(slug, giorno):
    return "%s?json=wind&from=%s" % (url_stazione(slug), giorno)


def impronta(corpo):
    if corpo is None:
        return None
    return hashlib.sha256(corpo.encode("utf-8", "replace")).hexdigest()


def cartella_raw(slug, base=None):
    base = base or os.path.join(store.support_dir(), "raw", "addicted")
    p = os.path.join(base, slug)
    os.makedirs(p, exist_ok=True)
    return p


def salva_raw(slug, giorno, corpo, meta, base=None):
    """Il grezzo e la sua provenienza, separati per stazione."""
    cart = cartella_raw(slug, base)
    percorso = os.path.join(cart, "%s.json" % giorno)
    with open(percorso, "w", encoding="utf-8") as fh:
        fh.write(corpo if corpo is not None else "")
    with open(percorso + ".meta", "w", encoding="utf-8") as fh:
        _json.dump(meta, fh, ensure_ascii=False, indent=1, default=str)
    return percorso


_RE_CHIAVE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})/(\d{2})(\d{2})$")


def _chiave_giorno(chiave):
    m = _RE_CHIAVE.match(str(chiave))
    return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)) if m else None


def _chiave_minuti(chiave):
    m = _RE_CHIAVE.match(str(chiave))
    return (int(m.group(4)) * 60 + int(m.group(5))) if m else None


def audit_giorno(slug, giorno, salva=True, base_raw=None, adesso=None):
    """Un giorno di una stazione: cosa e' arrivato davvero. Nessuna stampa.

    Non solleva: un errore di rete o una risposta illeggibile sono RISULTATI
    dell'audit, non incidenti da propagare - la sonda deve poter continuare
    sulle altre giornate.
    """
    url = url_json(slug, giorno)
    fetched_at = iso_utc(adesso or utc_now())
    esito = {
        "slug": slug, "giorno": giorno, "url": url, "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "ok": False, "errore": None, "bytes": None, "sha256": None,
        "json": False, "campo_ok": None,
        "n_slot": 0, "n_mavg": 0, "n_mmax": 0, "n_dir": 0,
        "primo": None, "ultimo": None, "giorni_nelle_chiavi": [],
        "from_ignorato": None, "cadenza_min": None, "buchi": None,
        "mavg_min": None, "mavg_max": None, "mmax_min": None, "mmax_max": None,
        "mmax_sotto_mavg": 0, "mae_dichiarato": None,
        "campi": [], "raw": None,
    }
    try:
        corpo = fetch_text(url, timeout=45)
    except FetchError as e:
        esito["errore"] = str(e)[:200]
        if salva:
            esito["raw"] = salva_raw(slug, giorno, "", esito, base_raw)
        return esito

    esito["bytes"] = len(corpo)
    esito["sha256"] = impronta(corpo)
    if salva:
        esito["raw"] = salva_raw(slug, giorno, corpo, esito, base_raw)

    try:
        dati = _json.loads(corpo)
    except ValueError as e:
        # Non e' JSON: molto probabilmente e' la pagina HTML. Distinguere i due
        # casi conta, perche' "la stazione non esiste" e "il canale json non
        # risponde per questa stazione" portano a decisioni diverse.
        esito["errore"] = ("risposta non JSON (%s): sembra %s"
                           % (str(e)[:60],
                              "HTML" if corpo.lstrip()[:1] == "<" else "altro"))
        return esito

    esito["json"] = True
    if not isinstance(dati, dict):
        esito["errore"] = "JSON non e' un oggetto: %s" % type(dati).__name__
        return esito
    esito["campi"] = sorted(dati.keys())
    esito["campo_ok"] = dati.get("ok")
    esito["mae_dichiarato"] = dati.get("mae")

    arch = dati.get("arch") or []
    mavg = dati.get("mavg") or []
    mmax = dati.get("mmax") or []
    dirs = dati.get("dir") or []
    esito.update({"n_slot": len(arch), "n_mavg": sum(1 for v in mavg if v is not None),
                  "n_mmax": sum(1 for v in mmax if v is not None),
                  "n_dir": sum(1 for v in dirs if v is not None)})
    if not arch:
        esito["errore"] = "nessuno slot (arch vuoto)"
        return esito

    giorni = sorted({_chiave_giorno(k) for k in arch} - {None})
    esito["giorni_nelle_chiavi"] = giorni
    esito["primo"], esito["ultimo"] = str(arch[0]), str(arch[-1])
    # IL controllo: le chiavi cadono nel giorno richiesto?
    esito["from_ignorato"] = giorno not in giorni

    minuti = [_chiave_minuti(k) for k in arch if _chiave_giorno(k) == giorno]
    minuti = [m for m in minuti if m is not None]
    if len(minuti) >= 2:
        esito["cadenza_min"] = sampling_cadence(sorted(minuti))
    # I buchi: slot del giorno richiesto senza media misurata.
    dentro = [i for i, k in enumerate(arch) if _chiave_giorno(k) == giorno]
    if dentro:
        esito["buchi"] = sum(1 for i in dentro
                             if i >= len(mavg) or mavg[i] is None)
    vals_a = [v for v in mavg if isinstance(v, (int, float))]
    vals_m = [v for v in mmax if isinstance(v, (int, float))]
    if vals_a:
        esito["mavg_min"], esito["mavg_max"] = min(vals_a), max(vals_a)
    if vals_m:
        esito["mmax_min"], esito["mmax_max"] = min(vals_m), max(vals_m)
    # Semantica: se mmax e' "il massimo dell'ora" non puo' stare sotto la
    # media della stessa ora. Se capita, la coppia di nomi non vuol dire
    # quello che sembra, e lo si scopre qui invece che a modello addestrato.
    esito["mmax_sotto_mavg"] = sum(
        1 for a, m in zip(mavg, mmax)
        if isinstance(a, (int, float)) and isinstance(m, (int, float)) and m < a)
    esito["ok"] = bool(arch) and not esito["from_ignorato"]
    return esito


def trova_orizzonte(slug, oggi=None, salva=True, base_raw=None,
                    salti=SALTI_GIORNI, su_progresso=None):
    """Fin dove torna indietro il canale, per questa stazione.

    Prima a salti, poi per bisezione fra l'ultimo giorno buono e il primo
    vuoto. Ritorna (risultati, orizzonte) dove orizzonte e' il giorno piu'
    vecchio con una serie misurata nel giorno richiesto.
    """
    import datetime as _dt
    oggi = oggi or _dt.date.today()
    risultati, buoni = {}, []

    def prova(delta):
        g = (oggi - _dt.timedelta(days=delta)).isoformat()
        if g in risultati:
            return risultati[g]
        r = audit_giorno(slug, g, salva=salva, base_raw=base_raw)
        risultati[g] = r
        if su_progresso:
            su_progresso(delta, r)
        return r

    ultimo_buono, primo_vuoto = None, None
    for d in salti:
        r = prova(d)
        if r["ok"] and r["n_mavg"] > 0:
            ultimo_buono = d
            buoni.append(d)
        else:
            primo_vuoto = d
            break

    # Bisezione fra l'ultimo buono e il primo vuoto: al massimo una decina di
    # richieste in piu', e l'orizzonte esce con la precisione di un giorno.
    if ultimo_buono is not None and primo_vuoto is not None:
        lo, hi = ultimo_buono, primo_vuoto
        while hi - lo > 1:
            mid = (lo + hi) // 2
            r = prova(mid)
            if r["ok"] and r["n_mavg"] > 0:
                lo = mid
            else:
                hi = mid
        ultimo_buono = lo

    orizzonte = None
    if ultimo_buono is not None:
        orizzonte = (oggi - _dt.timedelta(days=ultimo_buono)).isoformat()
    return risultati, orizzonte


def riassumi(risultati):
    """I fatti di una stazione, aggregati. Nessun giudizio, nessuna stampa."""
    tutti = [r for r in risultati.values()]
    buoni = [r for r in tutti if r["ok"] and r["n_mavg"] > 0]
    ignorati = [r for r in tutti if r["from_ignorato"]]
    non_json = [r for r in tutti if not r["json"]]
    cad = [r["cadenza_min"] for r in buoni if r["cadenza_min"]]
    campi = set()
    for r in tutti:
        campi.update(r["campi"])
    return {
        "n_provati": len(tutti),
        "n_con_serie": len(buoni),
        "n_from_ignorato": len(ignorati),
        "n_non_json": len(non_json),
        "campi_visti": sorted(campi),
        "cadenza_mediana": median(cad) if cad else None,
        "slot_per_giorno": median([r["n_slot"] for r in buoni]) if buoni else None,
        "buchi_mediani": median([r["buchi"] for r in buoni
                                 if r["buchi"] is not None]) if buoni else None,
        "mavg_max": max([r["mavg_max"] for r in buoni
                         if r["mavg_max"] is not None] or [None] or [None])
        if any(r["mavg_max"] is not None for r in buoni) else None,
        "mmax_max": max([r["mmax_max"] for r in buoni
                         if r["mmax_max"] is not None])
        if any(r["mmax_max"] is not None for r in buoni) else None,
        "mmax_sotto_mavg": sum(r["mmax_sotto_mavg"] for r in tutti),
        "mae_dichiarato": next((r["mae_dichiarato"] for r in buoni
                                if r["mae_dichiarato"] is not None), None),
        "errori": sorted({r["errore"] for r in tutti if r["errore"]}),
    }
