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

from . import config, engine, store, web
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
    return (
        '<div class="panel"><p style="margin:0">Pagina statica, generata il '
        '<b>%s</b>. Non si aggiorna da sola: la rigenera il processo che la '
        'pubblica. Se i numeri sembrano vecchi, è perché lo sono.</p></div>'
        % built_at)


def export(directory, with_json=True):
    """Scrive index.html, diagnostica.html e (opzionale) previsione.json."""
    os.makedirs(directory, exist_ok=True)
    built = utc_now()
    built_local = web.to_local(built).strftime("%d/%m/%Y alle %H:%M")

    home = _staticize(web.page_home())
    home = home.replace('<main class="wrap">', '<main class="wrap">' + _banner(built_local))
    diag = _staticize(web.page_diagnostics())

    written = []
    for name, content in (("index.html", home), ("diagnostica.html", diag)):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
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
