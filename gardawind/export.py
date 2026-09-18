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
import shutil
import re

from . import config, engine, icona, live, store, web
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
    # La navigazione fra localita' diventa relativa. Si ricava da
    # config.PLACES, come la navigazione stessa: se un giorno si aggiunge una
    # localita', qui non c'e' niente da ricordarsi di cambiare - ed e' il
    # punto della richiesta, perche' una voce di menu senza pagina dietro e'
    # un vicolo cieco che nessun controllo prenderebbe.
    for place in config.PLACES:
        slug = web._slug(place)
        html_text = html_text.replace('href="/%s"' % slug, 'href="%s.html"' % slug)
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
        # Una riga piccola, non un riquadro: e' un'avvertenza, non un
        # contenuto, e in cima alla pagina un riquadro grigio era la prima
        # cosa che si vedeva dopo il titolo.
        '<p class="costruita">Previsione calcolata il '
        '<b>%s</b>: per cambiarla la pagina va ricostruita. Le '
        '<b>condizioni attuali</b>, invece, si aggiornano da sole ogni pochi '
        'minuti, e l\u2019orario accanto dice sempre di quando è il dato: se '
        'invecchia, lo vedi.</p>'
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
        # Una pagina per localita', e i nomi dei file li decide web._slug:
        # la prima di config.PLACES e' index.html, le altre portano il proprio
        # nome. Cosi' la navigazione e i file vengono dalla stessa lista, e non
        # possono raccontare due strutture diverse.
        pagine = [(web._slug(place) + ".html",
                   _staticize(web.page_luogo(place)))
                  for place in config.PLACES]
    finally:
        web.LIVE_URL = url_prima
    # In coda al contenuto, non in testa: e' un'avvertenza, si legge dopo.
    pagine = [(nome, testo.replace('</main>', _banner(built_local) + '</main>'))
              for nome, testo in pagine]
    diag = _staticize(web.page_diagnostics())

    written = []
    for name, content in pagine + [("diagnostica.html", diag)]:
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

    # L'app installabile: manifesto e icone. Generati, non copiati: l'icona
    # nasce dallo stesso codice del sito (icona.py, libreria standard).
    for nome, contenuto in (("manifest.webmanifest",
                             icona.manifest(config.APP_NAME, config.APP_SHORT_NAME).encode("utf-8")),
                            ("icona-192.png", icona.png(192)),
                            ("icona-512.png", icona.png(512))):
        path = os.path.join(directory, nome)
        with open(path, "wb") as fh:
            fh.write(contenuto)
        written.append(path)

    # La foto di sfondo, se Gian l'ha messa nella cartella del progetto.
    foto = config.sfondo_path()
    if foto:
        path = os.path.join(directory, config.SFONDO_FILE)
        shutil.copyfile(foto, path)
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
