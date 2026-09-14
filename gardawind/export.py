"""Esportazione statica del cruscotto.

Produce una cartella di file HTML autosufficienti, senza server. Serve a due
cose che sembrano diverse ma sono la stessa: consultare la previsione da un
telefono in spiaggia, e farla vivere in rete senza tenere acceso un computer.

Il contenuto e' identico a quello servito da /: stesse funzioni, stesso
modello, stessi numeri. L'unica differenza sono i collegamenti, che diventano
relativi, e l'assenza delle azioni che avrebbero bisogno di un processo vivo
(aggiornare, spegnere).
"""

import json
import os
import re

from . import config, engine, live, store, web
from .util import iso_utc, utc_now

# Le azioni che esistono solo con un server dietro.
_DROP = [
    (re.compile(r'\s*&nbsp;·&nbsp;\s*<a href="/spegni">[^<]*</a>'), ""),
    (re.compile(r'\s*·\s*<a href="/aggiorna[^"]*">[^<]*</a>'), ""),
    (re.compile(r"setTimeout\(function\(\)\{location\.reload\(\)\},\d+\);"), ""),
]

_LINKS = [
    ('href="/diagnostica"', 'href="diagnostica.html"'),
    ('href="/"', 'href="index.html"'),
]


def _staticize(html_text):
    for pattern, repl in _DROP:
        html_text = pattern.sub(repl, html_text)
    for a, b in _LINKS:
        html_text = html_text.replace(a, b)
    return html_text


def _banner(built_at):
    """Cosa si aggiorna da solo e cosa no. Distinguerlo non e' un dettaglio.

    La previsione e' quella del momento in cui la pagina e' stata costruita, e
    per cambiarla bisogna ricostruirla. Il dato osservato no: quello la pagina
    lo rilegge da sola, e l'eta' che mostra e' sempre calcolata sull'orario
    del campione. Dire "non si aggiorna da sola", come diceva prima questa
    riga, sarebbe ormai falso per metà della pagina - ed e' la metà che si
    guarda per decidere se andare in acqua.
    """
    return (
        '<div class="panel"><p style="margin:0">Previsione calcolata il '
        '<b>%s</b>: per cambiarla la pagina va ricostruita. Le '
        '<b>condizioni attuali</b>, invece, si aggiornano da sole ogni pochi '
        'minuti, e l\u2019orario accanto dice sempre di quando è il dato: se '
        'invecchia, lo vedi.</p></div>'
        % built_at)


def export(directory, with_json=True):
    """Scrive index.html, diagnostica.html e (opzionale) previsione.json."""
    os.makedirs(directory, exist_ok=True)
    built = utc_now()
    built_local = web.to_local(built).strftime("%d/%m/%Y alle %H:%M")

    # Nel sito pubblicato il dato osservato non si legge accanto alla pagina
    # (Pages si pubblica tutto insieme, quel file si aggiornerebbe solo
    # ricostruendo il sito): si legge dal ramo dedicato che il processo veloce
    # riscrive. L'indirizzo si sostituisce QUI, non dentro la pagina, cosi'
    # l'app sul Mac continua a chiedere il suo /live.json.
    url_prima = web.LIVE_URL
    web.LIVE_URL = config.LIVE_JSON_URL or web.LIVE_URL
    try:
        home = _staticize(web.page_home())
    finally:
        web.LIVE_URL = url_prima
    home = home.replace('<main class="wrap">', '<main class="wrap">' + _banner(built_local))
    diag = _staticize(web.page_diagnostics())

    written = []
    for name, content in (("index.html", home), ("diagnostica.html", diag)):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written.append(path)

    # Il dato osservato va anche in un file suo, piccolo, che la pagina
    # rilegge da sola. Scriverlo anche qui - e non solo nel processo veloce -
    # serve perche' il sito appena costruito non resti senza: se il processo
    # veloce non ha ancora girato, la pagina trova comunque un live.json
    # coerente con i numeri che ha stampato dentro.
    path = os.path.join(directory, "live.json")
    live.scrivi(path)
    written.append(path)

    if with_json:
        payload = {
            "generato": iso_utc(built),
            "versione": config.APP_VERSION,
            "giorni": engine.by_day(),
            "modelli": {
                name: store.load_learned(name, "daily")
                for name in config.SPOT_ORDER
            },
        }
        path = os.path.join(directory, "previsione.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str, indent=1)
        written.append(path)

    return written
