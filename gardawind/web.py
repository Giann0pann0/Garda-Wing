"""Cruscotto locale.

Due schermate:
  /              quello che serve per decidere se andare in acqua
  /diagnostica   quanto sbaglia il modello, misurato su dati mai visti

La seconda esiste perche' la prima sia credibile. Un numero senza un errore
dichiarato e' un'opinione.

L'impaginazione e' PER GIORNO, non per luogo: si sceglie prima quando andare
e poi dove. Dentro ogni giorno le sessioni sono in ordine di orologio:
prima il Peler, che e' un vento di mattina, poi l'Ora, che e' di pomeriggio.
"""

import html
import json
import math
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, confidence, engine, store, verify
from .util import clamp, parse_dt_any, to_local

E = html.escape

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
# Le due serie (Torbole / Malcesine) sono identita', non grandezze: colore
# categorico, assegnato una volta e mai riciclato. Coppia verificata con il
# validatore sulle superfici effettive di questa pagina:
#   chiaro  #2a78d6 / #eb6834 su #ffffff  -> tutti i controlli superati
#   scuro   #3987e5 / #d95926 su #161b22  -> tutti i controlli superati
# Lo sfondo marino sta sul piano della PAGINA, non sulla superficie dei
# grafici: le schede restano neutre, e la validazione resta valida.

CSS = """
:root{
  color-scheme:light;
  --sea-1:#dbe9f4; --sea-2:#eaf3f9; --sea-3:#c9e0f0;
  --card:#ffffff; --card-2:#f4f8fc;
  --ink:#0c1722; --ink-2:#4a5a6b; --ink-3:#7d8d9c;
  --line:#e0e8ef; --grid:#e8eef4; --axis:#c2cedb;
  --s1:#2a78d6; --s2:#eb6834;
  --s1-soft:#cde2fb; --s2-soft:#fbdcce;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --warn-ink:#8a5f00;
  --shadow:0 1px 2px rgba(12,23,34,.06),0 10px 28px rgba(12,23,34,.08);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --sea-1:#071420; --sea-2:#0b1f2d; --sea-3:#040f18;
    --card:#161b22; --card-2:#1c2430;
    --ink:#eef4f9; --ink-2:#a9bacb; --ink-3:#7f91a3;
    --line:#252f3c; --grid:#222c38; --axis:#3a4859;
    --s1:#3987e5; --s2:#d95926;
    --s1-soft:#16324f; --s2-soft:#412210;
    --warn-ink:#fab219;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 12px 32px rgba(0,0,0,.4);
  }
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color:var(--ink);
  background:
    radial-gradient(1100px 480px at 15% -10%, var(--sea-2), transparent 60%),
    radial-gradient(900px 420px at 90% 2%, var(--sea-3), transparent 55%),
    linear-gradient(180deg, var(--sea-1) 0%, var(--sea-2) 45%, var(--sea-1) 100%);
  background-attachment:fixed;
  min-height:100vh;
}
.display{
  font-family:"Avenir Next","Avenir",Futura,"Gill Sans","Trebuchet MS",system-ui,sans-serif;
  font-weight:700;letter-spacing:-.018em;
}
a{color:var(--s1)}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}

header{padding:26px 0 0}
.hbar{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:31px;line-height:1.04}
h1 .sub{display:block;font-family:system-ui,sans-serif;font-weight:500;font-size:12px;
  letter-spacing:.1em;text-transform:uppercase;color:var(--ink-2);margin-top:7px}
.status{font-size:13px;color:var(--ink-2);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);flex:none}
.dot.warn{background:var(--warn)}.dot.bad{background:var(--crit)}
.wave{display:block;width:100%;height:40px;margin-top:20px}

.now{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;
  margin:2px 0 24px}
.nowcard{background:var(--card);border-radius:16px;padding:13px 16px;box-shadow:var(--shadow);
  display:flex;align-items:center;gap:13px}
.nowcard .place{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
.nowcard .val{font-size:26px;line-height:1.1;font-family:"Avenir Next",system-ui,sans-serif;
  font-weight:700}
.nowcard .val small{font-size:13px;color:var(--ink-2);font-weight:600}
.nowcard .meta{font-size:12px;color:var(--ink-3)}
.nowcard.stale .val{color:var(--ink-3)}

.day{background:var(--card);border-radius:20px;padding:20px;margin-bottom:18px;
  box-shadow:var(--shadow)}
.dayhead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.dayhead h2{margin:0;font-size:23px}
.dayhead .date{font-size:13px;color:var(--ink-2)}
.dayhead .lead{margin-left:auto;font-size:11.5px;color:var(--ink-3)}

/* Affidabilita': quattro livelli, quattro colori, sempre con la parola scritta
   accanto. Il colore da' la lettura in mezzo secondo, la parola la da' a chi
   non distingue quei colori e a chi legge stampato. */
.cf{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
  padding:3px 10px;font-size:12.5px;font-weight:800;letter-spacing:.01em}
.cf::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.cf-alta{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.cf-buona{background:color-mix(in srgb,var(--s1) 15%,transparent);color:var(--s1)}
.cf-tend{background:color-mix(in srgb,var(--warn) 26%,transparent);color:var(--warn-ink)}
.cf-out{background:color-mix(in srgb,var(--ink-3) 16%,transparent);color:var(--ink-2)}
.cfline{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px}
.cf-why{font-size:12.5px;color:var(--ink-3)}
/* Seconda voce: l'orario. Stessa grammatica, peso visivo minore, perche' e'
   una domanda diversa e subordinata - ma sempre presente, mai sottintesa. */
.tm{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;
  border-radius:8px;padding:2px 9px;background:var(--card-2);color:var(--ink-2)}
.tm b{font-weight:700;color:var(--ink)}
.tm::before{content:"";width:6px;height:6px;border-radius:50%;flex:none;
  background:currentColor;opacity:.75}
.tm-3{color:var(--good)}.tm-2{color:var(--s1)}
.tm-1{color:var(--warn-ink)}.tm-0{color:var(--ink-3)}
.dayhead .cfline{margin-left:auto;margin-top:0}

.session{margin-top:16px}
.shead{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.shead{margin-bottom:2px}
.shead .name{font-size:13px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink);font-weight:800}
.shead .when{font-size:13px;color:var(--ink-3);font-variant-numeric:tabular-nums}

.row{display:grid;grid-template-columns:132px 1fr auto;gap:14px;align-items:center;
  padding:12px 0 6px;border-top:1px solid var(--line)}
.row .spot{display:flex;align-items:center;gap:8px;font-weight:700;font-size:16px}
.swatch{width:11px;height:11px;border-radius:3px;flex:none}
.row .num{text-align:right;white-space:nowrap}
.row .kn{font-size:27px;font-weight:700;line-height:1.05;
  font-family:"Avenir Next",system-ui,sans-serif}
.row .kn small{font-size:14px;font-weight:600;color:var(--ink-2)}
.row .pct{font-size:13px;color:var(--ink-2);font-variant-numeric:tabular-nums}
.detail{grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap;align-items:center;
  font-size:13px;color:var(--ink-2);padding:2px 0 6px}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 11px;
  font-size:13px;font-weight:700}
.chip.go{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.chip.ok{background:color-mix(in srgb,var(--s1) 15%,transparent);color:var(--s1)}
.chip.meh{background:color-mix(in srgb,var(--warn) 24%,transparent);color:var(--warn-ink)}
.chip.no{background:color-mix(in srgb,var(--ink-3) 15%,transparent);color:var(--ink-2)}
.chip.big{background:color-mix(in srgb,var(--crit) 15%,transparent);color:var(--crit)}
.tag{background:var(--card-2);border-radius:8px;padding:3px 10px;font-size:13px;
  color:var(--ink-2)}
.tag b{color:var(--ink);font-weight:700}
.other{grid-column:1/-1;margin:2px 0 8px;padding:10px 12px;border-radius:11px;
  background:var(--card-2);border-left:3px solid var(--s2);font-size:13.5px;
  color:var(--ink-2);line-height:1.45}
.other b{color:var(--ink)}

.strip{position:relative;height:30px}
.strip .track{position:absolute;left:0;right:0;top:10px;height:10px;border-radius:5px;
  background:var(--card-2)}
.strip .band{position:absolute;top:10px;height:10px;border-radius:5px;opacity:.30}
.strip .bar{position:absolute;top:10px;height:10px;border-radius:5px;left:0}
.strip .thr{position:absolute;top:4px;height:22px;width:2px;border-radius:1px;
  background:var(--axis)}
.strip .thr::after{content:attr(data-l);position:absolute;top:-13px;left:50%;
  transform:translateX(-50%);font-size:10px;color:var(--ink-3);white-space:nowrap}
.strip .dot{position:absolute;top:7px;width:16px;height:16px;border-radius:50%;
  margin-left:-8px;box-shadow:0 0 0 3px var(--card)}
.row.faint .kn,.row.faint .spot{opacity:.42}
.row.faint .strip{opacity:.4}
.scalerow{display:grid;grid-template-columns:132px 1fr auto;gap:14px;align-items:end}
.scalerow .sp{font-size:11px;color:var(--ink-3);letter-spacing:.06em}
.scalerow .rt{font-size:11px;color:transparent}
.scale{position:relative;height:15px}
.scale span{position:absolute;bottom:0;transform:translateX(-50%);font-size:11px;
  color:var(--ink-3);font-variant-numeric:tabular-nums;white-space:nowrap}
.scale i{position:absolute;bottom:0;width:1px;height:5px;background:var(--line)}
svg.chart{display:block;width:100%;height:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2);margin-top:9px}
.legend i{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:6px;
  vertical-align:middle}
.chartwrap{position:relative;margin-top:16px}
.tip{position:absolute;pointer-events:none;opacity:0;transition:opacity .12s;
  background:var(--card);border:1px solid var(--line);border-radius:10px;padding:7px 10px;
  font-size:12px;box-shadow:var(--shadow);white-space:nowrap;z-index:3;color:var(--ink)}
details.tbl{margin-top:10px;font-size:13px}
details.tbl summary{cursor:pointer;color:var(--ink-3)}
.trust{margin-top:14px;padding-top:12px;border-top:1px solid var(--line);
  font-size:12.5px;color:var(--ink-3);line-height:1.6}
.trust b{color:var(--ink-2)}

table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 16px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:600}.bad{color:var(--crit);font-weight:600}

.panel{background:var(--card);border-radius:20px;padding:20px;margin-bottom:18px;
  box-shadow:var(--shadow)}
.panel h2{margin:0 0 8px;font-size:20px}
.panel h3{margin:18px 0 2px;font-size:13.5px}
.panel p{color:var(--ink-2);font-size:13px;margin:6px 0 10px}
.empty{padding:36px 10px;text-align:center;color:var(--ink-3)}
footer{padding:4px 0 46px;font-size:12px;color:var(--ink-3);text-align:center}
@media (max-width:640px){
  .wrap{padding:0 12px}
  h1{font-size:24px}
  .day,.panel{padding:14px;border-radius:16px}
  .row{grid-template-columns:1fr auto;gap:6px 10px}
  .row .spot{grid-column:1;font-size:15px}
  .row>div:nth-child(2){grid-column:1/-1;order:3;margin-top:2px}
  .row .detail{order:4}
  .row .other{order:5}
  .row .kn{font-size:26px}
  .row .pct{font-size:12px;white-space:normal;text-align:right}
  .scalerow{grid-template-columns:1fr;gap:0}
  .scalerow .sp,.scalerow .rt{display:none}
  .tag,.chip{font-size:12.5px}
  .dayhead h2{font-size:20px}
  .dayhead .lead{width:100%;margin-left:0}
}
"""

WAVE = ('<svg class="wave" viewBox="0 0 1200 40" preserveAspectRatio="none" aria-hidden="true">'
        '<path d="M0,24 C150,8 260,36 420,26 C580,16 660,34 820,28 C960,23 1060,10 1200,20 '
        'L1200,40 L0,40 Z" fill="var(--card)" opacity=".5"/>'
        '<path d="M0,31 C170,17 280,39 440,31 C620,22 700,38 860,33 C1000,29 1080,20 1200,27 '
        'L1200,40 L0,40 Z" fill="var(--card)" opacity=".92"/></svg>')

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]

SOURCE_LABEL = {
    "appreso": "modello addestrato sullo storico della centralina",
    "misto": "probabilità addestrata, intensità ancora dalla stima fisica",
    "prior": "stima fisica di partenza, non ancora calibrata sui dati",
}

# Le sessioni in ordine di orologio: il Pelèr e' un vento di mattina, l'Ora
# di pomeriggio. Mostrarle nell'ordine opposto costringe a rileggere.
SESSION_ORDER = [
    ("Mattina · Pelèr", "PELER"),
    ("Pomeriggio · Ora", "ORA"),
    ("Tutto il giorno", "GIORNO"),
]


# --------------------------------------------------------------------------
# Pezzi riutilizzabili
# --------------------------------------------------------------------------

def day_title(day, lead):
    """Titolo del giorno in italiano, senza sigle.

    Niente D+1 / D+3: la scadenza si dice come la si dice a voce. Il giorno
    della settimana resta accanto, perche' "tra 5 giorni" e' comodo per capire
    la distanza e inutile per capire se e' sabato.
    """
    dt = parse_dt_any(day + " 12:00:00")
    return (confidence.lead_label(lead),
            "%s %d %s" % (GIORNI[dt.weekday()], dt.day, MESI[dt.month - 1]))


# Quanto ci si puo' fidare, in una parola sola e con un colore. L'etichetta non
# viene dalla scadenza ma dalle misure fatte a quella scadenza su quello spot:
# due giorni identici sul calendario possono meritare due etichette diverse.
CONF_CLASS = {3: "cf-alta", 2: "cf-buona", 1: "cf-tend", 0: "cf-out"}


def confidence_badge(val, compact=False):
    if not val:
        return ""
    cls = CONF_CLASS.get(val["livello"], "cf-out")
    label = val["etichetta"]
    title = val.get("motivo") or val.get("uso") or ""
    if compact:
        return ('<span class="cf %s" title="%s">%s</span>'
                % (cls, E(title), E(label[0].upper() + label[1:])))
    extra = ('<span class="cf-why">%s</span>'
             % E(val.get("motivo") or val.get("uso") or "")) if title else ""
    return ('<div class="cfline"><span class="cf %s">%s</span>%s</div>'
            % (cls, E(label[0].upper() + label[1:]), extra))


def hhmm(minutes):
    """Minuti dalla mezzanotte -> HH:MM, arrotondati a dieci minuti.

    L'arrotondamento a dieci non e' estetica: scrivere 08:07 suggerirebbe una
    precisione al minuto che l'interpolazione di un profilo orario non ha.
    """
    m = int(round(clamp(minutes, 0.0, 24 * 60 - 1) / 10.0) * 10)
    return "%02d:%02d" % (m // 60, m % 60)


def timing_badge(val):
    """La seconda voce della scheda: l'orario, separato dalla prima."""
    if not val:
        return ""
    return ('<span class="tm tm-%d">Timing: <b>%s</b>%s</span>'
            % (val["livello"], E(val["etichetta"]),
               (" · ±%d min" % round(val["minuti"])) if val.get("minuti") else ""))


def compass(deg):
    if deg is None:
        return ""
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]


def arrow(deg, size=24, color="currentColor"):
    """Freccia che punta dove VA il vento, ruotata dalla sua provenienza."""
    if deg is None:
        return ""
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" aria-hidden="true" '
            'style="flex:none"><g transform="rotate(%.0f 12 12)">'
            '<path d="M12 3 L12 21 M12 21 L7.6 15.6 M12 21 L16.4 15.6" fill="none" '
            'stroke="%s" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>'
            '</g></svg>' % (size, size, (deg or 0) % 360, color))


def verdict_chip(grade, speed, prob):
    if prob is not None and prob < 0.25:
        cls = "no"
    elif speed >= 23:
        cls = "big"
    elif speed >= 16:
        cls = "go"
    elif speed >= 12:
        cls = "ok"
    elif speed >= 9:
        cls = "meh"
    else:
        cls = "no"
    mark = {"go": "✓", "big": "!", "ok": "~", "meh": "~", "no": "✕"}[cls]
    return '<span class="chip %s">%s %s</span>' % (cls, mark, E(grade))


def range_strip(lo, hi, value, threshold, scale_max, color, muted=False):
    """Barra orizzontale: quanto tira, con dentro l'incertezza e la soglia.

    La lunghezza porta l'intensita', il punto il valore atteso, la parte
    chiara l'intervallo. La tacca e' la soglia di planata, etichettata, cosi'
    la barra si legge senza dover indovinare cosa significhi la sua lunghezza:
    sopra al gruppo c'e' comunque la scala in nodi.
    """
    def pct(v):
        return max(0.0, min(100.0, 100.0 * v / scale_max))

    a, b, v = pct(lo), pct(hi), pct(value)
    return (
        '<div class="strip" role="img" aria-label="%.0f nodi attesi, da %.0f a %.0f, '
        'planata sopra %.0f">'
        '<div class="track"></div>'
        '<div class="band" style="left:%.1f%%;width:%.1f%%;background:%s"></div>'
        '<div class="bar" style="width:%.1f%%;background:%s;opacity:%s"></div>'
        '<div class="thr" data-l="planata" style="left:%.1f%%"></div>'
        '<div class="dot" style="left:%.1f%%;background:%s"></div>'
        '</div>'
        % (value, lo, hi, threshold,
           a, max(1.5, b - a), color,
           v, color, ".55" if muted else ".85",
           pct(threshold), v, "var(--ink-3)" if muted else color))


def scale_bar(scale_max, steps=3):
    """Righello in nodi, allineato esattamente alla colonna delle barre."""
    marks = ['<span style="left:0">0</span>']
    for i in range(1, steps + 1):
        pos = 100.0 * i / steps
        marks.append('<span style="left:%.1f%%">%d</span>' % (pos, round(scale_max * i / steps)))
    return ('<div class="scalerow"><div class="sp">NODI</div>'
            '<div class="scale">%s</div><div class="rt">00</div></div>'
            % "".join(marks))


def hourly_chart(profiles, bands, chart_id, best_hours=None):
    """Andamento della giornata, una linea per luogo.

    Due serie soltanto, con etichetta diretta a fine linea oltre al colore:
    l'identita' non dipende mai dal colore da solo. Sotto l'asse, una riga di
    frecce con la direzione prevista: per chi va in acqua "da dove viene" conta
    quanto "quanto tira", e nessun numero lo dice altrettanto in fretta.
    """
    series = [(place, sorted(rows, key=lambda r: r["hour"]))
              for place, rows in profiles if rows]
    if not series:
        return ""
    hours = sorted({r["hour"] for _p, rows in series for r in rows})
    if len(hours) < 3:
        return ""

    W, H = 760.0, 270.0
    pl, pr, pt, pb = 34.0, 84.0, 16.0, 52.0
    peak = max([r["hi"] for _p, rows in series for r in rows] + [12.0])
    top = max(15.0, 5 * math.ceil(peak / 5.0))

    def x(h):
        return pl + (W - pl - pr) * ((h - hours[0]) / max(1, hours[-1] - hours[0]))

    def y(v):
        return H - pb - (H - pb - pt) * (max(0.0, min(top, v)) / top)

    colors = ["var(--s1)", "var(--s2)"]
    softs = ["var(--s1-soft)", "var(--s2-soft)"]
    p = ['<defs>']
    for i in range(len(series)):
        p.append('<linearGradient id="%s-g%d" x1="0" y1="0" x2="0" y2="1">'
                 '<stop offset="0%%" stop-color="%s" stop-opacity=".34"/>'
                 '<stop offset="100%%" stop-color="%s" stop-opacity="0"/></linearGradient>'
                 % (chart_id, i, colors[i], colors[i]))
    p.append('</defs>')

    for band in bands:
        a, b = max(band["from"], hours[0]), min(band["to"], hours[-1])
        if b <= a:
            continue
        p.append('<rect x="%.1f" y="%g" width="%.1f" height="%.1f" fill="var(--card-2)" '
                 'rx="6"/>' % (x(a), pt, x(b) - x(a), H - pb - pt))
        p.append('<text x="%.1f" y="%g" font-size="11" font-weight="700" '
                 'letter-spacing=".1em" fill="var(--ink-3)">%s</text>'
                 % (x(a) + 7, pt + 15, E(band["label"].upper())))

    for v in range(0, int(top) + 1, 5):
        yy = y(v)
        p.append('<line x1="%g" y1="%.1f" x2="%g" y2="%.1f" stroke="var(--grid)" '
                 'stroke-width="1"/>' % (pl, yy, W - pr, yy))
        p.append('<text x="%g" y="%.1f" text-anchor="end" font-size="11.5" '
                 'fill="var(--ink-3)">%d</text>' % (pl - 7, yy + 4, v))

    for i, (_place, rows) in enumerate(series):
        area = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["wind"])) for r in rows)
        p.append('<polygon points="%.1f,%.1f %s %.1f,%.1f" fill="url(#%s-g%d)"/>'
                 % (x(rows[0]["hour"]), H - pb, area, x(rows[-1]["hour"]), H - pb,
                    chart_id, i))
        hi = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["hi"])) for r in rows)
        lo = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["lo"])) for r in reversed(rows))
        p.append('<polygon points="%s %s" fill="%s" opacity=".5"/>' % (hi, lo, softs[i]))

    for i, (place, rows) in enumerate(series):
        pts = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["wind"])) for r in rows)
        p.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="3" '
                 'stroke-linejoin="round" stroke-linecap="round"/>' % (pts, colors[i]))
        top_row = max(rows, key=lambda r: r["wind"])
        p.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="var(--card)" '
                 'stroke-width="2.5"/>' % (x(top_row["hour"]), y(top_row["wind"]), colors[i]))
        p.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="800" fill="%s">'
                 '%.0f kn</text>'
                 % (x(top_row["hour"]) + 9, y(top_row["wind"]) - 7, colors[i],
                    top_row["wind"]))
        last = rows[-1]
        p.append('<text x="%.1f" y="%.1f" font-size="12.5" font-weight="700" fill="%s">'
                 '%s</text>' % (x(last["hour"]) + 9, y(last["wind"]) + 4, colors[i],
                                E(place)))

    # Frecce di direzione della serie principale, una ogni due ore.
    main = series[0][1]
    ay = H - pb + 20
    for r in main:
        if r["hour"] % 2 or r.get("dir") is None:
            continue
        p.append('<g transform="translate(%.1f %g) rotate(%.0f) scale(.62)" '
                 'opacity=".75">'
                 '<path d="M0 -9 L0 9 M0 9 L-4.4 3.4 M0 9 L4.4 3.4" fill="none" '
                 'stroke="%s" stroke-width="2.6" stroke-linecap="round" '
                 'stroke-linejoin="round"/></g>'
                 % (x(r["hour"]), ay, (r["dir"] or 0) % 360, colors[0]))

    for h in hours:
        if h % 2 == 0:
            p.append('<text x="%.1f" y="%g" text-anchor="middle" font-size="11.5" '
                     'fill="var(--ink-3)">%02d</text>' % (x(h), H - pb + 2, h))

    p.append('<line id="%s-cross" x1="0" y1="%g" x2="0" y2="%g" stroke="var(--axis)" '
             'stroke-width="1.5" opacity="0"/>' % (chart_id, pt, H - pb))

    payload = []
    for h in hours:
        e = {"h": h}
        for place, rows in series:
            m = [r for r in rows if r["hour"] == h]
            if m:
                e[place] = [round(m[0]["wind"], 1), round(m[0]["gust"], 1),
                            compass(m[0].get("dir"))]
        payload.append(e)

    head = "".join('<th class="num">%s</th>' % E(pl_) for pl_, _r in series)
    body = []
    for e in payload:
        cells = "".join(
            '<td class="num">%s</td>'
            % (("%.0f <span style='opacity:.6'>(%.0f) %s</span>"
                % (e[pl_][0], e[pl_][1], E(e[pl_][2]))) if pl_ in e else "—")
            for pl_, _r in series)
        body.append("<tr><td>%02d:00</td>%s</tr>" % (e["h"], cells))

    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (colors[i], E(pl_))
                     for i, (pl_, _r) in enumerate(series))

    return (
        '<div class="chartwrap">'
        '<svg class="chart" id="%s" viewBox="0 0 %g %g" role="img" '
        'aria-label="Vento previsto ora per ora">%s</svg>'
        '<div class="tip" id="%s-tip"></div></div>'
        '<div class="legend">%s'
        '<span><i style="background:var(--card-2);height:10px"></i>finestra del regime</span>'
        '<span><i style="background:var(--s1-soft);height:10px"></i>incertezza</span>'
        '<span>frecce: da dove viene</span></div>'
        '<details class="tbl"><summary>i numeri, ora per ora (medio, raffica, direzione)'
        '</summary><table><tr><th>Ora</th>%s</tr>%s</table></details>'
        '<script>gwChart(%s,%s,%g,%g,%g,%g,%g);</script>'
        % (chart_id, W, H, "".join(p), chart_id, legend, head, "".join(body),
           json.dumps(chart_id), json.dumps(payload), W, pl, pr, hours[0], hours[-1]))


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------

def now_card(place, live):
    if not live or live.get("wind") is None:
        return ('<div class="nowcard stale"><div><div class="place">%s</div>'
                '<div class="val">—</div><div class="meta">nessuna lettura</div></div></div>'
                % E(place))
    age = live["age_min"]
    when = ("adesso" if age is not None and age < 12 else
            "%d min fa" % age if age is not None and age < 180 else "dato non recente")
    gust = " · raffica %.0f kn" % live["gust"] if live.get("gust") else ""
    return (
        '<div class="nowcard%s">%s<div><div class="place">%s · adesso</div>'
        '<div class="val">%.0f <small>kn %s</small></div>'
        '<div class="meta">%s%s</div></div></div>'
        % (" stale" if live["stale"] else "", arrow(live["dir"], 26, "var(--s1)"), E(place),
           live["wind"], E(compass(live["dir"])), when, gust))


def other_wind_note(spot_name, data):
    """Che succede se il regime non entra ma il vento c'e' lo stesso."""
    other = data.get("other_wind")
    if not other or other.get("dir") is None:
        return ""
    # Con vento debole non c'e' niente da segnalare: la riga dice gia' che
    # non si naviga, e ripeterlo con un riquadro e' solo rumore.
    if not other["usable"] and other["speed"] < 8.0:
        return ""
    spot = config.SPOTS[spot_name]
    regime = "Pelèr" if spot["regime"] == "PELER" else "Ora"
    card = compass(other["dir"])
    if other["usable"]:
        testa = ("Il %s non entra, ma i modelli danno <b>%.0f kn da %s</b>"
                 % (regime, other["speed"], card))
        coda = (" — lungo il lago, quindi navigabile."
                if other.get("along_lake") else
                " — vento trasversale: sul lago è di solito irregolare e rafficato.")
    else:
        testa = ("Il %s non entra. Il vento previsto viene da <b>%s</b>, "
                 "%.0f kn: poco per uscire" % (regime, card, other["speed"]))
        coda = "."
    return ('<div class="other">%s%s<br>'
            '<span style="opacity:.85">Questo numero è il vento grezzo dei modelli, '
            'non corretto: la correzione appresa vale per il %s, e oggi il %s non è '
            'quello che soffia.</span></div>'
            % (testa, coda, regime, regime))


def session_row(spot_name, data, scale_max, color):
    spot = config.SPOTS[spot_name]
    win = data["window"]
    # Il modello "raffica di giornata" non prevede un vento medio ma il picco
    # di raffica: presentarlo con le stesse parole dell'Ora farebbe leggere
    # 38 nodi di media dove ci sono 38 nodi di punta.
    daily = spot["target"] == "daily_gust"
    strip = range_strip(data["lo"], data["hi"], data["speed"],
                        spot["planing_kn"], scale_max, color, muted=daily)

    # Quando il regime e' improbabile, l'intensita' mostrata e' condizionata a
    # un evento che quasi certamente non succede: resta scritta per onesta',
    # ma non deve catturare l'occhio, e i dettagli operativi spariscono.
    faint = (not daily) and data["prob"] < 0.30

    conf = data.get("affidabilita") or {}
    # I minuti dipendono SOLO da quanto vale l'orario a questa scadenza, non
    # dall'etichetta complessiva: sono due cose diverse e tenerle legate faceva
    # comparire "08:10" su schede dove l'ora e' incerta di un'ora e mezza.
    mis = (conf.get("componenti") or {}).get("timing_min")
    tvoice = confidence.timing_voice({"timing": {"mae_min": mis}} if mis else None)
    tmbadge = timing_badge(tvoice)
    orario_fine = tvoice["fine"]

    if daily:
        bits = ['<span class="tag">picco di raffica, non media</span>']
        caption = "sopra %d kn" % round(spot["min_kn"])
    else:
        bits = [verdict_chip(data["grade"], data["speed"], data["prob"])]
        ph = data.get("peak_hour")
        mae = data.get("peak_hour_mae_min")
        if ph is not None and data["prob"] >= 0.35 and orario_fine:
            precision = (" ±%d min" % round(mis)) if mis and mis >= 10 else ""
            bits.append('<span class="tag">picco ~%02d:%02d%s</span>'
                        % (int(ph), int(round((ph % 1) * 60 / 15) * 15) % 60, precision))
        # Nessun ramo "else": la voce sull'orario non e' un ripiego di quando
        # i minuti non si possono scrivere, e' una riga che c'e' sempre. Viene
        # aggiunta piu' sotto, accanto all'etichetta di affidabilita'.
        if win and not faint:
            if orario_fine and win.get("from_min") is not None:
                bits.append('<span class="tag">finestra migliore <b>%s–%s</b></span>'
                            % (hhmm(win["from_min"]), hhmm(win["to_min"])))
            else:
                bits.append('<span class="tag">meglio fra le %02d e le %02d</span>'
                            % (win["from"], win["to"]))
            bits.append('<span class="tag">raffiche ~%.0f kn</span>' % win["gust"])
        hint = engine.wing_hint(data["speed"])
        if hint and data["prob"] >= 0.4:
            bits.append('<span class="tag">wing %s</span>' % E(hint))
        caption = "se entrasse" if faint else "che entri"
    dirbit = ""
    if data.get("dir") is not None:
        dirbit = ('<span class="tag">%s da <b>%s</b></span>'
                  % (arrow(data["dir"], 15, "currentColor"), E(compass(data["dir"]))))
    return (
        '<div class="row%s">'
        '<div class="spot"><span class="swatch" style="background:%s"></span>%s</div>'
        '<div>%s</div>'
        '<div class="num"><div class="kn">%.0f <small>kn</small></div>'
        '<div class="pct">%d%% che entri</div>%s</div>'
        '<div class="detail">%s%s%s</div>%s</div>'
        % (" faint" if faint else "", color, E(spot["place"]), strip, data["speed"],
           round(data["prob"] * 100),
           ('<div class="pct">%s</div>' % E(caption)) if caption != "che entri" else "",
           confidence_badge(conf, compact=True) + tmbadge, "".join(bits), dirbit,
           other_wind_note(spot_name, data)))


def day_block(entry, index):
    sessions = entry["sessions"]
    name, date = day_title(entry["day"], entry["lead"])

    scale_max = 5 * math.ceil(max([20.0] + [s["hi"] for s in sessions.values()]) / 5.0)
    colors = {place: ["var(--s1)", "var(--s2)"][i % 2]
              for i, place in enumerate(config.PLACES)}

    blocks, bands = [], []
    for label, regime in SESSION_ORDER:
        members = [(n, sessions[n]) for n in config.SPOT_ORDER
                   if n in sessions and config.SPOTS[n]["regime"] == regime]
        if not members:
            continue
        w0 = min(config.SPOTS[n]["window"][0] for n, _d in members)
        w1 = max(config.SPOTS[n]["window"][1] for n, _d in members)
        if regime != "GIORNO":
            start = w0
            if bands:                      # niente sovrapposizioni fra le fasce
                start = max(start, bands[-1]["to"])
                bands[-1]["to"] = min(bands[-1]["to"], w0 + 1)
            bands.append({"from": start, "to": w1 + 1,
                          "label": label.split("·")[-1].strip()})
        rows = "".join(session_row(n, d, scale_max, colors[config.SPOTS[n]["place"]])
                       for n, d in members)
        blocks.append(
            '<div class="session"><div class="shead"><span class="name">%s</span>'
            '<span class="when">%02d:00 – %02d:00</span></div>%s%s</div>'
            % (E(label), w0, w1 + 1, scale_bar(scale_max), rows))

    profiles = [(place, entry["places"][place]["profile"]) for place in config.PLACES]
    chart = hourly_chart(profiles, bands, "d%d" % index)

    any_s = next(iter(sessions.values()))
    trust = [SOURCE_LABEL.get(any_s["source"], any_s["source"])]
    # L'errore medio si dichiara solo dove e' stato misurato A QUESTA SCADENZA.
    # Prestare il numero di D+0 a un giorno lontano e' il modo piu' elegante di
    # dire una cosa falsa: la cifra e' vera, ma non parla di quel giorno.
    if any_s.get("mae") is not None and any_s.get("validata"):
        trust.append("errore medio fuori campione <b>±%.1f kn</b>" % any_s["mae"])
    elif any_s.get("mae") is not None:
        trust.append("errore misurato solo a giornata in corso (±%.1f kn); "
                     "a questa scadenza non è stato misurato" % any_s["mae"])
    if any_s.get("band_source"):
        trust.append("banda da %s" % E(any_s["band_source"]))
    if any_s.get("peak_hour_mae_min"):
        trust.append("orario del picco <b>±%d min</b>" % round(any_s["peak_hour_mae_min"]))
    trust.append("<b>%d modelli</b> disponibili a questa scadenza" % any_s["n_models"])
    trust.append("pesi %s" % any_s["weights"])

    # L'intestazione del giorno porta il livello PIU' BASSO fra le sessioni
    # mostrate: letta da sola verrebbe presa per un giudizio sul giorno, e non
    # puo' promettere piu' di quanto prometta la riga piu' debole. Il livello
    # per singolo spot-regime resta su ciascuna riga, che e' dove si decide.
    lead_note = confidence_badge(
        confidence.sintesi_giorno([s.get("affidabilita") for s in sessions.values()]))

    return ('<section class="day"><div class="dayhead"><h2 class="display">%s</h2>'
            '<span class="date">%s</span>%s</div>%s%s'
            '<div class="trust">%s</div></section>'
            % (E(name), E(date), lead_note, "".join(blocks), chart, " · ".join(trust)))


def sources_panel():
    """Da dove arriva la previsione: centraline, modelli, pesi effettivi."""
    r = ['<div class="panel"><h2 class="display">Da dove arriva la previsione</h2>']

    r.append("<h3>Centraline · la verità contro cui è calibrato tutto</h3><table>"
             "<tr><th>Stazione</th><th>Fornitore</th><th class='num'>Dati raccolti</th>"
             "<th>Periodo</th></tr>")
    stations = [
        ("T0193", "Torbole (Belvedere), 90 m", "Meteotrentino",
         "https://dati.meteotrentino.it/service.asmx"),
        ("malcesine", "Fraglia Vela Malcesine, 65 m", "MeteoProject",
         "https://stazioni.meteoproject.it/dati/malcesine/"),
    ]
    for station, nome, prov, url in stations:
        st = store.obs_stats(station)
        span = "%s → %s" % ((st["hour_from"] or st["day_from"] or "—")[:10],
                            (st["hour_to"] or st["day_to"] or "—")[:10])
        quanti = ("{:,} ore".format(st["hours"]).replace(",", ".") if st["hours"]
                  else "%d giorni" % st["days"])
        r.append("<tr><td>%s</td><td><a href='%s' target='_blank' rel='noopener'>%s</a></td>"
                 "<td class='num'>%s</td><td>%s</td></tr>"
                 % (E(nome), E(url), E(prov), E(quanti), E(span)))
    r.append("</table>")

    ref = config.SPOT_ORDER[0]
    weights, origin = verify.compute_weights(ref, 1)
    skills = store.skills(ref)
    r.append("<h3>Modelli meteo nell'ensemble</h3><p>%s</p><table>"
             "<tr><th>Modello</th><th>Centro</th><th class='num'>Griglia</th>"
             "<th class='num'>Giorni</th><th class='num'>Peso</th>"
             "<th class='num'>MAE verificato</th></tr>"
             % ("I pesi sono <b>misurati</b>: ogni modello conta quanto ha dimostrato di "
                "valere sulla centralina di Torbole." if origin == "verificato"
                else "I pesi vengono ancora da un prior sulla risoluzione: servono almeno "
                     "%d giorni verificati per misurarli sui dati."
                     % verify.MIN_DAYS_FOR_SKILL))
    centri = {
        "ECMWF IFS": "ECMWF", "ECMWF AIFS": "ECMWF (IA)", "ICON-D2": "DWD",
        "ICON-EU": "DWD", "ICON-2I": "ItaliaMeteo · Arpae",
        "AROME Austria": "GeoSphere Austria", "ICON-CH2": "MeteoSvizzera",
        "ARPEGE Europe": "Météo-France", "HARMONIE": "KNMI", "GFS": "NOAA",
        "UKMO": "Met Office", "GEM": "ECCC",
    }
    reach = {True: "1-3 gg", False: "7 gg"}
    for name, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        m = config.MODELS[name]
        sk = skills.get((name, 1))
        r.append("<tr><td>%s</td><td>%s</td><td class='num'>%s km</td>"
                 "<td class='num'>%s</td><td class='num'>%.0f%%</td>"
                 "<td class='num'>%s</td></tr>"
                 % (E(name), E(centri.get(name, "")), m["res_km"],
                    reach[m["res_km"] < 6], w * 100,
                    ("%.2f kn" % sk["mae"]) if sk and sk.get("mae") else "—"))
    r.append("</table>")

    r.append(
        "<h3>Servizi interrogati</h3><table><tr><th>Servizio</th><th>A cosa serve</th></tr>"
        "<tr><td><a href='https://open-meteo.com/' target='_blank' rel='noopener'>"
        "Open-Meteo · Forecast</a></td>"
        "<td>le previsioni correnti dei %d modelli, ogni ~25 minuti</td></tr>"
        "<tr><td><a href='https://open-meteo.com/en/docs/historical-forecast-api' "
        "target='_blank' rel='noopener'>Open-Meteo · Historical Forecast</a></td>"
        "<td>i predittori storici su cui il modello è addestrato</td></tr>"
        "<tr><td><a href='https://open-meteo.com/en/docs/previous-runs-api' "
        "target='_blank' rel='noopener'>Open-Meteo · Previous Runs</a></td>"
        "<td>misura la skill di ogni modello alle varie scadenze</td></tr>"
        "<tr><td><a href='http://storico.meteotrentino.it/' target='_blank' rel='noopener'>"
        "Meteotrentino · archivio Hydstra</a></td>"
        "<td>la serie a 10 minuti di Torbole dal luglio 2012</td></tr>"
        "<tr><td><a href='https://stazioni.meteoproject.it/dati/malcesine/archivio.php' "
        "target='_blank' rel='noopener'>MeteoProject · archivio intraday</a></td>"
        "<td>Malcesine ogni 15-30 minuti da marzo 2026, vento e raffica in nodi</td></tr>"
        "<tr><td><a href='https://stazioni.meteoproject.it/dati/malcesine/report.php' "
        "target='_blank' rel='noopener'>MeteoProject · report mensili</a></td>"
        "<td>l'archivio giornaliero di Malcesine da agosto 2024</td></tr>"
        "</table>" % len(config.MODELS))

    r.append(
        "<h3>Sulle raffiche</h3><p>Le raffiche <b>previste</b> ci sono per entrambi gli "
        "spot: vengono dai modelli. Quelle <b>misurate</b> sono asimmetriche, e la "
        "ragione è nelle fonti. L'archivio storico di Torbole (2012→) espone solo la "
        "velocità media e la direzione, non il massimo: per Torbole un modello di "
        "raffica addestrato non esiste ancora, e si sta accumulando dal canale in tempo "
        "reale, che invece la raffica ce l'ha. Malcesine ha sia la raffica giornaliera "
        "dal 2024 sia quella intraday dal marzo 2026.</p>")

    r.append("<p>Nessuna previsione altrui viene ricopiata: i modelli grezzi entrano come "
             "ingredienti, la previsione che leggi è ricalcolata qui sul tuo computer e "
             "corretta con lo storico misurato delle due centraline. Di quanto sbaglia "
             "si parla in <a href='/diagnostica'>diagnostica</a>.</p></div>")
    return "".join(r)


def status_line():
    if engine.STATE["running"]:
        return "Aggiornamento · %s" % engine.STATE["phase"], "warn"
    last = store.meta_get("last_update")
    if not last:
        return "Primo avvio: raccolta dati", "warn"
    dt = parse_dt_any(last)
    return ("Aggiornato alle %s" % to_local(dt).strftime("%H:%M"),
            "bad" if engine.STATE["errors"] else "")


def page_home():
    engine.ensure_update(False)
    days = engine.by_day()
    text, cls = status_line()

    if not days:
        body = '<div class="panel"><div class="empty">Sto raccogliendo i dati…</div></div>'
    else:
        first = days[0]["places"]
        now = '<div class="now">%s</div>' % "".join(
            now_card(place, first[place]["live"]) for place in config.PLACES)
        body = now + "".join(day_block(d, i) for i, d in enumerate(days))

    return TEMPLATE % {
        "title": "Garda Wind",
        "css": CSS, "wave": WAVE, "status": E(text), "dotcls": cls,
        "nav": '<a href="/diagnostica">diagnostica</a> · <a href="/aggiorna">aggiorna</a>',
        "body": body + sources_panel(),
        "reload": 8000 if engine.STATE["running"] else 900000,
    }


# --------------------------------------------------------------------------
# Diagnostica
# --------------------------------------------------------------------------

def page_diagnostics():
    def fmt(v, d=2):
        return ("%.*f" % (d, v)) if isinstance(v, (int, float)) else "—"

    r = ['<div class="panel"><h2 class="display">Quanto sbaglia</h2>'
         '<p>Tutti i numeri sono misurati su giorni che il modello non aveva mai visto. '
         'Le metriche calcolate sugli stessi dati usati per imparare sarebbero una '
         'promessa che il modello non può mantenere.</p>'
         "<table><tr><th>Spot</th><th>Addestrato su</th><th>Livello</th>"
         "<th class='num'>Giorni</th>"
         "<th class='num'>MAE fuori campione</th><th class='num'>MAE riferimento</th>"
         "<th class='num'>Brier</th><th class='num'>Climatologia</th>"
         "<th class='num'>Copertura</th><th>In uso</th></tr>"]
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        label = config.SPOTS[name]["label"]
        if not L:
            r.append("<tr><td>%s</td><td colspan='9'>non ancora addestrato</td></tr>" % E(label))
            continue
        m = L["metrics"]
        used = ("<span class='good'>sì</span>" if m.get("usable") else
                "<span class='bad'>solo probabilità</span>" if m.get("usable_occurrence")
                else "<span class='bad'>no, stima fisica</span>")
        src = {"era5": "rianalisi ERA5", "forecast": "archivio previsioni"}.get(
            m.get("source"), m.get("source") or "—")
        r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td>"
                 "<td class='num'>%s</td>"
                 "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                 "<td class='num'>%s</td><td>%s</td></tr>"
                 % (E(label), E(src), E(str(m.get("tier"))), m.get("n") or 0,
                    fmt(m.get("mae")), fmt(m.get("mae_base")),
                    fmt(m.get("brier"), 4), fmt(m.get("brier_base"), 4),
                    ("%.0f%%" % (m["coverage"] * 100)) if m.get("coverage") else "—", used))
    r.append("</table>"
             "<p>Ogni spot mette in gara due addestramenti: uno sull'archivio delle "
             "previsioni (ha i livelli isobarici ma copre ~5 anni) e uno sulla "
             "rianalisi ERA5 (solo superficie, ma dal 2012). Vincono sullo stesso "
             "metro: entrambi vengono valutati dando loro gli ingressi <i>previsti</i>, "
             "quelli che avranno in esercizio. Valutare quello ERA5 sulla rianalisi lo "
             "farebbe sembrare molto più bravo di quanto sia.</p>")

    # --- la tabella per spot x regime x scadenza -------------------------
    # E' il tavolo su cui poggiano le etichette di affidabilita' della prima
    # pagina. Tenerla qui, e non li', e' deliberato: chi deve decidere se
    # caricare la macchina vuole una parola, chi vuole controllare quella parola
    # vuole i numeri, e sono due bisogni diversi. Ma i numeri devono esserci,
    # altrimenti la parola non e' verificabile.
    band_rows = []
    for name in config.SPOT_ORDER:
        for band, _rng in config.LEAD_BANDS:
            L = store.load_learned(name, "daily@" + band)
            if not L:
                continue
            per = (L.get("metrics") or {}).get("per_lead") or {}
            for lead in sorted(per, key=lambda x: int(x)):
                band_rows.append((name, band, int(lead), per[lead]))
    if band_rows:
        r.append(
            "<h3>Scadenza per scadenza: da dove viene l'etichetta di affidabilità</h3>"
            "<p>Ogni riga è una scadenza misurata a sé, con forward chaining "
            "(si addestra sul passato, si prova sul futuro), lambda scelto dentro "
            "il solo periodo di addestramento e calibrazione tarata fuori dal blocco "
            "di prova. <b>ns</b> significa che l'intervallo di confidenza del "
            "guadagno attraversa lo zero: il miglioramento non si distingue dal "
            "rumore e non viene contato.</p>"
            "<table><tr><th>Spot</th><th>Quando</th><th class='num'>Giorni provati</th>"
            "<th class='num'>MAE</th><th class='num'>Grezzo</th>"
            "<th class='num'>Brier</th><th class='num'>Clim.</th>"
            "<th class='num'>Calibr.</th><th class='num'>Orario</th>"
            "<th>Guadagno intensità</th><th>Affidabilità</th></tr>")
        for name, band, lead, e in band_rows:
            inten = e.get("intensity") or {}
            prob = e.get("prob") or {}
            tim = e.get("timing") or {}
            gi = e.get("gain_int") or {}
            val = confidence.assess(name, lead, e)
            gtxt = "—"
            if gi.get("punto") is not None:
                gtxt = "%+.0f%%" % gi["punto"]
                if gi.get("ic_lo") is not None:
                    gtxt += " [%+.0f,%+.0f]" % (gi["ic_lo"], gi["ic_hi"])
                if not gi.get("significativo"):
                    gtxt += " <b>ns</b>"
            r.append("<tr><td>%s</td><td>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td>%s</td><td>%s</td></tr>"
                     % (E(config.SPOTS[name]["label"]),
                        E(confidence.lead_label(lead)), e.get("n_test_days") or 0,
                        fmt(inten.get("mae")), fmt(inten.get("mae_raw")),
                        fmt(prob.get("brier"), 3), fmt(prob.get("brier_base"), 3),
                        fmt(prob.get("calibration_error"), 3),
                        ("±%d min" % round(tim["mae_min"])) if tim.get("mae_min") else "—",
                        gtxt, confidence_badge(val, compact=True)))
        r.append("</table><p>Le etichette non dipendono dall'orizzonte ma da queste "
                 "misure: la stessa scadenza può meritare <i>buona affidabilità</i> su "
                 "uno spot e <i>tendenza</i> su un altro. Le soglie che separano i "
                 "quattro livelli sono una scelta di prodotto, dichiarata in "
                 "<code>confidence.py</code>, ancorata al margine di nodi che cambia "
                 "davvero la decisione di andare in acqua.</p>")
    else:
        r.append("<h3>Scadenza per scadenza</h3><p>Nessuna scadenza è ancora stata "
                 "misurata: serve l'archivio dei predittori per scadenza "
                 "(<code>--backfill</code>), poi <code>--validate</code>. Finché manca, "
                 "ogni giorno oltre oggi è dichiarato <i>outlook</i>.</p>")

    cand_rows = []
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        cands = (L or {}).get("metrics", {}).get("candidates") or []
        for c in cands:
            cand_rows.append((config.SPOTS[name]["label"], c))
    if cand_rows:
        r.append("<h3>I candidati in gara</h3><table><tr><th>Spot</th><th>Sorgente</th>"
                 "<th>Livello</th><th class='num'>Giorni</th><th class='num'>MAE</th>"
                 "<th class='num'>Brier</th><th>Adottabile</th></tr>")
        for label, c in cand_rows:
            r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                     % (E(label), E(str(c.get("source"))), E(str(c.get("tier"))),
                        c.get("n") or 0, fmt(c.get("mae")), fmt(c.get("brier"), 4),
                        "sì" if c.get("usable") else "no"))
        r.append("</table>")

    tim = []
    for name in config.SPOT_ORDER:
        T = store.load_learned(name, "timing")
        if T:
            tim.append((config.SPOTS[name]["label"], T["metrics"]))
    if tim:
        r.append("<h3>Orario del picco</h3><p>Quanto sbaglia l'ora in cui il regime "
                 "tocca il massimo, contro i due riferimenti: l'ora media stagionale e "
                 "l'ora in cui il vento grezzo d'ensemble mette il proprio massimo.</p>"
                 "<table><tr><th>Spot</th><th class='num'>Giorni</th>"
                 "<th class='num'>Errore</th><th class='num'>Climatologia</th>"
                 "<th class='num'>Ensemble grezzo</th><th>In uso</th></tr>")
        for label, m in tim:
            mm = lambda h: ("%d min" % round(h * 60)) if isinstance(h, (int, float)) else "—"
            r.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                     % (E(label), m.get("n") or 0, mm(m.get("mae_hours")),
                        mm(m.get("base_clim_hours")), mm(m.get("base_raw_hours")),
                        "<span class='good'>sì</span>" if m.get("usable")
                        else "<span class='bad'>no</span>"))
        r.append("</table>")
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Le probabilità sono oneste?</h2>'
             '<p>Quando l\'app dichiara 70%, il vento deve essere entrato circa 70 volte '
             'su 100.</p>')
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        rel = (L or {}).get("metrics", {}).get("reliability") or []
        if not rel:
            continue
        r.append("<h3>%s</h3><table><tr><th>Dichiarato</th><th class='num'>Osservato</th>"
                 "<th class='num'>Giorni</th></tr>" % E(config.SPOTS[name]["label"]))
        for b in rel:
            r.append("<tr><td>%.0f–%.0f%%</td><td class='num'>%.0f%%</td>"
                     "<td class='num'>%d</td></tr>"
                     % (b["lo"] * 100, b["hi"] * 100, b["observed"] * 100, b["n"]))
        r.append("</table>")
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Skill dei singoli modelli</h2>')
    found = False
    for name in config.SPOT_ORDER:
        sk = store.skills(name)
        if not sk:
            continue
        found = True
        r.append("<h3>%s</h3><table><tr><th>Modello</th><th class='num'>Scad.</th>"
                 "<th class='num'>Giorni</th><th class='num'>MAE</th>"
                 "<th class='num'>Bias</th><th class='num'>Pendenza</th></tr>"
                 % E(config.SPOTS[name]["label"]))
        for (m, lead), s in sorted(sk.items(),
                                   key=lambda kv: (kv[0][1], kv[1].get("mae") or 99)):
            r.append("<tr><td>%s</td><td class='num'>D+%d</td><td class='num'>%d</td>"
                     "<td class='num'>%.2f</td><td class='num'>%+.2f</td>"
                     "<td class='num'>%.2f</td></tr>"
                     % (E(m), lead, s["n"] or 0, s["mae"] or 0, s["bias"] or 0,
                        s["slope"] or 0))
        r.append("</table>")
    if not found:
        r.append("<p>Servono almeno %d giorni di osservazioni verificate. Finché non ci "
                 "sono, i pesi vengono da un prior sulla risoluzione dei modelli.</p>"
                 % verify.MIN_DAYS_FOR_SKILL)
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Dati e registro</h2><table>'
             "<tr><th>Centralina</th><th class='num'>Campioni</th><th class='num'>Ore</th>"
             "<th>Da</th><th>A</th><th class='num'>Giorni</th></tr>")
    for station in sorted({s["station"] for s in config.SPOTS.values()}):
        st = store.obs_stats(station)
        r.append("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td>"
                 "<td>%s</td><td>%s</td><td class='num'>%d</td></tr>"
                 % (E(station), st["samples"], st["hours"],
                    (st["hour_from"] or "—")[:10], (st["hour_to"] or "—")[:10], st["days"]))
    r.append("</table><table><tr><th>Quando</th><th>Livello</th><th>Ambito</th>"
             "<th>Messaggio</th></tr>")
    for e in store.recent_events(40):
        dt = parse_dt_any(e["ts"])
        r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                 % (to_local(dt).strftime("%d/%m %H:%M") if dt else "—",
                    E(e["level"] or ""), E(e["scope"] or ""), E(e["message"] or "")))
    r.append("</table></div>")

    text, cls = status_line()
    return TEMPLATE % {
        "title": "Diagnostica",
        "css": CSS, "wave": WAVE, "status": E(text), "dotcls": cls,
        "nav": '<a href="/">previsione</a> · <a href="/aggiorna?deep=1">ricalcola</a>',
        "body": "".join(r),
        "reload": 600000,
    }


SHUTDOWN_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Garda Wind</title><style>body{font:16px/1.6 system-ui,-apple-system,sans-serif;
padding:70px 20px;text-align:center;color:#0c1722;background:#dbe9f4}</style></head><body>
<h2>Garda Wind è chiusa.</h2><p>I dati raccolti restano salvati.<br>
Riaprila quando vuoi dall’icona dell’app.</p></body></html>"""


TEMPLATE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>%(title)s</title><style>%(css)s</style></head><body>
<header><div class="wrap"><div class="hbar">
<h1 class="display">Garda Wind<span class="sub">Torbole &amp; Malcesine · Pel&egrave;r e Ora</span></h1>
<div class="status"><span class="dot %(dotcls)s"></span>%(status)s &nbsp;·&nbsp; %(nav)s</div>
</div></div>%(wave)s</header>
<main class="wrap">%(body)s</main>
<footer class="wrap">Previsione ricalcolata in locale e corretta sullo storico delle
centraline. &nbsp;·&nbsp; <a href="/spegni">chiudi Garda Wind</a></footer>
<script>
function gwChart(id,data,W,pl,pr,h0,h1){
  var svg=document.getElementById(id); if(!svg||!data.length) return;
  var tip=document.getElementById(id+'-tip'), cross=document.getElementById(id+'-cross');
  var keys=[]; data.forEach(function(d){Object.keys(d).forEach(function(k){
    if(k!=='h'&&keys.indexOf(k)<0) keys.push(k);});});
  function xOf(h){return pl+(W-pl-pr)*((h-h0)/Math.max(1,h1-h0));}
  function show(pt){
    var r=svg.getBoundingClientRect();
    var sx=(pt.clientX-r.left)/r.width*W, best=data[0], bd=1e9;
    data.forEach(function(d){var dd=Math.abs(xOf(d.h)-sx); if(dd<bd){bd=dd;best=d;}});
    cross.setAttribute('x1',xOf(best.h)); cross.setAttribute('x2',xOf(best.h));
    cross.setAttribute('opacity','.5');
    var h='<b>'+(best.h<10?'0':'')+best.h+':00</b>';
    keys.forEach(function(k){ if(best[k]) h+='<br>'+k+' <b>'+best[k][0]+' kn</b>'+
      ' <span style="opacity:.6">raff '+best[k][1]+' · '+best[k][2]+'</span>';});
    tip.innerHTML=h; tip.style.opacity='1';
    var px=xOf(best.h)/W*r.width;
    tip.style.left=Math.min(Math.max(px-tip.offsetWidth/2,0),r.width-tip.offsetWidth)+'px';
    tip.style.top='0px';
  }
  function hide(){tip.style.opacity='0'; cross.setAttribute('opacity','0');}
  svg.addEventListener('mousemove',show);
  svg.addEventListener('mouseleave',hide);
  svg.addEventListener('touchstart',function(e){show(e.touches[0]);},{passive:true});
  svg.addEventListener('touchmove',function(e){show(e.touches[0]);},{passive:true});
  svg.addEventListener('touchend',hide);
}
setTimeout(function(){location.reload()},%(reload)d);
</script></body></html>"""


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "GardaWind/3.5"

    def log_message(self, *_a):
        pass

    def handle_one_request(self):
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        finally:
            # Un thread per richiesta: la connessione SQLite va chiusa qui,
            # altrimenti si accumulano handle aperti a ogni ricarica.
            store.close()

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/health":
            return self._send(200, "ok", "text/plain; charset=utf-8")
        if u.path == "/aggiorna":
            engine.ensure_update(True)
            self.send_response(302)
            self.send_header("Location", "/diagnostica" if q.get("deep") else "/")
            self.end_headers()
            return
        if u.path == "/spegni":
            self._send(200, SHUTDOWN_PAGE)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if u.path == "/diagnostica":
            return self._send(200, page_diagnostics())
        if u.path == "/api/previsione":
            return self._send(200, json.dumps(engine.full_product(), default=str),
                              "application/json; charset=utf-8")
        if u.path == "/":
            return self._send(200, page_home())
        return self._send(404, "non trovato", "text/plain; charset=utf-8")


def serve(port=None):
    port = port or config.RUNTIME_PORT
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
