"""Gli archivi che NON si riscaricano, messi al sicuro dentro il progetto.

Fino al 19/09/2026 ogni riga del database era ricostruibile: Meteotrentino
pubblica quattordici anni, Addicted pubblica il suo storico orario, Open-Meteo
la rianalisi. Se il database fosse sparito si rifaceva, con pazienza.

Da quando leggiamo il canale vivo non e' piu' cosi'. Tre serie esistono solo
perche' le registriamo mentre passano, e nessuno le conserva al posto nostro:

  vivo     i campioni a dieci minuti delle centraline Addicted, con la
           DIREZIONE misurata. Il loro canale vivo non ha archivio: quello che
           non prendiamo adesso non esiste piu' fra un'ora.
  emesse   le curve che abbiamo pubblicato noi, ora per ora. Servono a
           verificarci contro quello che l'utente ha davvero letto.
  altrui   la previsione di Addicted con il giorno in cui l'abbiamo letta.
           Loro ripubblicano i giorni passati senza dire a che scadenza li
           avevano previsti: quel dato lo crea la nostra lettura, non la loro
           pagina.

E dove stavano? In una cache di GitHub Actions, che cancella le copie non
usate da sette giorni e ne tiene dieci giga in tutto: col database da 547 MB
riscritto a ogni esecuzione fanno circa quattro giorni di profondita'. Per
roba ricostruibile andava benissimo. Per roba irripetibile no.

Qui le stesse righe finiscono in file compressi dentro il progetto, un file
per mese: git tiene ogni versione, ogni copia scaricata e' completa, e non
scade. E' lo stesso mestiere che fa gia' storico/campione-addicted.csv.gz.

DUE REGOLE, e la prima e' quella che evita il disastro:

  NON SI RIMPICCIOLISCE MAI. Prima di scrivere si legge il file che c'e' gia'
  e si fa l'unione. Senza questa regola basterebbe una cache persa perche' la
  prima esecuzione successiva - con il database vuoto e in ricostruzione -
  scrivesse file vuoti SOPRA l'archivio buono. Il salvataggio diventerebbe il
  modo di perdere tutto, che e' il difetto peggiore che un backup possa avere.

  SI RILEGGE ALL'INDIETRO. `recupera` riporta i file dentro il database se
  quelle righe non ci sono. Cosi' il giro si chiude: cache persa, una
  esecuzione, archivio di nuovo a posto - senza che nessuno debba accorgersene
  e ripescare a mano un allegato prima che scada.
"""
import csv
import gzip
import io
import os

from . import config, store

CARTELLA = "storico"


def _percorso(sotto, nome, mese):
    return os.path.join(config.PROJECT_DIR, CARTELLA, sotto,
                        "%s-%s.csv.gz" % (nome, mese))


def _leggi(path):
    """[(riga come tupla di stringhe)] dal file, o [] se non c'e'."""
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        righe = list(csv.reader(fh))
    return righe[1:] if righe else []


def _scrivi_mese(path, intestazione, n_chiave, righe):
    """Unisce `righe` a quelle gia' nel file e riscrive. Ritorna (n, nuove).

    `n_chiave` e' quante colonne iniziali formano la chiave. A parita' di
    chiave vince la riga GIA' IN ARCHIVIO: un file scritto ieri non si fa
    correggere da un database che si sta ricostruendo.
    """
    vecchie = _leggi(path)
    unione = {}
    for r in list(righe) + vecchie:          # le vecchie dopo: vincono loro
        unione[tuple(str(x) for x in r[:n_chiave])] = [
            "" if x is None else str(x) for x in r]
    if len(unione) < len(vecchie):           # pragma: no cover - impossibile
        raise RuntimeError("l'unione ha meno righe del file: non si scrive")
    nuove = len(unione) - len(vecchie)
    if not nuove and vecchie:
        return len(vecchie), 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(intestazione)
    for k in sorted(unione):
        w.writerow(unione[k])
    with gzip.open(path, "wb") as fh:
        fh.write(buf.getvalue().encode("utf-8"))
    return len(unione), nuove


# ==========================================================================
# Le tre serie. Ognuna sa estrarsi e sa rientrare: una definizione, due versi.
# ==========================================================================

VIVO = {
    "sotto": "vivo",
    "intestazione": ("ts", "wind_kn", "gust_kn", "dir_deg"),
    "chiave": 1,
    "query": ("SELECT station, ts, wind_kn, gust_kn, dir_deg FROM obs_sample "
              "WHERE source=? ORDER BY station, ts", ("addicted-live",)),
}
EMESSE = {
    "sotto": "emesse",
    "intestazione": ("issued_at", "valid_hour", "wind_kn", "gust_kn"),
    "chiave": 2,
    "query": ("SELECT place, issued_at, valid_hour, wind_kn, gust_kn "
              "FROM issued_profile ORDER BY place, issued_at, valid_hour", ()),
}
ALTRUI = {
    "sotto": "altrui",
    "intestazione": ("letto_il", "letto_a", "valid_hour", "wind_kn",
                     "lo_kn", "hi_kn"),
    "chiave": 3,
    "query": ("SELECT station, letto_il, letto_a, valid_hour, wind_kn, lo_kn, "
              "hi_kn FROM fc_altrui ORDER BY station, letto_il, valid_hour", ()),
}
SERIE = (VIVO, EMESSE, ALTRUI)


def _mese_di(riga, serie):
    """Il mese da cui prende nome il file: la prima colonna che e' una data."""
    for v in riga[1:]:
        s = str(v or "")
        if len(s) >= 7 and s[4] == "-":
            return s[:7]
    return None


def esporta():
    """Scrive i file mensili. Ritorna [(percorso, righe, nuove)]."""
    c = store.connect()
    fatti = []
    for serie in SERIE:
        sql, args = serie["query"]
        per_file = {}
        for r in c.execute(sql, args):
            riga = list(r)
            nome, resto = riga[0], riga[1:]
            mese = _mese_di(riga, serie)
            if not mese:
                continue
            per_file.setdefault((nome, mese), []).append(resto)
        for (nome, mese), righe in sorted(per_file.items()):
            path = _percorso(serie["sotto"], nome.replace("/", "_"), mese)
            n, nuove = _scrivi_mese(path, serie["intestazione"],
                                    serie["chiave"], righe)
            fatti.append((os.path.relpath(path, config.PROJECT_DIR), n, nuove))
    return fatti


def recupera():
    """Rimette nel database quello che sta nei file e li' non c'e' piu'.

    E' la meta' che rende il salvataggio un archivio invece che una copia:
    dopo una cache persa, una sola esecuzione rimette tutto a posto.
    """
    base = os.path.join(config.PROJECT_DIR, CARTELLA)
    fatti = []
    for serie in SERIE:
        cartella = os.path.join(base, serie["sotto"])
        if not os.path.isdir(cartella):
            continue
        for f in sorted(os.listdir(cartella)):
            if not f.endswith(".csv.gz"):
                continue
            # Il nome del file e' "<stazione>-<AAAA-MM>.csv.gz", e il mese
            # contiene un trattino: tagliare all'ultimo trattino dava
            # "campione-2026". Le righe rientravano sotto una stazione
            # inventata, il recupero non recuperava niente, e la scrittura
            # successiva creava "campione-2026-2026-09.csv.gz" - un file
            # spazzatura in piu' a ogni giro. Si tolgono i DUE pezzi del mese.
            nome = f[:-len(".csv.gz")].rsplit("-", 2)[0]
            righe = _leggi(os.path.join(cartella, f))
            if not righe:
                continue
            n = _rientra(serie, nome, righe)
            if n:
                fatti.append((f, n))
    return fatti


def _rientra(serie, nome, righe):
    """Le righe del file tornano nella loro tabella. Non sovrascrive niente."""
    def num(x):
        try:
            return float(x) if x not in (None, "") else None
        except (TypeError, ValueError):
            return None

    c = store.connect()
    if serie is VIVO:
        payload = [(nome, r[0], num(r[1]), num(r[2]), num(r[3]), "addicted-live")
                   for r in righe if r and r[0]]
        sql = ("INSERT OR IGNORE INTO obs_sample"
               "(station,ts,wind_kn,gust_kn,dir_deg,source) VALUES(?,?,?,?,?,?)")
    elif serie is EMESSE:
        payload = [(nome, r[0], r[1], num(r[2]), num(r[3]))
                   for r in righe if len(r) >= 4 and r[0] and r[1]]
        sql = ("INSERT OR IGNORE INTO issued_profile"
               "(place,issued_at,valid_hour,wind_kn,gust_kn) VALUES(?,?,?,?,?)")
    else:
        payload = [("addicted-sports", nome, r[0], r[1], r[2],
                    num(r[3]), num(r[4]), num(r[5]))
                   for r in righe if len(r) >= 6 and r[0] and r[2]]
        sql = ("INSERT OR IGNORE INTO fc_altrui"
               "(fonte,station,letto_il,letto_a,valid_hour,wind_kn,lo_kn,hi_kn)"
               " VALUES(?,?,?,?,?,?,?,?)")
    if not payload:
        return 0
    prima = c.total_changes
    c.executemany(sql, payload)
    c.commit()
    return c.total_changes - prima
