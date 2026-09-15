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

# Gli slug VERI, presi dalla pagina /historie/ del sito e non indovinati.
# La prima sonda aveva usato "limone", che risponde HTML: lo slug della
# stazione di Limone e' "caporeamol". E' il motivo per cui quella stazione
# sembrava senza archivio - lo slug della webcam non e' lo slug della serie.
#
# Accanto a ogni stazione, cio' che il sito DICHIARA: da quando, quante
# giornate misurate, quanti giorni di vento (col criterio della pagina:
# minKn=12, minHours=2). Sono numeri da confrontare con quello che si riesce
# a scaricare davvero: se scarichiamo 300 giornate dove il sito ne dichiara
# 959, non abbiamo l'archivio - ne abbiamo un terzo, e va saputo.
#
# Torbole: 959 giornate misurate su un periodo di 4342 giorni. L'archivio e'
# RADO al 22%: il tetto di cio' che si puo' scaricare e' 959, non dodici anni.
DICHIARATO = {
    "torbole":       {"dal": 2014, "giorni_misurati": 959,  "giorni_vento": 522,
                      "nome": "Gardasee, Torbole"},
    "caporeamol":    {"dal": 2014, "giorni_misurati": 820,  "giorni_vento": None,
                      "nome": "Gardasee, Limone"},
    "malcesine":     {"dal": 2014, "giorni_misurati": 1360, "giorni_vento": None,
                      "nome": "Gardasee, Malcesine"},
    "malcesinenord": {"dal": 2023, "giorni_misurati": 43,   "giorni_vento": None,
                      "nome": "Gardasee, Malcesine (Nord)"},
    "campione":      {"dal": 2017, "giorni_misurati": 735,  "giorni_vento": None,
                      "nome": "Gardasee, Campione"},
    "brenzone":      {"dal": 2017, "giorni_misurati": 735,  "giorni_vento": None,
                      "nome": "Gardasee, Brenzone"},
}

SLUG_STAZIONI = ("torbole", "caporeamol", "malcesine", "malcesinenord",
                 "campione", "brenzone")

# Una risposta copre 72 slot a cadenza oraria, cioe' TRE GIORNI, non uno. Da
# qui due conseguenze: per camminare l'archivio basta una richiesta ogni tre
# giorni, e "72 slot" non vuol dire che la stazione campiona ogni venti
# minuti - vuol dire che la risposta e' larga tre giorni.
ORE_PER_RISPOSTA = 72
PASSO_GIORNI = 3

# La pagina /historie/ dichiara anche il record di raffica. A Torbole e' 49,6
# kn (4 maggio 2018). Se leggendo mmax si trovano valori PIU' ALTI, uno dei
# due numeri non e' quello che dice il suo nome - e la cosa va chiarita prima
# di ingerire, non dopo.
RECORD_DICHIARATO_KN = {"torbole": 49.6}

BASE = "https://it.addicted-sports.com/forecast/gardasee/%s/"

# I passi con cui si cerca l'orizzonte: prima a salti, poi per bisezione.
# Andare giorno per giorno su quattordici anni sarebbe cinquemila richieste a
# un sito che non ci ha chiesto niente.
# Il passo piu' profondo va oltre l'eta' dell'archivio di Meteotrentino (2012)
# perche' la prima sonda su Torbole ha trovato dati a 3650 giorni e si e'
# fermata li': quel numero non era l'orizzonte, era il fondo della scala.
SALTI_GIORNI = (1, 3, 7, 14, 30, 60, 120, 240, 365, 730, 1095, 1825, 3650,
                4380, 5475, 7300)


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
        "n_mavg_giorno": 0, "n_mmax_giorno": 0,
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

    # Le misure che appartengono DAVVERO al giorno richiesto. Serve perche' una
    # risposta e' larga tre giorni: chiedendo un giorno due giorni prima
    # dell'inizio dell'archivio, la finestra contiene comunque misure - quelle
    # dei giorni dopo - e un "n_mavg > 0" farebbe concludere che l'archivio
    # comincia due giorni prima di dove comincia. L'ho scoperto solo dopo aver
    # reso il server di prova larga tre giorni come quello vero.
    esito["n_mavg_giorno"] = sum(
        1 for i, k in enumerate(arch)
        if _chiave_giorno(k) == giorno and i < len(mavg) and mavg[i] is not None)
    esito["n_mmax_giorno"] = sum(
        1 for i, k in enumerate(arch)
        if _chiave_giorno(k) == giorno and i < len(mmax) and mmax[i] is not None)

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

    def ha_misure(r):
        """Misure DEL GIORNO RICHIESTO, non della finestra di tre giorni."""
        return r["ok"] and r["n_mavg_giorno"] > 0

    ultimo_buono, primo_vuoto = None, None
    for d in salti:
        r = prova(d)
        if ha_misure(r):
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
            if ha_misure(r):
                lo = mid
            else:
                hi = mid
        ultimo_buono = lo

    orizzonte = None
    if ultimo_buono is not None:
        orizzonte = (oggi - _dt.timedelta(days=ultimo_buono)).isoformat()
    # Se nessuna giornata e' risultata vuota, la sonda ha esaurito la scala
    # senza toccare il fondo: quel giorno NON e' l'orizzonte, e' il punto piu'
    # profondo che abbiamo guardato. Dirlo cambia la conclusione da "l'archivio
    # comincia nel 2016" a "l'archivio arriva almeno al 2016", che e' un'altra
    # frase - e la prima sarebbe falsa.
    fondo_non_raggiunto = (primo_vuoto is None and ultimo_buono is not None)
    return risultati, {"orizzonte": orizzonte,
                       "fondo_non_raggiunto": fondo_non_raggiunto,
                       "passo_piu_profondo": max(salti)}


def riassumi(risultati):
    """I fatti di una stazione, aggregati. Nessun giudizio, nessuna stampa."""
    tutti = [r for r in risultati.values()]
    # "Con serie" vuol dire con misure del giorno richiesto: la finestra e'
    # larga tre giorni, e contare le misure della finestra gonfierebbe il conto.
    buoni = [r for r in tutti if r["ok"] and r.get("n_mavg_giorno", 0) > 0]
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


# ==========================================================================
# Censimento: quante giornate COMPLETE si riesce davvero a scaricare
# ==========================================================================
#
# "Una data campione del 2016 risponde" e "l'archivio e' scaricabile" sono due
# affermazioni diverse, e solo la seconda serve a decidere. Questo censimento
# cammina l'archivio dall'inizio dichiarato a oggi, a passi di tre giorni
# (una risposta copre 72 ore), e conta cosa arriva davvero.
#
# Tre proprieta' che lo rendono utilizzabile su migliaia di richieste:
#
#   RIPARTIBILE   una giornata il cui grezzo esiste gia' non viene richiesta
#                 di nuovo. Si puo' interrompere e riprendere, e una seconda
#                 esecuzione non ribatte il sito.
#   EDUCATO       un passo ogni tre giorni invece di uno al giorno, con il
#                 limitatore di frequenza del livello HTTP. Il sito non ci ha
#                 chiesto niente.
#   CONFRONTABILE il totale scaricato si mette accanto a quello DICHIARATO
#                 dalla pagina /historie/. Se scarichiamo 300 giornate dove il
#                 sito ne dichiara 959, non abbiamo l'archivio: ne abbiamo un
#                 terzo, e la differenza e' il risultato piu' importante.

# Una giornata si dice COMPLETA se ha almeno questa quota delle 24 ore con una
# media misurata. Non 24 su 24: una stazione vera perde qualche ora, e
# pretendere la perfezione conterebbe zero giornate complete su un archivio
# perfettamente usabile.
QUOTA_COMPLETA = 0.9


def giorni_da_censire(slug, oggi=None, dal=None, passo=PASSO_GIORNI):
    """Le date da chiedere: una ogni tre giorni, dall'inizio dichiarato a oggi."""
    import datetime as _dt
    oggi = oggi or _dt.date.today()
    anno = dal or (DICHIARATO.get(slug, {}).get("dal") or 2014)
    d = _dt.date(anno, 1, 1)
    out = []
    while d <= oggi:
        out.append(d.isoformat())
        d += _dt.timedelta(days=passo)
    return out


def censimento(slug, oggi=None, dal=None, base_raw=None, salta_esistenti=True,
               massimo=None, su_progresso=None):
    """Cammina l'archivio e conta. Ritorna (per_giorno, riassunto).

    per_giorno: {giorno_misurato: {"ore", "ore_mmax", "completa"}} costruito
    dalle chiavi arch di TUTTE le risposte - quindi conta i giorni veri, non
    le richieste: una risposta larga tre giorni ne riempie tre.
    """
    import datetime as _dt
    oggi = oggi or _dt.date.today()
    date = giorni_da_censire(slug, oggi=oggi, dal=dal)
    if massimo:
        date = date[-int(massimo):]

    per_giorno = {}
    n_richieste = n_saltate = n_errori = 0
    from_ignorato = 0
    mmax_visto = None
    cart = cartella_raw(slug, base_raw)

    for i, giorno in enumerate(date):
        percorso = os.path.join(cart, "%s.json" % giorno)
        corpo = None
        if salta_esistenti and os.path.exists(percorso):
            try:
                corpo = open(percorso, encoding="utf-8").read()
                n_saltate += 1
            except OSError:
                corpo = None
        if corpo is None:
            r = audit_giorno(slug, giorno, salva=True, base_raw=base_raw)
            n_richieste += 1
            if r["errore"]:
                n_errori += 1
            if r["from_ignorato"]:
                from_ignorato += 1
            corpo = None
            if r["json"] and r["raw"]:
                try:
                    corpo = open(r["raw"], encoding="utf-8").read()
                except OSError:
                    corpo = None
            if su_progresso:
                su_progresso(i, len(date), giorno, r)
        if not corpo:
            continue
        try:
            dati = _json.loads(corpo)
        except ValueError:
            continue
        arch = dati.get("arch") or []
        mavg = dati.get("mavg") or []
        mmax = dati.get("mmax") or []
        for k, chiave in enumerate(arch):
            g = _chiave_giorno(chiave)
            if not g:
                continue
            voce = per_giorno.setdefault(g, {"ore": 0, "ore_mmax": 0})
            if k < len(mavg) and mavg[k] is not None:
                voce["ore"] += 1
            if k < len(mmax) and mmax[k] is not None:
                voce["ore_mmax"] += 1
                v = mmax[k]
                if isinstance(v, (int, float)) and (mmax_visto is None or v > mmax_visto):
                    mmax_visto = v

    for g, voce in per_giorno.items():
        voce["completa"] = voce["ore"] >= 24 * QUOTA_COMPLETA

    con_dato = {g: v for g, v in per_giorno.items() if v["ore"] > 0}
    complete = {g: v for g, v in con_dato.items() if v["completa"]}
    con_mmax = {g: v for g, v in con_dato.items() if v["ore_mmax"] > 0}
    per_anno = {}
    for g, v in con_dato.items():
        a = g[:4]
        s = per_anno.setdefault(a, {"con_dato": 0, "complete": 0, "con_mmax": 0})
        s["con_dato"] += 1
        if v["completa"]:
            s["complete"] += 1
        if v["ore_mmax"] > 0:
            s["con_mmax"] += 1

    dich = DICHIARATO.get(slug, {})
    atteso = dich.get("giorni_misurati")
    riassunto = {
        "slug": slug,
        "n_richieste": n_richieste, "n_dalla_cache": n_saltate,
        "n_errori": n_errori, "n_from_ignorato": from_ignorato,
        "n_giorni_visti": len(per_giorno),
        "n_con_dato": len(con_dato),
        "n_complete": len(complete),
        "n_con_mmax": len(con_mmax),
        "primo": min(con_dato) if con_dato else None,
        "ultimo": max(con_dato) if con_dato else None,
        "per_anno": per_anno,
        "dichiarato": atteso,
        "quota_del_dichiarato": (len(con_dato) / float(atteso)) if atteso else None,
        "mmax_visto": mmax_visto,
        "record_dichiarato": RECORD_DICHIARATO_KN.get(slug),
        "mmax_oltre_record": (
            mmax_visto is not None
            and RECORD_DICHIARATO_KN.get(slug) is not None
            and mmax_visto > RECORD_DICHIARATO_KN[slug]),
    }
    return per_giorno, riassunto
