"""Utilita' di base: tempo, angoli, statistica, algebra lineare, modelli lineari.

Nessuna dipendenza esterna: gira sul Python di sistema di macOS (3.9+).
"""

import math
import re
import statistics
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ_ROME = ZoneInfo("Europe/Rome")
except Exception:                                    # pragma: no cover
    _TZ_ROME = None

UTC = timezone.utc


# ==========================================================================
# Tempo
# ==========================================================================

def _rome_offset_fallback(dt_utc):
    """Offset di Europe/Rome senza tzdata: regola UE (ultima dom. marzo/ottobre)."""
    y = dt_utc.year

    def last_sunday(year, month):
        d = datetime(year, month, 31, tzinfo=UTC) if month != 4 else datetime(year, 4, 30, tzinfo=UTC)
        while d.weekday() != 6:
            d -= timedelta(days=1)
        return d.replace(hour=1)                      # 01:00 UTC

    start = last_sunday(y, 3)
    end = last_sunday(y, 10)
    return timedelta(hours=2) if start <= dt_utc < end else timedelta(hours=1)


def to_local(dt_utc):
    """Da datetime aware UTC a datetime aware ora locale italiana."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    if _TZ_ROME is not None:
        return dt_utc.astimezone(_TZ_ROME)
    return (dt_utc + _rome_offset_fallback(dt_utc)).replace(tzinfo=UTC)


def local_day(dt_utc):
    """Giorno locale (stringa YYYY-MM-DD) a cui appartiene un istante UTC."""
    return to_local(dt_utc).strftime("%Y-%m-%d")


def local_hour(dt_utc):
    return to_local(dt_utc).hour


def local_minute_of_day(dt_utc):
    """Minuti dalla mezzanotte locale, con i minuti dentro.

    local_hour qui sopra i minuti li butta, ed e' giusto che li butti: serve a
    indicizzare le ORE, e un'ora e' un numero intero. Ma chi disegna i
    campioni veri ha bisogno di sapere DOVE nell'ora sono arrivati, e
    riusando local_hour li metteva tutti sullo stesso punto: sei campioni di
    un'ora finivano alla stessa ascissa con sei valori diversi, e la curva fra
    loro diventava un salto verticale. Sono i gradini che si vedevano nel
    grafico - "un gran casino" - insieme al mescolamento delle fonti.

    Due funzioni e non una perche' sono due domande diverse: "in quale ora
    siamo" e "a che minuto siamo". Una sola funzione che rispondesse a
    entrambe le avrebbe confuse un'altra volta.
    """
    t = to_local(dt_utc)
    return t.hour * 60.0 + t.minute + t.second / 60.0


def utc_now():
    return datetime.now(UTC).replace(microsecond=0)


def iso_utc(dt):
    """Chiave testuale ordinabile, sempre UTC, al minuto."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_hour_utc(dt):
    """Chiave oraria UTC (troncata all'ora)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


def parse_iso_utc(s):
    """Parsa una chiave prodotta da iso_utc/iso_hour_utc."""
    if not s:
        return None
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


_OFFSET_RE = re.compile(r"([+-])(\d{2})(?::?(\d{2}))?$")


def parse_dt_any(s, assume_offset_hours=None):
    """Parser tollerante che restituisce SEMPRE un datetime aware in UTC.

    Gestisce i casi reali incontrati:
      - '2026-09-13T10:15:00+01'   (Meteotrentino: offset a due cifre, che il
        fromisoformat di Python 3.9 rifiuta)
      - '2026-09-13T10:15:00+01:00'
      - '2026-09-13 10:15:00'      (naive -> usa assume_offset_hours)
      - '13/09/2026 10:15'
      - '13/09/26 10.15'
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")

    offset = None
    m = _OFFSET_RE.search(s)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        hh = int(m.group(2))
        mm = int(m.group(3) or 0)
        offset = timedelta(hours=sign * hh, minutes=sign * mm)
        s = s[:m.start()]
    s = s.strip().replace("T", " ")

    naive = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H.%M",
                "%d/%m/%y %H:%M", "%d/%m/%y %H.%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if naive is None:
        return None

    if offset is None:
        if assume_offset_hours is None:
            return naive.replace(tzinfo=UTC)          # trattato come UTC
        offset = timedelta(hours=assume_offset_hours)
    return (naive - offset).replace(tzinfo=UTC)


def local_naive_to_utc(dt_naive, fold=0):
    """Interpreta un datetime senza fuso come ora civile italiana e lo porta in UTC.

    Serve per le sorgenti che pubblicano l'orologio da parete (le centraline
    private lo fanno quasi sempre), a differenza di Meteotrentino che pubblica
    un offset esplicito.
    """
    if dt_naive is None:
        return None
    if dt_naive.tzinfo is not None:
        return dt_naive.astimezone(UTC)
    if _TZ_ROME is not None:
        return dt_naive.replace(tzinfo=_TZ_ROME, fold=fold).astimezone(UTC)
    guess = dt_naive.replace(tzinfo=UTC)
    return (guess - _rome_offset_fallback(guess)).replace(tzinfo=UTC)


def serie_locale_to_utc(naives):
    """Una SERIE di orologi da parete -> istanti UTC, senza perdere l'ora doppia.

    L'ultima domenica di ottobre le 02:00-02:59 italiane esistono due volte, e
    le fonti che pubblicano l'orologio da parete - la Fraglia, Addicted - le
    scrivono due volte uguali. Convertendole una per una con `fold=0` le due
    coppie finiscono sullo stesso istante UTC, e siccome i campioni si salvano
    con INSERT OR REPLACE la seconda cancella la prima: un'ora di misure persa
    e un'ora di UTC che nessuna chiave produce piu'. Il 25 ottobre 2026.

    Qui la serie si legge in ordine: quando un istante non avanza rispetto al
    precedente vuol dire che siamo tornati indietro, e da li' in poi - fino a
    che la sequenza non e' di nuovo crescente - si usa il secondo passaggio.
    Non e' un indovinello: e' l'unica informazione che la fonte ci da', cioe'
    l'ordine in cui ha scritto le righe.
    """
    out, ultimo, dentro = [], None, False
    for n in naives:
        if n is None:
            out.append(None)
            continue
        t = local_naive_to_utc(n, fold=1 if dentro else 0)
        if ultimo is not None and t is not None and t <= ultimo and not dentro:
            dentro = True
            t = local_naive_to_utc(n, fold=1)
        if ultimo is not None and t is not None and t > ultimo and dentro:
            # usciti dall'ora doppia: da qui l'orologio e' di nuovo unico
            senza = local_naive_to_utc(n, fold=0)
            if senza is not None and senza > ultimo:
                dentro, t = False, senza
        if t is not None:
            ultimo = t
        out.append(t)
    return out


def day_range(start_day, end_day):
    """Lista di stringhe YYYY-MM-DD inclusive."""
    d0 = datetime.strptime(start_day, "%Y-%m-%d")
    d1 = datetime.strptime(end_day, "%Y-%m-%d")
    out = []
    while d0 <= d1:
        out.append(d0.strftime("%Y-%m-%d"))
        d0 += timedelta(days=1)
    return out


def day_shift(day, n):
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def day_of_year(day):
    return datetime.strptime(day, "%Y-%m-%d").timetuple().tm_yday


# ==========================================================================
# Numeri e angoli
# ==========================================================================

KN_PER_MS = 1.9438445
KN_PER_KMH = 1.0 / 1.852


def num(v, default=None):
    """Converte in float tollerando stringhe vuote, virgole decimali, None."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return default if isinstance(v, float) and math.isnan(v) else float(v)
    s = str(v).strip().replace(",", ".")
    if s in ("", "-", "--", "nan", "NaN", "None", "null", "n.d."):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def mean(xs, default=None):
    z = [x for x in xs if x is not None]
    return sum(z) / len(z) if z else default


def pstdev(xs, default=0.0):
    z = [x for x in xs if x is not None]
    if len(z) < 2:
        return default
    return statistics.pstdev(z)


def median(xs, default=None):
    z = sorted(x for x in xs if x is not None)
    return statistics.median(z) if z else default


def quantile(xs, q):
    """Quantile lineare su lista gia' filtrata da None."""
    z = sorted(x for x in xs if x is not None)
    if not z:
        return None
    if len(z) == 1:
        return z[0]
    pos = q * (len(z) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(z) - 1)
    frac = pos - lo
    return z[lo] * (1 - frac) + z[hi] * frac


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-clamp(x, -35.0, 35.0)))


def angle_diff(a, b):
    """Differenza angolare minima fra due direzioni, in gradi (0..180)."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def wind_components(speed, direction_from):
    """Da (velocita', direzione di PROVENIENZA) a componenti (u east, v north)."""
    if speed is None or direction_from is None:
        return None, None
    rad = math.radians(direction_from)
    return -speed * math.sin(rad), -speed * math.cos(rad)


def along_axis(speed, direction_from, axis_from):
    """Componente del vento lungo l'asse, positiva se soffia NELLO stesso verso.

    axis_from e' la direzione di provenienza "ideale" del regime. Il risultato
    e' +speed se il vento viene esattamente da li', -speed se viene dall'opposto.
    E' la grandezza fisicamente rilevante: un gradiente contrario spegne la
    brezza, uno concorde la rinforza. Il punteggio angolare simmetrico usato
    di solito non distingue i due casi.
    """
    if speed is None or direction_from is None:
        return None
    return speed * math.cos(math.radians(direction_from - axis_from))


def cross_axis(speed, direction_from, axis_from):
    if speed is None or direction_from is None:
        return None
    return abs(speed * math.sin(math.radians(direction_from - axis_from)))


def circular_median(directions, step=1.0):
    """Direzione che minimizza la somma degli scarti angolari.

    La mediana ordinaria non esiste su un cerchio: 350 e 10 gradi hanno mediana
    180, che e' la direzione opposta a entrambi. Qui si cerca per forza bruta
    l'angolo che minimizza la somma delle distanze angolari, che e' la
    definizione corretta e non ha il problema del taglio a zero.
    """
    ds = [d % 360.0 for d in directions if d is not None]
    if not ds:
        return None
    best = None
    x = 0.0
    while x < 360.0:
        tot = 0.0
        for d in ds:
            tot += angle_diff(d, x)
        if best is None or tot < best[0]:
            best = (tot, x)
        x += step
    return best[1]


def circular_mean(directions):
    """Media vettoriale non pesata e concentrazione R in [0,1]."""
    ds = [d % 360.0 for d in directions if d is not None]
    if not ds:
        return None, 0.0
    su = sum(math.sin(math.radians(d)) for d in ds) / len(ds)
    cu = sum(math.cos(math.radians(d)) for d in ds) / len(ds)
    return math.degrees(math.atan2(su, cu)) % 360.0, math.hypot(su, cu)


def circular_modes(directions, bin_deg=10.0, smooth=1, min_share=0.35):
    """Mode della distribuzione circolare, con il ventre fra le due.

    Ritorna [(centro, conteggio), ...] ordinate per conteggio, piu' il rapporto
    fra il ventre piu' basso e la moda secondaria. Un rapporto basso significa
    che le due mode sono davvero separate e non due gobbe dello stesso mucchio:
    e' il modo piu' semplice di rispondere a "e' bimodale?" senza ricorrere a
    test che su un campione cosi' direbbero comunque di si'.
    """
    nb = int(round(360.0 / bin_deg))
    counts = [0] * nb
    for d in directions:
        if d is None:
            continue
        counts[int((d % 360.0) // bin_deg) % nb] += 1
    if sum(counts) == 0:
        return [], None
    # Media mobile circolare: toglie i denti senza spostare le mode.
    sm = list(counts)
    for _ in range(max(0, smooth)):
        sm = [(sm[(i - 1) % nb] + sm[i] + sm[(i + 1) % nb]) / 3.0 for i in range(nb)]
    top = max(sm)
    peaks = [i for i in range(nb)
             if sm[i] >= sm[(i - 1) % nb] and sm[i] >= sm[(i + 1) % nb]
             and sm[i] >= min_share * top]
    # Fonde i picchi adiacenti.
    merged = []
    for i in peaks:
        if merged and (i - merged[-1][-1]) % nb <= 1:
            merged[-1].append(i)
        else:
            merged.append([i])
    if len(merged) > 1 and (merged[0][0] - merged[-1][-1]) % nb <= 1:
        merged[0] = merged[-1] + merged[0]
        merged.pop()
    modes = []
    for grp in merged:
        centre = max(grp, key=lambda i: sm[i])
        modes.append((centre * bin_deg + bin_deg / 2.0,
                      sum(counts[i] for i in grp)))
    modes.sort(key=lambda m: -m[1])

    dip = None
    if len(modes) >= 2:
        a = int((modes[0][0] - bin_deg / 2.0) // bin_deg)
        b = int((modes[1][0] - bin_deg / 2.0) // bin_deg)
        # Il ventre lungo il tratto PIU' CORTO fra le due mode. Prendere il
        # minimo fra i due versi sarebbe sbagliato: il verso lungo attraversa
        # il mezzo cerchio vuoto, dove il conteggio e' zero, e allora qualunque
        # coppia di mode risulterebbe "ben separata". La domanda e' se c'e' un
        # avvallamento FRA le due, non se esiste il vuoto da qualche altra parte.
        def walk(i, j):
            vals, k = [], i
            while k != j:
                k = (k + 1) % nb
                vals.append(sm[k])
            return vals
        avanti, indietro = walk(a, b), walk(b, a)
        corto = avanti if len(avanti) <= len(indietro) else indietro
        second = sm[b]
        dip = (min(corto) / second) if (corto and second) else None
    return modes, dip


def vector_mean_direction(pairs):
    """Media vettoriale di direzioni pesata per velocita'.

    pairs: iterabile di (speed, direction_from). Ritorna (dir_media, costanza)
    dove costanza in [0,1] dice quanto il vento e' stato direzionalmente stabile.
    """
    su = sv = ssp = 0.0
    n = 0
    for sp, d in pairs:
        if sp is None or d is None:
            continue
        u, v = wind_components(sp, d)
        su += u
        sv += v
        ssp += sp
        n += 1
    if n == 0 or ssp == 0:
        return None, 0.0
    mag = math.hypot(su, sv)
    direction = (math.degrees(math.atan2(-su, -sv))) % 360.0
    return direction, clamp(mag / ssp, 0.0, 1.0)


# ==========================================================================
# Algebra lineare
# ==========================================================================

def solve_spd(A, b, ridge=0.0):
    """Risolve A x = b con eliminazione di Gauss e pivot parziale.

    Ritorna None se la matrice e' numericamente singolare: il chiamante deve
    gestirlo (tipicamente aumentando la regolarizzazione) invece di restituire
    coefficienti spazzatura.
    """
    n = len(b)
    M = [[float(A[i][j]) + (ridge if i == j else 0.0) for j in range(n)] + [float(b[i])]
         for i in range(n)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            return None
        M[i], M[piv] = M[piv], M[i]
        d = M[i][i]
        M[i] = [x / d for x in M[i]]
        for r in range(n):
            if r == i:
                continue
            f = M[r][i]
            if f != 0.0:
                M[r] = [M[r][j] - f * M[i][j] for j in range(n + 1)]
    return [M[i][n] for i in range(n)]


class Standardizer:
    """Centra e scala le colonne; le colonne costanti vengono neutralizzate."""

    def __init__(self, X):
        p = len(X[0])
        self.mean = [mean([r[j] for r in X], 0.0) for j in range(p)]
        self.sd = []
        for j in range(p):
            s = pstdev([r[j] for r in X], 0.0)
            self.sd.append(s if s > 1e-9 else 1.0)
        self.constant = [pstdev([r[j] for r in X], 0.0) <= 1e-9 for j in range(p)]

    def apply(self, row):
        return [0.0 if self.constant[j] else (row[j] - self.mean[j]) / self.sd[j]
                for j in range(len(row))]

    def apply_all(self, X):
        return [self.apply(r) for r in X]


# ==========================================================================
# Regressione ridge
# ==========================================================================

class RidgeModel:
    """Ridge con intercetta, addestrata su feature standardizzate.

    I coefficienti vengono riportati alla scala originale, cosi' che
    predict() lavori direttamente sul vettore di feature grezzo.
    """

    def __init__(self, intercept, coef, feature_names=None, lam=None):
        self.intercept = intercept
        self.coef = coef
        self.feature_names = feature_names or []
        self.lam = lam

    def predict(self, row):
        return self.intercept + sum(c * x for c, x in zip(self.coef, row))

    def to_dict(self):
        return {"intercept": self.intercept, "coef": self.coef,
                "features": self.feature_names, "lam": self.lam}

    @staticmethod
    def from_dict(d):
        return RidgeModel(d["intercept"], d["coef"], d.get("features"), d.get("lam"))


def ridge_fit(X, y, lam=1.0, feature_names=None):
    """Adatta una ridge. Ritorna None se il sistema resta singolare."""
    if not X or len(X) != len(y):
        return None
    p = len(X[0])
    std = Standardizer(X)
    Z = std.apply_all(X)
    ym = mean(y, 0.0)
    yc = [v - ym for v in y]

    A = [[sum(r[i] * r[j] for r in Z) for j in range(p)] for i in range(p)]
    b = [sum(r[i] * v for r, v in zip(Z, yc)) for i in range(p)]

    bz = None
    for extra in (lam, lam * 10, lam * 100, lam * 1000):
        bz = solve_spd(A, b, ridge=extra)
        if bz is not None:
            break
    if bz is None:
        return None

    coef = [0.0 if std.constant[j] else bz[j] / std.sd[j] for j in range(p)]
    intercept = ym - sum(coef[j] * std.mean[j] for j in range(p) if not std.constant[j])
    return RidgeModel(intercept, coef, feature_names, lam)


# ==========================================================================
# Regressione logistica (IRLS con penalizzazione L2)
# ==========================================================================

class LogisticModel:
    def __init__(self, intercept, coef, feature_names=None, lam=None):
        self.intercept = intercept
        self.coef = coef
        self.feature_names = feature_names or []
        self.lam = lam

    def predict_proba(self, row):
        return sigmoid(self.intercept + sum(c * x for c, x in zip(self.coef, row)))

    def to_dict(self):
        return {"intercept": self.intercept, "coef": self.coef,
                "features": self.feature_names, "lam": self.lam}

    @staticmethod
    def from_dict(d):
        return LogisticModel(d["intercept"], d["coef"], d.get("features"), d.get("lam"))


def logistic_fit(X, y, lam=1.0, feature_names=None, max_iter=60):
    """IRLS con ridge sulle feature standardizzate.

    y deve essere 0/1. Se una classe e' assente o l'IRLS diverge, ritorna None:
    meglio nessun modello che un modello che allucina certezze.
    """
    if not X or len(X) != len(y):
        return None
    pos = sum(1 for v in y if v > 0.5)
    if pos == 0 or pos == len(y):
        return None

    p = len(X[0])
    std = Standardizer(X)
    Z = std.apply_all(X)
    n = len(Z)

    base = math.log(pos / (n - pos))
    beta = [0.0] * p
    b0 = base

    for _ in range(max_iter):
        eta = [b0 + sum(beta[j] * Z[i][j] for j in range(p)) for i in range(n)]
        mu = [sigmoid(e) for e in eta]
        w = [max(mu_i * (1 - mu_i), 1e-6) for mu_i in mu]
        # variabile di lavoro
        z = [eta[i] + (y[i] - mu[i]) / w[i] for i in range(n)]

        # matrice aumentata con colonna di intercetta
        cols = p + 1
        A = [[0.0] * cols for _ in range(cols)]
        rhs = [0.0] * cols
        for i in range(n):
            xi = [1.0] + Z[i]
            wi = w[i]
            zi = z[i]
            for a in range(cols):
                xa = xi[a] * wi
                rhs[a] += xa * zi
                for bcol in range(a, cols):
                    A[a][bcol] += xa * xi[bcol]
        for a in range(cols):
            for bcol in range(a):
                A[a][bcol] = A[bcol][a]
        for j in range(1, cols):          # nessuna penalita' sull'intercetta
            A[j][j] += lam

        sol = None
        for extra in (0.0, lam, lam * 10, lam * 100):
            sol = solve_spd(A, rhs, ridge=extra)
            if sol is not None:
                break
        if sol is None:
            return None

        new_b0, new_beta = sol[0], sol[1:]
        if any(not math.isfinite(v) for v in sol):
            return None
        delta = abs(new_b0 - b0) + sum(abs(a - b) for a, b in zip(new_beta, beta))
        b0, beta = new_b0, new_beta
        if delta < 1e-7:
            break

    coef = [0.0 if std.constant[j] else beta[j] / std.sd[j] for j in range(p)]
    intercept = b0 - sum(coef[j] * std.mean[j] for j in range(p) if not std.constant[j])
    if not math.isfinite(intercept) or any(not math.isfinite(c) for c in coef):
        return None
    return LogisticModel(intercept, coef, feature_names, lam)


# ==========================================================================
# Cross-validation a blocchi
# ==========================================================================

def block_folds(groups, k=5):
    """Divide in k fold tenendo insieme i campioni dello stesso gruppo.

    I gruppi (tipicamente il giorno) sono assegnati a blocchi CONTIGUI nel
    tempo, non a caso: ore dello stesso giorno e giorni consecutivi sono
    fortemente correlati, e una CV casuale gonfierebbe il punteggio.
    """
    uniq = sorted(set(groups))
    if len(uniq) < k:
        k = max(2, len(uniq))
    size = len(uniq) / float(k)
    assign = {}
    for idx, g in enumerate(uniq):
        assign[g] = min(int(idx / size), k - 1)
    folds = [[] for _ in range(k)]
    for i, g in enumerate(groups):
        folds[assign[g]].append(i)
    return [f for f in folds if f]


def forward_folds_idx(groups, k=5, min_train_frac=0.40):
    """Come block_folds, ma SOLO in avanti nel tempo: [(indici_train, indici_test)].

    block_folds tiene insieme i giorni, e questo evita che ore dello stesso
    giorno finiscano di qua e di la'. Ma non impedisce la cosa piu' grave:
    predire il 2019 con un modello addestrato anche sul 2023. Una previsione
    del tempo si usa in un verso solo, e va misurata in quel verso, altrimenti
    il punteggio descrive un esercizio che nessuno potra' ripetere.

    Il primo blocco di giorni serve solo ad addestrare: non viene mai predetto.
    E' il prezzo del metodo corretto, e si paga in campioni, non in onesta'.
    """
    days = sorted(set(groups))
    n = len(days)
    if n < 8:
        return []
    start = max(int(n * min_train_frac), min(4, n - 2))
    if n - start < k:
        k = max(1, n - start)
    size = max(1, (n - start) // max(1, k))
    by_day = {}
    for i, g in enumerate(groups):
        by_day.setdefault(g, []).append(i)
    out = []
    pos = start
    while pos < n and len(out) < k:
        stop = min(n, pos + size)
        tr = [i for d in days[:pos] for i in by_day[d]]
        te = [i for d in days[pos:stop] for i in by_day[d]]
        if tr and te:
            out.append((tr, te))
        pos = stop
    return out


def cv_predict(X, y, groups, fit_fn, predict_fn, k=5):
    """Predizioni out-of-fold. Ritorna (preds, n_valid) con None dove il fit fallisce."""
    preds = [None] * len(y)
    folds = block_folds(groups, k)
    if len(folds) < 2:
        return preds, 0
    ok = 0
    for f in folds:
        test = set(f)
        tr_idx = [i for i in range(len(y)) if i not in test]
        if len(tr_idx) < 8:
            continue
        model = fit_fn([X[i] for i in tr_idx], [y[i] for i in tr_idx])
        if model is None:
            continue
        for i in f:
            preds[i] = predict_fn(model, X[i])
            ok += 1
    return preds, ok


# ==========================================================================
# Metriche
# ==========================================================================

def regression_metrics(pred, obs):
    pairs = [(p, o) for p, o in zip(pred, obs) if p is not None and o is not None]
    if len(pairs) < 3:
        return None
    errs = [p - o for p, o in pairs]
    ys = [o for _, o in pairs]
    ym = mean(ys, 0.0)
    sst = sum((o - ym) ** 2 for o in ys)
    ssr = sum(e * e for e in errs)
    return {
        "n": len(pairs),
        "mae": mean([abs(e) for e in errs]),
        "bias": mean(errs),
        "rmse": math.sqrt(ssr / len(pairs)),
        "r2": (1 - ssr / sst) if sst > 0 else 0.0,
        "resid": errs,
    }


def brier(pred, obs):
    pairs = [(p, o) for p, o in zip(pred, obs) if p is not None and o is not None]
    if not pairs:
        return None
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def reliability_table(pred, obs, bins=5):
    """Tabella di affidabilita': in ogni bucket, probabilita' dichiarata vs osservata."""
    pairs = [(p, o) for p, o in zip(pred, obs) if p is not None and o is not None]
    if not pairs:
        return []
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        if not sel:
            continue
        out.append({
            "lo": lo, "hi": hi, "n": len(sel),
            "declared": mean([p for p, _ in sel]),
            "observed": mean([o for _, o in sel]),
        })
    return out


def interval_coverage(lo_list, hi_list, obs):
    """Frazione di osservazioni cadute dentro la banda dichiarata."""
    n = hit = 0
    for lo, hi, o in zip(lo_list, hi_list, obs):
        if lo is None or hi is None or o is None:
            continue
        n += 1
        if lo <= o <= hi:
            hit += 1
    return (hit / n, n) if n else (None, 0)


# --------------------------------------------------------------------------
# Livelli di raffica, e il tempo misurato in minuti
# --------------------------------------------------------------------------
# Con il wing non si plana sul vento medio, e non si plana nemmeno sulla
# raffica di punta: un colpo isolato a 25 nodi dentro una media di 8 non e' una
# sessione, e' una tavola che si ferma. Quello che fa la sessione e' un livello
# di raffica che TORNA.
#
# La definizione deve essere causale: "la mediana delle raffiche nelle ore
# migliori" non lo e', perche' scegliere le ore migliori e' una selezione fatta
# a giornata finita e infilerebbe uno sguardo sul futuro dentro il bersaglio.
# Una finestra mobile e' funzione solo di quello che sta dentro la finestra.
#
# E la finestra NON si allarga da sola. Una versione precedente, trovando una
# centralina che campiona ogni mezz'ora, portava la finestra da 30 a 90 minuti
# per farci stare tre campioni - e continuava a chiamare il risultato "raffica
# ricorrente". Ma "il livello che si ripete su mezz'ora" e "su novanta minuti"
# non sono la stessa grandezza fisica: tenere lo stesso nome fa sembrare due
# centraline confrontabili quando non lo sono, ed e' il modo piu' silenzioso di
# mettere insieme mele e pere. La finestra e' un parametro dichiarato: dove la
# cadenza non permette di stimare la ricorrente a 30 minuti, la risposta e'
# "non stimabile", non un numero che misura un'altra cosa.


def sampling_cadence(times, max_gap_min=180.0):
    """Cadenza tipica di una serie: mediana degli intervalli fra campioni.

    Gli intervalli piu' larghi di max_gap_min sono buchi, non cadenza, e non
    entrano nella mediana: una notte senza dati non deve far credere che la
    centralina campioni ogni otto ore.
    """
    t = sorted(float(x) for x in times if x is not None)
    gaps = [b - a for a, b in zip(t, t[1:]) if 0 < b - a <= max_gap_min]
    return median(gaps) if gaps else None


def window_estimable(cadence_min, window_min=30.0, min_samples=3):
    """La finestra chiesta e' stimabile a questa cadenza?

    Una mediana vuole almeno tre valori per poter scartare un estremo. In una
    finestra di w minuti, a cadenza c, ci stanno circa floor(w/c)+1 campioni:
    quindi servono c <= w/2 per averne tre. A 30 minuti di finestra, una
    centralina a 10 o 15 minuti va bene, una a 30 no.

    Questa e' la funzione che decide se una centralina puo' avere la raffica
    ricorrente a 30 minuti. Se dice no, la risposta e' "non stimabile": non si
    cambia la finestra tenendo il nome.
    """
    if not cadence_min or cadence_min <= 0:
        return False
    return int(window_min // cadence_min) + 1 >= min_samples


# Quando una serie di campioni e' abbastanza per essere una CURVA. Non un
# numero di campioni: un ARCO DI TEMPO.
#
# Un conto fisso vuol dire soglie diverse per centraline diverse. La regola
# precedente - "almeno dodici campioni" - sono due ore a Torbole, che misura
# ogni dieci minuti, e mezza giornata a Campione, che pubblica una volta
# all'ora: percio' a Campione e a Malcesine la curva del misurato non si
# aggiornava mai prima delle sedici, e per il Peler mai. Visto in pagina da
# Gian: "per torbole funziona ma per campione e malcesine non si aggiorna".
#
# E' la stessa famiglia della finestra della raffica e della soglia di
# "non recente": una costante tarata su una centralina e applicata a tutte.
# 110 minuti sono esattamente l'arco che coprivano dodici campioni da dieci
# minuti, quindi per Torbole non cambia niente.
CURVA_MIN_PUNTI = 3
CURVA_MIN_ARCO_MIN = 110.0


def serie_disegnabile(minuti, min_punti=CURVA_MIN_PUNTI,
                      arco_min=CURVA_MIN_ARCO_MIN):
    """Questi istanti (minuti dalla mezzanotte) coprono abbastanza giornata
    da disegnarci una curva sopra?"""
    z = [m for m in minuti if m is not None]
    if len(z) < min_punti:
        return False
    return (max(z) - min(z)) >= arco_min


def covered_minutes(times, cadence_min=None, max_gap_min=None):
    """Minuti effettivamente coperti da una serie di campioni.

    Un campione copre l'intervallo che lo precede: la raffica pubblicata alle
    12:20 e' il massimo fra le 12:10 e le 12:20. La copertura e' quindi la
    somma di quegli intervalli, con i buchi esclusi invece di contati.
    """
    t = sorted(float(x) for x in times if x is not None)
    if not t:
        return 0.0
    if cadence_min is None:
        cadence_min = sampling_cadence(t) or 0.0
    if max_gap_min is None:
        max_gap_min = max(15.0, 2.5 * cadence_min) if cadence_min else 60.0
    total = cadence_min          # il primo campione copre la sua cadenza
    for a, b in zip(t, t[1:]):
        d = b - a
        total += d if d <= max_gap_min else cadence_min
    return total


def gust_level(samples, window_min, centered=True, cadence_min=None,
               min_cover_frac=0.6, min_samples=3):
    """Mediana mobile delle raffiche su una finestra DICHIARATA.

    window_min e' obbligatorio e non viene mai modificato: e' il nome della
    grandezza. Chi la chiama sa quale finestra ha chiesto, e deve stampare quel
    numero accanto ai risultati.

    samples: [(minuti, raffica)] in ordine di tempo. Ritorna [(minuti, valore)]
    con valore None dove la finestra non e' coperta abbastanza - un buco nei
    dati non e' una raffica bassa, ed e' meglio dirlo che riempirlo. La
    validita' si giudica sulla COPERTURA TEMPORALE e su un minimo di campioni,
    non su un conteggio tarato su una cadenza particolare.

    La finestra centrata guarda oltre l'istante e va bene per il BERSAGLIO, che
    e' storia osservata. Per il dato in diretta serve la finestra all'indietro
    (centered=False): centrata, gli ultimi minuti non sarebbero calcolabili, e
    nel frattempo mostrerebbe un valore costruito con campioni che al momento
    della previsione non esistevano.
    """
    pts = [(float(t), float(v)) for t, v in samples if v is not None]
    pts.sort()
    if not pts:
        return []
    if cadence_min is None:
        cadence_min = sampling_cadence([t for t, _v in pts]) or 0.0
    w = float(window_min)
    need = min_cover_frac * w
    out = []
    half = w / 2.0
    # Due indici che avanzano, non una scansione per ogni punto: la versione
    # ingenua e' O(n^2) e su Torbole - centoquarantamila campioni dal 2012 -
    # l'aggregazione non finiva piu'.
    i = j = 0
    n = len(pts)
    for k in range(n):
        t = pts[k][0]
        lo = (t - half) if centered else (t - w)
        hi = (t + half) if centered else t
        while i < n and pts[i][0] < lo - 1e-9:
            i += 1
        if j < i:
            j = i
        while j < n and pts[j][0] <= hi + 1e-9:
            j += 1
        fetta = pts[i:j]
        if (len(fetta) >= min_samples and covered_minutes(
                [x for x, _v in fetta], cadence_min) >= need - 1e-9):
            out.append((t, median([v for _x, v in fetta])))
        else:
            out.append((t, None))
    return out


# La finestra canonica della raffica ricorrente. E' una scelta di prodotto -
# mezz'ora e' il tempo in cui si decide se scendere in acqua - e sta scritta
# qui una volta sola, non sparsa nei chiamanti.
FINESTRA_RICORRENTE_MIN = 30.0


def recurrent_gust(samples, centered=True, cadence_min=None):
    """Raffica ricorrente: il livello che si ripete su TRENTA minuti.

    Finestra fissa. A cadenze troppo rade esce None su tutto, e va riportato
    come "non stimabile a questa cadenza" (window_estimable lo dice in
    anticipo). Per un livello sostenuto su una finestra piu' larga si chiama
    gust_level con la sua finestra e si usa un altro nome: e' un'altra
    grandezza.
    """
    return gust_level(samples, FINESTRA_RICORRENTE_MIN, centered=centered,
                      cadence_min=cadence_min)


def time_above(series, threshold, cadence_min=None, max_gap_min=None):
    """Minuti in cui la serie sta sopra soglia, dai tempi veri.

    Non "quanti campioni sopra soglia per dieci": con campioni ogni mezz'ora
    quella moltiplicazione sbaglia di tre volte. Ogni campione vale
    l'intervallo che lo precede, i buchi valgono una cadenza e non la loro
    intera larghezza.
    """
    pts = [(float(t), v) for t, v in series if v is not None]
    pts.sort()
    if not pts:
        return 0.0
    if cadence_min is None:
        cadence_min = sampling_cadence([t for t, _v in pts]) or 0.0
    if max_gap_min is None:
        max_gap_min = max(15.0, 2.5 * cadence_min) if cadence_min else 60.0
    total = 0.0
    prev_t = None
    for t, v in pts:
        if v >= threshold:
            if prev_t is None:
                total += cadence_min
            else:
                d = t - prev_t
                total += d if d <= max_gap_min else cadence_min
        prev_t = t
    return total


def sustained_onset(series, threshold, persist_min, max_gap_min=None,
                    cadence_min=None):
    """Primo istante in cui la serie sta sopra soglia e CI RESTA.

    `persist_min` non ha un valore di default, e non e' una dimenticanza: era
    30.0, e un default e' una definizione. Questa e' logica pura e non conosce
    la configurazione, quindi la mezz'ora deve arrivarle da fuori - da
    orari.PERSISTENZA_MIN, che e' l'unico posto dove quel numero e' deciso.
    Con il default, un chiamante distratto misurava trenta minuti senza
    saperlo, e il giorno che la persistenza cambiasse in orari.py lui avrebbe
    continuato a misurare trenta.

    Il "ci resta" e' il punto: il primo superamento puntuale lo produce
    qualunque colpo di vento, e non risponde alla domanda vera, che e' da che
    ora posso entrare in acqua e planare con continuita'.

    Un campione COPRE un intervallo, non un istante, quindi due campioni
    consecutivi sopra soglia coprono due cadenze di orologio e la durata si
    misura sulla copertura. Contando la sola differenza fra i timestamp,
    "trenta minuti" avrebbe significato in silenzio quaranta.

    max_gap_min, se non passato, viene dalla cadenza e non da una costante:
    con 15 minuti fissi, a Malcesine (campioni ogni mezz'ora) OGNI intervallo
    avrebbe spezzato la serie e l'ingresso non si sarebbe trovato mai.

    Funziona su qualunque serie temporale, non solo sulle raffiche: sul vento
    medio, che a Torbole c'e' dal 2012, da' l'ingresso del regime senza
    aspettare che il campione di raffiche cresca.

    Ritorna il CENTRO dell'intervallo in cui il passaggio e' avvenuto: il
    campione dice che fra t-cadenza e t si era sopra soglia, non dove, e su una
    grandezza che vogliamo misurare a mezz'ora di precisione un errore
    sistematico di mezza cadenza e' regalato a nessuno.
    """
    pts = [(float(t), v) for t, v in series if v is not None]
    pts.sort()
    n = len(pts)
    if n == 0:
        return None
    if cadence_min is None:
        cadence_min = sampling_cadence([t for t, _v in pts]) or 0.0
    if max_gap_min is None:
        max_gap_min = max(15.0, 2.5 * cadence_min) if cadence_min else 60.0
    for i in range(n):
        if pts[i][1] < threshold:
            continue
        j = i
        while j + 1 < n:
            if pts[j + 1][0] - pts[j][0] > max_gap_min:
                break
            if pts[j + 1][1] < threshold:
                break
            j += 1
        if pts[j][0] - pts[i][0] + cadence_min >= persist_min - 1e-9:
            return pts[i][0] - cadence_min / 2.0
    return None


# --------------------------------------------------------------------------
# Unione dei campioni che descrivono lo stesso istante
# --------------------------------------------------------------------------
# La chiave di obs_sample e' (stazione, istante, FONTE). Il realtime non deve
# creare una SECONDA osservazione dello stesso istante: deve arricchire quella
# storica con la raffica, che l'archivio non ha. Questa e' la semantica giusta
# del dato, e trattarli come due righe indipendenti falsava cadenza (un
# intervallo di zero minuti), copertura, durate e il numero di campioni con cui
# il modello decide se un'ora e' una media o rumore.
#
# Dove i due sono d'accordo si uniscono. Dove due valori VALIDI dello stesso
# campo differiscono davvero, non si sceglie in silenzio: si registra un
# conflitto e si applica una regola dichiarata.

# L'archivio Hydstra e' la serie validata; il realtime e' istantaneo e non
# controllato. A parita' di istante, per i campi che entrambi hanno, vince
# l'archivio. La raffica esiste solo nel realtime, quindi arriva da li'.
# Le fonti non elencate vengono dopo, in ordine alfabetico: deterministico.
PRIORITA_SORGENTI = (
    "meteotrentino-archivio",
    "meteoproject-intraday",
    "meteotrentino-realtime",
    "meteoproject-live",
)

# Due fonti che misurano lo stesso istante possono differire per arrotondamento
# (l'archivio arriva in m/s e viene convertito in nodi). Sotto questa
# tolleranza non e' un conflitto, e' la stessa misura scritta due volte.
TOLLERANZA_KN = 0.6
TOLLERANZA_DEG = 12.0


def _rango(source):
    try:
        return (0, PRIORITA_SORGENTI.index(source or ""))
    except ValueError:
        return (1, source or "")


def merge_by_instant(samples, tol_kn=TOLLERANZA_KN, tol_deg=TOLLERANZA_DEG):
    """Unisce i campioni per istante. Ritorna (per_istante, conflitti).

    samples: iterabile di dict con ts/wind_kn/gust_kn/dir_deg/source, dove ts
    e' gia' un datetime oppure una chiave ordinabile.

    per_istante: {chiave: {"wind","gust","dir"}} con i campi uniti.
    conflitti: lista di dict con istante, campo, i due valori e le due fonti.
    Non vengono nascosti: chi chiama li conta e li dichiara.
    """
    grezzi = {}
    for s in samples:
        grezzi.setdefault(s["_key"], []).append(s)

    per_istante, conflitti = {}, []
    for key in grezzi:
        righe = sorted(grezzi[key], key=lambda r: _rango(r.get("source")))
        unito = {"wind": None, "gust": None, "dir": None}
        fonte_di = {}
        for r in righe:
            for campo, colonna, tol in (("wind", "wind_kn", tol_kn),
                                        ("gust", "gust_kn", tol_kn),
                                        ("dir", "dir_deg", tol_deg)):
                v = r.get(colonna)
                if v is None:
                    continue
                if unito[campo] is None:
                    unito[campo] = v
                    fonte_di[campo] = r.get("source")
                    continue
                differenza = abs(v - unito[campo])
                if campo == "dir":
                    differenza = min(differenza, 360.0 - differenza)
                if differenza > tol:
                    # La regola e' dichiarata: vince la fonte di rango
                    # migliore, che e' quella gia' dentro perche' le righe sono
                    # ordinate. Ma il disaccordo viene registrato.
                    conflitti.append({
                        "istante": key, "campo": campo,
                        "tenuto": unito[campo], "scartato": v,
                        "fonte_tenuta": fonte_di.get(campo),
                        "fonte_scartata": r.get("source"),
                        "differenza": differenza,
                    })
        per_istante[key] = unito
    return per_istante, conflitti


# Perche' due massimi locali non sono due modi. Senza questi tre criteri il
# rapporto dichiarava "DUE PICCHI" anche con valle/picco 0.99 e 1.00, cioe'
# una valle alta quanto il picco: quella non e' una distribuzione a due modi,
# e' una gobba larga e piatta con due massimi locali dentro il rumore. E
# dichiararla bimodale invita a costruire una complessita' che il dato non
# sostiene.
MAX_DIP = 0.70                 # la valle deve stare sotto il 70% del picco
MIN_SEPARAZIONE_MODI = 60.0    # due picchi a mezz'ora sono una gobba sola
MIN_N_MODI = 30                # una FORMA ha bisogno di piu' dati di una mediana

# Perche' la coppia di picchi e' stata rifiutata. Codici chiusi, come per le
# giornate: il rendering traduce, la logica non contiene italiano.
MOTIVI_MODI = ("valle_alta", "troppo_vicini", "pochi_dati")


def linear_modes(values, bin_size=30.0, smooth=1, min_share=0.35,
                 max_dip=MAX_DIP, min_sep=MIN_SEPARAZIONE_MODI,
                 min_n=MIN_N_MODI, dettagli=False):
    """Uno o due picchi in una distribuzione su una retta (non circolare).

    Serve sugli orari: se in un mese l'ingresso ha due picchi distinti - meta'
    delle giornate alle 12 e meta' alle 15 - allora una mediana mensile e' un
    riferimento povero, perche' cade in un avvallamento dove non capita quasi
    mai niente. Con un solo picco, invece, la mediana e' un buon riassunto.

    Ritorna (modi, dip): i centri dei picchi trovati (uno o due) e il rapporto
    fra il minimo della valle fra i due e il piu' basso dei due picchi. Un dip
    piccolo vuol dire valle profonda, cioe' due popolazioni davvero separate;
    un dip vicino a 1 vuol dire una gobba larga letta male.

    dip e' None quando non ci sono due picchi: attenzione a non confonderlo con
    0.0, che e' il caso PIU' bimodale di tutti - una valle vuota. Lo stesso
    inciampo l'avevamo avuto sulle direzioni.

    Due massimi locali non bastano per dichiarare due modi. Servono tutte tre:
    la valle sotto max_dip del picco piu' basso (prominenza), i due centri
    distanti almeno min_sep (separazione), e almeno min_n valori (una forma
    chiede piu' dati di una mediana). Se la coppia viene rifiutata si ritorna
    un solo modo - ma con dettagli=True si ottiene anche PERCHE', cosi' il
    rifiuto si puo' mostrare invece di farlo in silenzio.

    dettagli=True -> (modi, dip, motivo) invece di (modi, dip).
    """
    def esito(modi, dip, motivo=None):
        return (modi, dip, motivo) if dettagli else (modi, dip)

    xs = [float(v) for v in values if v is not None]
    if len(xs) < 6:
        return esito([], None, "pochi_dati")
    lo, hi = min(xs), max(xs)
    if hi - lo < bin_size:
        return esito([median(xs)], None)
    n_bin = max(3, int((hi - lo) / bin_size) + 1)
    conteggi = [0] * n_bin
    for v in xs:
        conteggi[min(n_bin - 1, int((v - lo) / bin_size))] += 1
    for _ in range(max(0, smooth)):
        conteggi = [
            (conteggi[max(0, i - 1)] + conteggi[i] + conteggi[min(n_bin - 1, i + 1)]) / 3.0
            for i in range(n_bin)]

    def centro(i):
        return lo + (i + 0.5) * bin_size

    picchi = [i for i in range(n_bin)
              if conteggi[i] >= conteggi[max(0, i - 1)]
              and conteggi[i] >= conteggi[min(n_bin - 1, i + 1)]
              and conteggi[i] > 0]
    if not picchi:
        return esito([median(xs)], None)
    picchi.sort(key=lambda i: -conteggi[i])
    primo = picchi[0]
    # Un secondo picco conta solo se e' alto almeno min_share del primo e non
    # e' il suo vicino immediato: due bin adiacenti sono una gobba, non due.
    abbastanza_alti = [i for i in picchi[1:]
                       if conteggi[i] >= min_share * conteggi[primo]]
    secondo = next((i for i in abbastanza_alti if abs(i - primo) >= 2), None)
    if secondo is None:
        # Distinguere "nessun secondo picco" da "secondo picco appiccicato al
        # primo" serve a chi legge: il secondo caso e' una gobba larga, e
        # saperlo e' diverso dal non avere affatto un secondo massimo.
        return esito([centro(primo)], None,
                     "troppo_vicini" if abbastanza_alti else None)
    a, b = sorted((primo, secondo))
    valle = min(conteggi[a + 1:b]) if b > a + 1 else min(conteggi[a], conteggi[b])
    dip = valle / min(conteggi[a], conteggi[b]) if min(conteggi[a], conteggi[b]) else None

    # I tre criteri. L'ordine conta solo per il messaggio: si dice il motivo
    # piu' sostanziale, cioe' "non e' una valle" prima di "sono pochi dati".
    if dip is None or dip > max_dip:
        return esito([centro(a)], None, "valle_alta")
    if abs(centro(b) - centro(a)) < min_sep:
        return esito([centro(a)], None, "troppo_vicini")
    if len(xs) < min_n:
        return esito([centro(a)], None, "pochi_dati")
    return esito([centro(a), centro(b)], dip)


# ==========================================================================
# Luce del giorno
# ==========================================================================
#
# Serve per una ragione pratica, non astronomica: sul Peler la finestra utile
# non comincia quando nasce il vento, comincia quando si vede. Un'ora pratica
# fissa alle 06:00 a dicembre e' prima dell'alba - si starebbe ottimizzando
# un'ora in cui nessuno puo' essere in acqua - e a giugno butta via mezz'ora
# buona. L'alba si muove di due ore fra dicembre e giugno, e il Peler e'
# l'unico regime dei due in cui questo vincola davvero.
#
# La formula e' quella NOAA, in forma ridotta: niente rete, niente tabelle,
# solo aritmetica, e quindi deterministica e verificabile. L'errore su
# latitudini come quella del Garda e' dell'ordine del minuto - abbastanza per
# decidere se si parte alle 6 o alle 8, che e' tutto quello che serve qui.

ZENIT_ALBA_DEG = 90.833      # alba civile: bordo del sole piu' rifrazione


def _giorno_giuliano(anno, mese, giorno):
    if mese <= 2:
        anno -= 1
        mese += 12
    a = anno // 100
    b = 2 - a + a // 4
    return (int(365.25 * (anno + 4716)) + int(30.6001 * (mese + 1))
            + giorno + b - 1524.5)


def alba_tramonto(data_iso, lat, lon, offset_ore, zenit=ZENIT_ALBA_DEG):
    """(alba, tramonto) in minuti dalla mezzanotte LOCALE, o (None, None).

    offset_ore e' l'offset del fuso in quel giorno (per l'Italia 1 d'inverno,
    2 d'estate): l'alba dipende dal fuso civile, e passarlo esplicitamente
    evita di dover indovinare l'ora legale dentro una formula astronomica.

    Ritorna (None, None) oltre i circoli polari, dove il sole puo' non
    sorgere: qui non capita, ma un None e' meglio di un numero inventato.
    """
    anno, mese, giorno = (int(x) for x in data_iso[:10].split("-"))
    jd = _giorno_giuliano(anno, mese, giorno)
    n = jd - 2451545.0 + 0.0008
    # anomalia media, centro, longitudine eclittica
    m = math.radians((357.5291 + 0.98560028 * n) % 360.0)
    c = (1.9148 * math.sin(m) + 0.0200 * math.sin(2 * m)
         + 0.0003 * math.sin(3 * m))
    lam = math.radians((math.degrees(m) + c + 180.0 + 102.9372) % 360.0)
    # declinazione e equazione del tempo (in minuti)
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    y = math.tan(math.radians(23.4397) / 2.0) ** 2
    eqt = 4.0 * math.degrees(
        y * math.sin(2.0 * math.radians((math.degrees(lam) - 102.9372) % 360.0))
        - 2.0 * 0.0167 * math.sin(m)
        + 4.0 * 0.0167 * y * math.sin(m)
        * math.cos(2.0 * math.radians((math.degrees(lam) - 102.9372) % 360.0)))
    phi = math.radians(lat)
    cos_h = ((math.cos(math.radians(zenit)) - math.sin(phi) * math.sin(decl))
             / (math.cos(phi) * math.cos(decl)))
    if cos_h > 1.0 or cos_h < -1.0:
        return None, None
    h = math.degrees(math.acos(cos_h))
    # mezzogiorno solare locale, in minuti dalla mezzanotte civile
    mezzogiorno = 720.0 - 4.0 * lon - eqt + offset_ore * 60.0
    return mezzogiorno - 4.0 * h, mezzogiorno + 4.0 * h


def offset_locale_ore(data_iso):
    """Offset del fuso italiano in quel giorno, in ore: 1 o 2.

    Si appoggia alla stessa conversione usata da tutto il resto del
    programma, invece di rifare le regole dell'ora legale qui.
    """
    dt = parse_iso_utc(data_iso[:10] + "T12:00:00Z")
    loc = to_local(dt)
    return (loc.utcoffset().total_seconds() / 3600.0) if loc.utcoffset() else 1.0


def curva_monotona(punti, cifre=1):
    """Un percorso CURVO che passa per tutti i punti e non inventa massimi.

`cifre` serve perche' questa funzione ha due clienti con due precisioni:
    il grafico la vuole in unita' di viewBox (un decimo basta), il processo
    veloce la scrive in coordinate normalizzate 0-1 dentro live.json, e la'
    un decimo sarebbe una griglia da dieci passi.

    Gian: "preferibilmente che sia una curva non una serie di rette
    spezzate". La tentazione, per ottenerla, e' una spline morbida qualunque -
    e sarebbe il difetto peggiore che questo grafico potrebbe avere, perche'
    una spline morbida OLTREPASSA i punti: fra un 16 e un 20 disegna un 21 che
    nessun modello ha previsto e nessuna centralina ha misurato. Su una pagina
    che serve a decidere se andare in acqua, un picco inventato e' la cosa
    peggiore da disegnare.

    Quindi si usa l'interpolazione cubica MONOTONA (Fritsch-Carlson): passa
    esattamente per ogni punto, e su ogni tratto resta monotona, cioe' non
    puo' creare un massimo o un minimo che non ci sia nei dati. Dove i dati
    cambiano verso, la pendenza viene messa a zero e la curva ha il suo
    estremo esattamente nel punto misurato.

    E il gradino dell'Ora sopravvive: i punti sono onorati uno per uno, quindi
    una salita di sette nodi in mezz'ora resta una salita di sette nodi in
    mezz'ora - arrotondata negli spigoli, non spianata.
    """
    pts = [(float(x), float(y)) for x, y in punti]
    if len(pts) < 2:
        return ""
    f2 = "M%%.%df,%%.%df L%%.%df,%%.%df" % (cifre, cifre, cifre, cifre)
    if len(pts) == 2:
        return f2 % (pts[0][0], pts[0][1], pts[1][0], pts[1][1])
    n = len(pts)
    h = [pts[i + 1][0] - pts[i][0] for i in range(n - 1)]
    d = [((pts[i + 1][1] - pts[i][1]) / h[i] if h[i] else 0.0)
         for i in range(n - 1)]
    m = [d[0]] + [0.0] * (n - 2) + [d[-1]]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0                     # un estremo resta dove e' misurato
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    fm = "M%%.%df,%%.%df" % (cifre, cifre)
    fc = ("C%%.%df,%%.%df %%.%df,%%.%df %%.%df,%%.%df"
          % tuple([cifre] * 6))
    out = [fm % pts[0]]
    for i in range(n - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        out.append(fc % (x0 + h[i] / 3.0, y0 + m[i] * h[i] / 3.0,
                         x1 - h[i] / 3.0, y1 - m[i + 1] * h[i] / 3.0,
                         x1, y1))
    return " ".join(out)


def riscala(curva, x):
    """Porta una lettura sulla scala comune con una curva a punti (x, y).

    Lineare fra i punti; sotto il primo e sopra l'ultimo si tiene il rapporto
    del punto estremo, cosi' zero resta zero e una lettura fuori tabella non
    salta. Monotona per costruzione se la curva lo e'.
    """
    if x is None or not curva:
        return x
    x = float(x)
    (x0, y0), (xn, yn) = curva[0], curva[-1]
    if x <= x0:
        return x * y0 / x0 if x0 > 0 else y0
    if x >= xn:
        return x * yn / xn
    for (a, ya), (b, yb) in zip(curva, curva[1:]):
        if a <= x <= b:
            return ya + (yb - ya) * (x - a) / (b - a)
    return x
