"""Livello HTTP: una sola porta d'ingresso per tutte le chiamate esterne.

Include un limitatore di frequenza elementare, perche' un ciclo completo di
aggiornamento fa decine di richieste a Open-Meteo e superare la quota fa
fallire tutto in modo silenzioso e confuso.
"""

import json
import os
import subprocess
import sys
import threading
import time
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "GardaWind/3.5 (uso personale, previsione vento Alto Garda)"

# Alcuni servizi (l'archivio Hydstra di Meteotrentino) assegnano un id di
# sessione anonimo alla prima visita e lo usano per nominare i file generati:
# senza conservare i cookie il flusso non si chiude.
_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_JAR))

_RATE_LOCK = threading.Lock()
_LAST_CALL = {"t": 0.0}
MIN_INTERVAL_S = 0.35
# Attesa fra un tentativo e il successivo. Cresce, perche' la causa piu'
# frequente e' un servizio che sta rifiatando: riprovare subito lo trova
# nello stesso stato.
ATTESA_S = (1.0, 3.0)


class FetchError(RuntimeError):
    pass


def _throttle():
    with _RATE_LOCK:
        wait = MIN_INTERVAL_S - (time.time() - _LAST_CALL["t"])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL["t"] = time.time()


def _cookie_file():
    base = os.path.expanduser("~/Library/Application Support/Garda Wind")
    if not os.path.isdir(base):
        base = os.path.expanduser("~/.gardawind")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return None
    return os.path.join(base, "cookies.txt")


def _curl(url, timeout, data=None):
    cmd = ["/usr/bin/curl", "--fail-with-body", "--silent", "--show-error", "--location",
           "--connect-timeout", "12", "--max-time", str(int(timeout)),
           "--retry", "2", "--retry-delay", "2", "-A", USER_AGENT]
    # Anche il ripiego su curl deve conservare la sessione, altrimenti il
    # flusso a due passaggi dell'archivio Hydstra si interrompe.
    jar = _cookie_file()
    if jar:
        cmd += ["-b", jar, "-c", jar]
    if data is not None:
        cmd += ["--data", data]
    cmd.append(url)
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        msg = cp.stderr.decode("utf-8", "replace").strip() or cp.stdout.decode("utf-8", "replace")[:200]
        raise FetchError(msg or "curl exit %s" % cp.returncode)
    return cp.stdout


def _ritentabile(e):
    """Un errore che ritentare puo' risolvere, e uno che no.

    Il 429 e i 5xx sono il server che chiede di aspettare. Timeout, errori
    SSL e connessioni cadute sono la rete. Un 400 o un 404 invece non
    migliorano ritentando: la richiesta e' sbagliata, e ripeterla tre volte
    aggiunge solo ritardo a un errore che va letto.
    """
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or 500 <= e.code < 600
    return True


def _tentativi(timeout):
    """Quante volte provare, in funzione di quanto costa una prova.

    Tre volte sulle chiamate brevi, due su quelle lunghe. Un timeout scaduto
    si paga tutto: tre tentativi da 240 secondi sono dodici minuti di build
    per una chiamata che il piu' delle volte non tornera' comunque.
    """
    return 3 if timeout <= 90 else 2


def fetch(url, params=None, timeout=60, data=None):
    """GET (o POST se data) che ritorna bytes. Solleva FetchError su errore.

    Ritenta, e non e' una comodita': prima ritentava solo macOS, per caso.
    Il ripiego su curl in fondo a questa funzione porta `--retry 2`, quindi
    sul Mac ogni chiamata aveva tre possibilita' e su Linux una sola - e la
    differenza si e' vista nel modo peggiore. Il ciclo di aggiornamento fa
    una ventina di richieste di fila a Open-Meteo, e nel runner di GitHub
    l'ultima - le condizioni per gli analoghi - cadeva ogni volta con un
    timeout dell'handshake SSL: sul Mac la porta era aperta e la curva
    affilata c'era, sul sito pubblicato no, e la diagnostica poteva solo
    dire "handshake operation timed out" a chi sapeva dove guardare.

    Quanto e' robusta un'applicazione non lo decide il sistema operativo su
    cui gira.
    """
    full = url
    if params:
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    prove = _tentativi(timeout)
    ultimo = None
    for prova in range(prove):
        _throttle()
        try:
            req = urllib.request.Request(full, data=body,
                                         headers={"User-Agent": USER_AGENT})
            with _OPENER.open(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            ultimo = FetchError("HTTP %s %s" % (e.code, detail or e.reason))
            if not _ritentabile(e):
                raise ultimo
        except Exception as e:
            ultimo = FetchError(str(e))
        if prova + 1 < prove:
            time.sleep(ATTESA_S[min(prova, len(ATTESA_S) - 1)])

    # Ultima carta, solo su macOS: il Python di sistema ha, su alcune
    # versioni, un bundle di certificati incompleto, e curl usa il keychain.
    if sys.platform == "darwin" and os.path.exists("/usr/bin/curl"):
        try:
            return _curl(full, timeout, body.decode() if body else None)
        except FetchError:
            raise
        except Exception as e2:
            raise FetchError(str(e2))
    raise ultimo or FetchError("nessuna risposta")


def fetch_json(url, params=None, timeout=60):
    raw = fetch(url, params, timeout)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise FetchError("risposta non JSON: %s" % e)
    if isinstance(data, dict) and data.get("error"):
        raise FetchError(str(data.get("reason", "errore API"))[:250])
    return data


def fetch_text(url, params=None, timeout=60, data=None, encoding="utf-8"):
    return fetch(url, params, timeout, data).decode(encoding, "replace")
