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


def fetch(url, params=None, timeout=60, data=None):
    """GET (o POST se data) che ritorna bytes. Solleva FetchError su errore."""
    _throttle()
    full = url
    if params:
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    try:
        req = urllib.request.Request(full, data=body, headers={"User-Agent": USER_AGENT})
        with _OPENER.open(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise FetchError("HTTP %s %s" % (e.code, detail or e.reason))
    except Exception as e:
        # Il Python di sistema di macOS ha, su alcune versioni, un bundle di
        # certificati incompleto: curl usa il keychain e funziona comunque.
        if sys.platform == "darwin" and os.path.exists("/usr/bin/curl"):
            try:
                return _curl(full, timeout, body.decode() if body else None)
            except FetchError:
                raise
            except Exception as e2:
                raise FetchError(str(e2))
        raise FetchError(str(e))


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
