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
from .util import clamp, local_day, parse_dt_any, to_local, utc_now

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
/* Un tema solo, scuro. Non e' una preferenza estetica: la pagina si guarda in
   spiaggia all'alba e al tramonto, e un fondo chiaro a quell'ora e' una torcia
   in faccia. Committiamo al buio e lo dipingiamo bene, invece di mantenere due
   temi e curarne male entrambi. */
:root{
  color-scheme:dark;
  --bg-1:#0a121c; --bg-2:#0d1826; --bg-3:#070e16;
  --card:#101a26; --card-2:#16222f; --card-3:#1b2937;
  --ink:#e9f1f8; --ink-2:#9db0c4; --ink-3:#6d8098;
  --line:#1e2c3b; --grid:#1a2734; --axis:#33455a;

  /* Identita' dei due luoghi: colore categorico, assegnato una volta e mai
     riciclato. Validati con lo script sui sei controlli, su questa superficie
     (#101a26), modalita' scura: tutti PASS, banda di luminosita' compresa.
       Torbole  #2e86e0   Malcesine #de7326 */
  --s1:#2e86e0; --s2:#de7326;
  --s1-soft:#1b3f63; --s2-soft:#4a2a12;
  --s1-glow:rgba(46,134,224,.22); --s2-glow:rgba(222,115,38,.20);

  /* La raffica non e' un terzo luogo: e' una seconda misura dello stesso posto.
     Ha un colore suo perche' compare in entrambi i grafici e deve dire sempre
     la stessa cosa, ma la distinzione dalla media NON dipende dal colore:
     tratteggio piu' etichetta diretta. Contro l'arancione di Malcesine la
     separazione in tritanopia e' debole (dE 3.7), ed e' esattamente il caso
     che il tratteggio copre. */
  --gust:#e0559b;

  /* Stati: riservati, mai riusati per una serie, sempre con la parola scritta. */
  --good:#35c97a; --warn:#f0b429; --crit:#f2564d;

  --shadow:0 1px 2px rgba(0,0,0,.55),0 14px 38px rgba(0,0,0,.45);
  --ring:inset 0 0 0 1px var(--line);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
img{max-width:100%}
[hidden]{display:none!important}
body{
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color:var(--ink);
  background:
    radial-gradient(900px 420px at 12% -8%, #13273c 0%, transparent 62%),
    radial-gradient(760px 380px at 88% 0%, #102132 0%, transparent 58%),
    linear-gradient(180deg, var(--bg-1) 0%, var(--bg-2) 40%, var(--bg-3) 100%);
  background-attachment:fixed;
  min-height:100vh;
  -webkit-font-smoothing:antialiased;
}
.display{
  font-family:"Avenir Next","Avenir",Futura,"Gill Sans","Trebuchet MS",system-ui,sans-serif;
  font-weight:700;letter-spacing:-.02em;
}
a{color:var(--s1)}
.wrap{max-width:1180px;margin:0 auto;padding-left:16px;padding-right:16px}

/* ---------------- testa ---------------- */
header{padding-block:20px 6px}
.hbar{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand h1{margin:0;font-size:27px;line-height:1}
.brand h1 em{font-style:normal;color:var(--s1)}
.brand .sub{display:block;font-family:system-ui,sans-serif;font-weight:500;font-size:10.5px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);margin-top:6px}
.status{font-size:12.5px;color:var(--ink-2);text-align:right;line-height:1.5}
.status .when{display:block;color:var(--ink);font-weight:600}
.status .live{display:inline-flex;align-items:center;gap:7px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);flex:none}
.dot.warn{background:var(--warn)}.dot.bad{background:var(--crit)}

/* ---------------- sezione di un luogo ---------------- */
/* Torbole e Malcesine non si distinguono per posizione ma per cornice: bordo e
   alone del proprio colore, nome grande in alto a sinistra. Cosi' nessun
   grafico puo' essere attribuito al posto sbagliato, che era il rischio piu'
   concreto del mostrarli insieme. */
.place{background:var(--card);border-radius:22px;padding:18px;margin-bottom:18px;
  box-shadow:var(--shadow);border:1px solid var(--line);position:relative;overflow:hidden}
.place::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--pc)}
.place.p1{--pc:var(--s1);--pc-soft:var(--s1-soft);--pc-glow:var(--s1-glow)}
.place.p2{--pc:var(--s2);--pc-soft:var(--s2-soft);--pc-glow:var(--s2-glow)}
.place{box-shadow:var(--shadow),0 0 0 1px var(--pc-glow)}
.pgrid{display:grid;grid-template-columns:1fr;gap:16px}
@media (min-width:1000px){
  /* Il grafico e' il contenuto principale; dati e giudizio gli stanno accanto. */
  .pgrid{grid-template-columns:minmax(0,1fr) 320px;gap:22px;align-items:start}
}

/* --- condizioni attuali: un solo riquadro in cima, solo per oggi --- */
.current{background:var(--card);border-radius:22px;padding:18px;margin-bottom:18px;
  box-shadow:var(--shadow);border:1px solid var(--line)}
.current-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  flex-wrap:wrap;margin-bottom:12px}
.current-head h2{margin:0;font-size:21px}
.current-grid{display:grid;grid-template-columns:1fr;gap:12px}
@media (min-width:760px){.current-grid{grid-template-columns:1fr 1fr}}
.current-place{border-radius:15px;padding:14px 15px;background:var(--card-2);
  border:1px solid var(--line);position:relative;overflow:hidden}
.current-place::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--pc)}
.current-place.p1{--pc:var(--s1);--pc-soft:var(--s1-soft);--pc-glow:var(--s1-glow)}
.current-place.p2{--pc:var(--s2);--pc-soft:var(--s2-soft);--pc-glow:var(--s2-glow)}
.placehead{margin-bottom:12px}

/* --- adesso --- */
.pname{display:flex;align-items:center;gap:10px;margin-bottom:2px}
.pname h2{margin:0;font-size:26px;line-height:1}
.pname .mark{width:30px;height:30px;border-radius:9px;flex:none;
  background:var(--pc-soft);display:grid;place-items:center}
.pregimi{font-size:12px;color:var(--ink-3);margin:0 0 14px}
.lbl{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);
  margin:0 0 6px}
.nowbig{display:flex;align-items:center;gap:14px}
.nowbig .v{font-size:44px;line-height:.95;font-weight:700;
  font-family:"Avenir Next",system-ui,sans-serif;letter-spacing:-.03em}
.nowbig .v small{font-size:17px;font-weight:600;color:var(--ink-2);letter-spacing:0}
.nowbig .compass{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-2)}
.nowbig .compass b{color:var(--ink);font-size:16px;display:block;line-height:1.15}
.nowbig .compass small{font-size:12px;color:var(--ink-3)}
.nowgust{font-size:14px;color:var(--ink-2);margin-top:4px}
.nowgust b{color:var(--ink)}
.nowmeta{font-size:12px;color:var(--ink-3);margin-top:8px;display:flex;gap:12px;flex-wrap:wrap}
.nowmeta.stale{color:var(--warn)}
.nowcond{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;padding-top:12px;
  border-top:1px solid var(--line);font-size:13px;color:var(--ink-2)}
.nowcond b{color:var(--ink);font-weight:600}
.novalue{font-size:20px;color:var(--ink-3)}

/* --- colonna 2: il grafico, che viene prima di ogni card --- */
.pchart .lbl{margin-bottom:2px}
.pchart h3{margin:0 0 10px;font-size:15px;font-weight:600;color:var(--ink-2)}
svg.chart{display:block;width:100%;height:auto}
.chartwrap{position:relative}
.tip{position:absolute;pointer-events:none;opacity:0;transition:opacity .12s;
  background:var(--card-3);border:1px solid var(--line);border-radius:10px;padding:7px 10px;
  font-size:12px;box-shadow:var(--shadow);white-space:nowrap;z-index:3;color:var(--ink)}
.legend{display:flex;gap:15px;flex-wrap:wrap;font-size:12px;color:var(--ink-2);margin-top:8px}
/* La riga dello scarto: sta fra il grafico e la legenda perche' e' la
   lettura del grafico, non una didascalia. */
.scarto{margin:10px 0 0;font-size:13.5px;color:var(--ink-2);line-height:1.5}
.scarto b{color:var(--ink-1)}
.legend i{display:inline-block;width:18px;height:0;border-top:3px solid currentColor;
  margin-right:6px;vertical-align:middle}
.legend i.dash{border-top-style:dashed}
.legend i.box{height:9px;border:0;border-radius:2px;vertical-align:-1px}
details.tbl{margin-top:10px;font-size:13px}
details.tbl summary{cursor:pointer;color:var(--ink-3);font-size:12px}
details.tbl .scroller{overflow-x:auto}

/* --- colonna 3: quanto fidarsi e quando andare --- */
.ringrow{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.ringrow .lbl{margin:0 0 2px}
.ringrow .rword{font-size:16px;font-weight:800;line-height:1.1;margin:1px 0 2px}
.ringrow .rtxt{font-size:12.5px;color:var(--ink-3);line-height:1.4}
.ring{flex:none}
.snote{font-size:12px;color:var(--warn);margin:-4px 0 12px;line-height:1.4}
.callout{border-radius:14px;padding:13px 15px;background:var(--card-2);
  border:1px solid var(--line);border-left:3px solid var(--ink-3);margin-bottom:12px}
.callout.go{border-left-color:var(--good);background:color-mix(in srgb,var(--good) 9%,var(--card-2))}
.callout.meh{border-left-color:var(--warn);background:color-mix(in srgb,var(--warn) 9%,var(--card-2))}
.callout.no{border-left-color:var(--ink-3)}
.callout .big{font-size:17px;font-weight:700;line-height:1.2;margin-bottom:3px}
.callout .big.go{color:var(--good)}.callout .big.meh{color:var(--warn)}
.callout .big.no{color:var(--ink-2)}
.callout p{margin:0;font-size:13px;color:var(--ink-2);line-height:1.45}
.halves{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.half{border-radius:12px;padding:11px 12px;background:var(--card-2);border:1px solid var(--line)}
.half .h{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
.half .when{font-size:12px;color:var(--ink-3);font-variant-numeric:tabular-nums;margin-top:1px}
.half .q{display:flex;align-items:center;gap:7px;margin-top:8px;font-weight:700;font-size:14px}
.half .q i{width:9px;height:9px;border-radius:50%;flex:none}
.half .kn{font-size:17px;font-weight:700;margin-top:5px;
  font-family:"Avenir Next",system-ui,sans-serif}
.half .kn small{font-size:12px;color:var(--ink-2);font-weight:600}
.half .win{font-size:12px;color:var(--ink-3);margin-top:3px}
.useful{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0 0;
  padding-top:10px;border-top:1px solid var(--line);font-size:12px;color:var(--ink-2)}
.useful span{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
.useful b{color:var(--ink);font-variant-numeric:tabular-nums}
.q-go i{background:var(--good)}.q-go{color:var(--good)}
.q-meh i{background:var(--warn)}.q-meh{color:var(--warn)}
.q-no i{background:var(--crit)}.q-no{color:var(--crit)}
.q-off i{background:var(--ink-3)}.q-off{color:var(--ink-3)}
.tmline{margin-top:12px;font-size:12.5px;color:var(--ink-2);display:flex;
  align-items:flex-start;gap:8px}
.tmline i{width:7px;height:7px;border-radius:50%;flex:none;background:currentColor;
  margin-top:6px}
.tmline span{flex:1;min-width:0}
.tm-3{color:var(--good)}.tm-2{color:var(--s1)}.tm-1{color:var(--warn)}.tm-0{color:var(--ink-3)}
.tmline b{color:var(--ink)}

/* ---------------- striscia dei cinque giorni ---------------- */
.week{background:var(--card);border-radius:22px;padding:18px;margin-bottom:18px;
  box-shadow:var(--shadow);border:1px solid var(--line)}
.whead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  flex-wrap:wrap;margin-bottom:14px}
.whead h2{margin:0;font-size:21px}
.wlegend{display:flex;gap:14px;font-size:12px;color:var(--ink-2);flex-wrap:wrap}
.wlegend span{display:inline-flex;align-items:center;gap:6px}
.wlegend i{width:9px;height:9px;border-radius:50%}
.days{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.dcard{appearance:none;text-align:left;font:inherit;color:inherit;cursor:pointer;
  background:var(--card-2);border:1px solid var(--line);border-radius:14px;padding:12px;
  display:block;transition:border-color .15s,background .15s}
.dcard:hover{border-color:var(--axis)}
.dcard[aria-current="true"]{border-color:var(--s1);background:color-mix(in srgb,var(--s1) 12%,var(--card-2))}
.dcard .dd{font-size:13px;font-weight:700}
.dcard .dl{font-size:11px;color:var(--ink-3);margin-top:1px}
.dcard .dk{font-size:21px;font-weight:700;margin-top:9px;
  font-family:"Avenir Next",system-ui,sans-serif}
.dcard .dk small{font-size:12px;color:var(--ink-2);font-weight:600}
.dcard .dbest{font-size:12px;color:var(--ink-2);margin-top:2px}
.dcard .dconf{margin-top:9px;display:grid;gap:4px}
.dcard .dconf div{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--ink-3)}
.dcard .dconf i{width:7px;height:7px;border-radius:50%;flex:none}
.cfd-3{background:var(--good)}.cfd-2{background:var(--s1)}
.cfd-1{background:var(--warn)}.cfd-0{background:var(--ink-3)}

/* ---------------- pannelli condivisi con la diagnostica ---------------- */
.panel{background:var(--card);border-radius:20px;padding:18px;margin-bottom:18px;
  box-shadow:var(--shadow);border:1px solid var(--line)}
.panel h2{margin:0 0 8px;font-size:20px}
.panel h3{margin:18px 0 2px;font-size:13.5px}
.panel p{color:var(--ink-2);font-size:13px;margin:6px 0 10px}
.empty{padding:40px 10px;text-align:center;color:var(--ink-3)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 16px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:600}.bad{color:var(--crit);font-weight:600}
.cf{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
  padding:3px 10px;font-size:12.5px;font-weight:800}
.cf::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.cf-alta{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.cf-buona{background:color-mix(in srgb,var(--s1) 18%,transparent);color:var(--s1)}
.cf-tend{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
.cf-out{background:color-mix(in srgb,var(--ink-3) 16%,transparent);color:var(--ink-2)}
.cfline{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px}
.cf-why{font-size:12.5px;color:var(--ink-3)}
footer{padding-block:6px 40px;font-size:12px;color:var(--ink-3);text-align:center}
footer a{color:var(--ink-2)}

@media (max-width:700px){
  .brand h1{font-size:23px}
  .status{text-align:left}
  .place,.week,.panel{padding:14px;border-radius:18px}
  .pname h2{font-size:23px}
  /* Su telefono la parte "adesso" si stringe: e' un dato solo, non merita
     mezzo schermo prima di arrivare al grafico. */
  .nowbig .v{font-size:34px}
  .nowgust{display:inline-block;margin-right:12px}
  .nowmeta{margin-top:4px}
  .nowcond{margin-top:10px;padding-top:10px}
  .pgrid{gap:14px}
  .halves{grid-template-columns:1fr 1fr;gap:10px}
  .half .kn{font-size:16px}
  .days{grid-template-columns:1fr 1fr}
  .whead h2{font-size:18px}
}
@media (max-width:380px){
  .halves{grid-template-columns:1fr}
  .days{grid-template-columns:1fr}
}
"""

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]

SOURCE_LABEL = {
    "appreso": "modello addestrato sullo storico della centralina",
    "misto": "probabilità addestrata, intensità ancora dalla stima fisica",
    "prior": "stima fisica di partenza, non ancora calibrata sui dati",
}

# Quali fonti meritano un avviso in home. "appreso" no: e' il caso normale, e
# scriverlo sarebbe rumore. Le altre due si', perche' il numero grande sullo
# schermo in quel caso NON e' calibrato sui dati di quella centralina, e chi
# guarda ha il diritto di saperlo prima di decidere se caricare la macchina.
# Non e' un dettaglio tecnico da mandare in diagnostica: e' un'avvertenza.
FONTI_DA_DICHIARARE = ("prior", "misto")


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


def hhmm(minutes, step=10):
    """Minuti dalla mezzanotte -> HH:MM, arrotondati al passo.

    L'arrotondamento non e' estetica: scrivere 08:07 suggerirebbe una
    precisione al minuto che l'interpolazione di un profilo orario non ha. Il
    passo di default e' dieci minuti; gli estremi della finestra di ingresso
    usano cinque, perche' vengono da un quantile misurato e non da
    un'interpolazione, e con dieci un intervallo simmetrico si sbilancia.
    Mezzo passo si arrotonda sempre verso l'alto: il round di Python va al
    pari piu' vicino, e su una coppia di estremi si vedeva.
    """
    m = int(math.floor(clamp(minutes, 0.0, 24 * 60 - 1) / float(step) + 0.5) * step)
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


# --------------------------------------------------------------------------
# Home: una sezione per luogo, il grafico prima di ogni card
# --------------------------------------------------------------------------

# Quali regimi ha un luogo. Solo i modelli orari: quello della raffica di
# giornata (Malcesine-Giorno) e' un'altra grandezza - un picco, non una media -
# e teneva in fondo alla pagina un riquadro che diceva la stessa cosa con
# numeri non confrontabili. Vive in diagnostica, dove il confronto e' il punto.
def place_spots(place):
    out = {}
    for name in config.SPOT_ORDER:
        spot = config.SPOTS[name]
        if spot["place"] == place and spot["target"] == "hourly":
            out[spot["regime"]] = name
    return out


META_REGIME = [("PELER", "Pel\u00e8r", "mattina"), ("ORA", "Ora", "pomeriggio")]


def quality(data, spot):
    """Tre livelli, una parola ciascuno, piu' il colore.

    La soglia non e' estetica: "Scarso" vuol dire che il vento non arriva a
    quello che noi stessi chiamiamo "regime entrato", oppure che la probabilita'
    e' cosi' bassa che l'intensita' e' condizionata a un evento che non capita.
    "Buono" richiede DUE cose insieme: sopra la soglia di planata e una
    probabilita' che regga. Fra i due c'e' tutto il resto, che e' "Discreto".
    """
    if not data:
        return "off", "\u2014"
    prob, speed = data.get("prob") or 0.0, data.get("speed") or 0.0
    if prob < 0.35 or speed < spot["min_kn"]:
        return "no", "Scarso"
    if speed >= spot["planing_kn"] and prob >= 0.55:
        return "go", "Buono"
    return "meh", "Discreto"


RING_WORD = {3: "Alta", 2: "Buona", 1: "Tendenza", 0: "Outlook"}
RING_COLOR = {3: "var(--good)", 2: "var(--s1)", 1: "var(--warn)", 0: "var(--ink-3)"}


def reliability_ring(conf, size=54):
    """Quattro tacche, non una percentuale.

    Il riferimento grafico mostrava "80%". Non lo scriviamo, perche' non
    esiste: quello che misuriamo e' se il modello batte i riferimenti banali a
    quella scadenza, non la probabilita' che la previsione sia giusta. Un
    numero col segno di percentuale verrebbe letto come la seconda cosa.
    Quattro tacche piene su quattro dicono quanto sappiamo, e la parola sta
    accanto - dentro non ci sta, e "Tendenza" tagliato a meta' e' peggio che
    non averla.
    """
    liv = int((conf or {}).get("livello") or 0)
    color = RING_COLOR[liv]
    r = size / 2.0 - 5
    cx = cy = size / 2.0
    circ = 2 * math.pi * r
    seg = circ / 4.0
    dash = seg * 0.74                       # un quarto di giro, meno lo stacco
    parts = []
    for i in range(4):
        on = i <= liv
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" '
            'stroke-width="5.5" stroke-linecap="round" stroke-dasharray="%.2f %.2f" '
            'stroke-dashoffset="%.2f"/>'
            % (cx, cy, r, color if on else "var(--line)",
               dash, circ - dash, -(i * seg + (seg - dash) / 2.0)))
    return ('<svg class="ring" width="%d" height="%d" viewBox="0 0 %d %d" '
            'role="img" aria-label="Affidabilit\u00e0 %s" '
            'style="transform:rotate(-90deg)">%s</svg>'
            % (size, size, size, size, E(RING_WORD[liv]), "".join(parts)))


PAROLE_DIR = ["nord", "nord-est", "est", "sud-est",
              "sud", "sud-ovest", "ovest", "nord-ovest"]


def direzione_parole(deg):
    """La provenienza a parole, per chi non legge le sigle a colpo d'occhio."""
    if deg is None:
        return ""
    return PAROLE_DIR[int((deg % 360) / 45.0 + 0.5) % 8]


def sky_words(profile):
    """Cielo e temperatura dai modelli, in due parole e un numero."""
    clouds = [r["cloud"] for r in profile if r.get("cloud") is not None]
    temps = [r["t2m"] for r in profile if r.get("t2m") is not None]
    rain = [r["precip"] for r in profile if r.get("precip") is not None]
    out = {}
    if temps:
        out["tmax"] = max(temps)
    if rain and sum(rain) > 1.0:
        out["sky"] = "pioggia"
    elif clouds:
        c = sum(clouds) / len(clouds)
        out["sky"] = ("sereno" if c < 25 else "poco nuvoloso" if c < 55
                      else "nuvoloso" if c < 85 else "coperto")
    return out


# Le parole dell'eta' del dato, in un posto solo. Le usa Python per costruire
# la pagina e le usa il browser per riscriverle mentre il dato invecchia: se
# stessero in due posti, prima o poi direbbero due cose diverse. Il primo
# limite che l'eta' non supera vince; l'ultimo vale per tutto il resto.
ETA_PAROLE = ((12.0, "adesso"), (180.0, "%d min fa"),
              (None, "dato non recente"))

# Oltre questa eta' il dato non e' piu' "adesso" e la riga si ingiallisce.
ETA_STANTIA_MIN = 45.0


def eta_parole(minuti):
    if minuti is None:
        return "orario sconosciuto"
    for limite, parola in ETA_PAROLE:
        if limite is None or minuti < limite:
            return (parola % round(minuti)) if "%d" in parola else parola
    return ETA_PAROLE[-1][1]


def now_observed_html(live):
    """La parte OSSERVATA delle condizioni attuali: vento, direzione, raffica, ora.

    Sta in una funzione sua perche' e' anche il contenuto che viaggia dentro
    live.json: il processo veloce la costruisce, la pagina la sostituisce, e
    cosi' le parole - i punti cardinali, "da nord-est", "raffica non
    disponibile" - restano definite in un posto solo, qui, invece di essere
    riscritte in JavaScript dove divergerebbero.

    L'eta' non e' inclusa come testo definitivo: c'e' l'ORARIO del campione,
    e l'eta' la calcola chi guarda, quando guarda.
    """
    if not live or live.get("wind") is None:
        return '<div class="novalue nowempty">nessuna lettura</div>'
    hhmm_txt = ""
    dt = parse_dt_any(live.get("ts") or "")
    if dt:
        hhmm_txt = to_local(dt).strftime("%H:%M")
    gust = ('<div class="nowgust">raffica <b>%.0f kn</b></div>' % live["gust"]
            if live.get("gust") else
            '<div class="nowgust" style="color:var(--ink-3)">'
            'raffica non disponibile</div>')
    return (
        '<div class="nowbig"><div class="v">%.0f <small>kn</small></div>'
        '<div class="compass">%s<span><b>%s</b>%s</span></div></div>'
        '%s<div class="nowmeta"><span class="nowage">%s</span>'
        '<span>%s</span></div>'
        % (live["wind"], arrow(live.get("dir"), 26, "var(--pc)"),
           E(compass(live.get("dir")) or "\u2014"),
           ('<small>da %s</small>' % E(direzione_parole(live.get("dir"))))
           if live.get("dir") is not None else "",
           gust,
           E(eta_parole(live.get("age_min"))),
           ("ultimo dato %s" % hhmm_txt) if hhmm_txt else ""))


def place_head(place):
    """Nome del luogo e regimi: identita' della scheda, non dato live."""
    spots = place_spots(place)
    regimi = " · ".join(
        "%s (%s)" % (lab, when) for key, lab, when in META_REGIME if key in spots)
    return (
        '<div class="pname"><span class="mark">%s</span>'
        '<h2 class="display">%s</h2></div>'
        '<p class="pregimi">%s</p>'
        % ('<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">'
           '<path d="M2 11 L8 3 L14 11 Z" fill="var(--pc)"/></svg>',
           E(place), E(regimi)))


def current_conditions_panel(entry):
    """Vento attuale e meteo in alto. Esiste solo per il giorno di oggi."""
    cards = []
    for index, place in enumerate(config.PLACES):
        pl = entry["places"].get(place) or {}
        cards.append(
            '<div class="current-place p%d">%s</div>'
            % (index + 1, now_column(place, index, pl.get("live"), pl.get("profile") or [])))
    return (
        '<section class="current" id="current-panel">'
        '<div class="current-head"><h2 class="display">Vento adesso</h2></div>'
        '<div class="current-grid">%s</div></section>' % "".join(cards))


def peler_useful_line(place, profile, sessions):
    """Durata prevista sopra 8/10/12 kn nella finestra pratica 06-11.

    E' una descrizione della media prevista, non un nuovo giudizio di planata.
    La durata deriva dagli slot orari presenti: nessun campione viene inventato.
    """
    name = place_spots(place).get("PELER")
    if not name or name not in sessions:
        return ""
    vals = sorted((int(r["hour"]), float(r["wind"])) for r in profile
                  if r.get("hour") is not None and r.get("wind") is not None
                  and 6 <= int(r["hour"]) <= 10)
    if not vals:
        return ""
    def longest(threshold):
        best = run = 0
        prev = None
        for hour, wind in vals:
            if wind >= threshold:
                run = run + 1 if prev is not None and hour == prev + 1 else 1
                best = max(best, run)
                prev = hour
            else:
                run = 0
                prev = None
        return best
    return ('<div class="useful"><span>Pelèr utile</span>'
            '<b>≥8: %dh</b><b>≥10: %dh</b><b>≥12: %dh</b></div>'
            % (longest(8), longest(10), longest(12)))


def now_column(place, index, live, profile):
    """Colonna di sinistra: quanto tira ADESSO, con l'ora del dato.

    L'orario dell'ultima lettura non e' un dettaglio tecnico: senza di esso
    "14 kn" e' un numero senza tempo, e a Torbole fra le 11 e le 12 il vento
    cambia del doppio. Quando il dato invecchia, lo diciamo in giallo.

    Il blocco porta con se' il nome del luogo e l'orario del campione: sono le
    due cose che servono per aggiornarlo dopo, nel browser, senza rifare la
    pagina. La previsione si rifa' quattro volte al giorno, il dato osservato
    ogni dieci minuti: tenerli insieme voleva dire far invecchiare l'"adesso"
    alla velocita' della previsione.
    """
    head = place_head(place)
    cond = sky_words(profile)
    bits = []
    if cond.get("tmax") is not None:
        bits.append("<b>%.0f \u00b0C</b> aria" % cond["tmax"])
    if cond.get("sky"):
        bits.append(E(cond["sky"]))
    # Il cielo e la temperatura vengono dai modelli, non dalla centralina:
    # stanno FUORI dal blocco che il processo veloce sostituisce, altrimenti
    # un aggiornamento del dato osservato li cancellerebbe.
    return (
        head +
        '<div class="nowblock" data-live-place="%s" data-ts="%s">'
        '<p class="lbl">Condizioni attuali</p>'
        '<div class="nowobs">%s</div></div>'
        '%s'
        % (E(place), E((live or {}).get("ts") or ""),
           now_observed_html(live),
           ('<div class="nowcond">%s</div>' % " \u00b7 ".join(bits)) if bits else ""))


def scarto_line(profile, osservato):
    """Quanto la realta' sta seguendo la previsione, in una riga.

    Confronta l'ultima ora MISURATA con la previsione della stessa ora - non
    con la previsione del picco, non con la media del giorno: la stessa ora,
    altrimenti si confrontano due cose diverse e lo scarto non vuol dire
    niente.

    Dice due cose e si ferma: di quanti nodi si discosta, e se l'osservato
    sta salendo o scendendo. NON dice "in ritardo di quaranta minuti": un
    ritardo e' una stima di timing, e il timing su questo lago ha appena
    mostrato una semiampiezza di sessanta minuti fuori campione. Quel numero
    va guadagnato con le stesse porte, non scritto perche' suona bene.
    """
    righe = (osservato or {}).get("righe") or []
    if not righe:
        return None
    ultimo = righe[-1]
    if ultimo.get("wind") is None:
        return None
    prev = next((r for r in profile if r.get("hour") == ultimo["hour"]
                 and r.get("wind") is not None), None)
    if prev is None:
        return None
    diff = ultimo["wind"] - prev["wind"]
    tendenza = None
    if len(righe) >= 2 and righe[-2].get("wind") is not None:
        d = ultimo["wind"] - righe[-2]["wind"]
        tendenza = "sale" if d >= 1.0 else ("scende" if d <= -1.0 else "stabile")
    return {"hour": ultimo["hour"], "previsto": prev["wind"],
            "misurato": ultimo["wind"], "scarto": diff, "tendenza": tendenza,
            "raffica_fonte": (osservato or {}).get("raffica_fonte")}


def scarto_words(sc):
    """La riga dello scarto, in italiano. Solo traduzione."""
    if not sc:
        return ""
    verso = ("in linea con la previsione" if abs(sc["scarto"]) < 1.5
             else "%.0f kn %s previsione" % (abs(sc["scarto"]),
                                             "sopra" if sc["scarto"] > 0 else "sotto"))
    coda = {"sale": ", e sta salendo", "scende": ", e sta scendendo",
            "stabile": ", stabile"}.get(sc["tendenza"] or "", "")
    return ("alle %02d:00 previsti <b>%.0f kn</b>, misurati <b>%.0f kn</b>: %s%s"
            % (sc["hour"], sc["previsto"], sc["misurato"], verso, coda))


def place_chart(place, profile, bands, chart_id, oggi=False, osservato=None):
    """La giornata di un luogo: vento medio e raffica.

    oggi: se e' la giornata di oggi, il grafico porta anche una riga verticale
    sull'ora corrente, messa dal browser. Nasce da una domanda che si e'
    rivelata piu' importante della risposta: "perche' il pallino e' alle 7
    mentre ora sono le 14.25?". Il pallino e' il PICCO previsto, ma un punto
    con un numero accanto, su una curva del tempo, si legge come "sei qui" -
    e senza un "sei qui" vero non c'era modo di accorgersi che non lo fosse.

    Due curve, distinte da tratto e da etichetta diretta oltre che dal colore -
    la raffica e' tratteggiata, e resta leggibile anche per chi non separa il
    rosa dall'arancione. Lo sfondo porta le finestre dei due regimi, con il
    nome scritto: "meglio fra le 14 e le 18" si capisce prima guardando dove
    sta la campana che leggendo una riga di testo.
    """
    rows = sorted([r for r in profile if r.get("wind") is not None],
                  key=lambda r: r["hour"])
    if len(rows) < 3:
        return ""
    hours = [r["hour"] for r in rows]
    # Il disegno e' vettoriale e si adatta alla colonna, ma il TESTO dentro si
    # adatta con lui: con un viewBox largo 760 dentro una colonna da 370 px di
    # telefono, un font 11 arriva a schermo a 5 px. La tela e' dimensionata
    # vicino alla larghezza reale sul telefono, cosi' su desktop il grafico si
    # ingrandisce - e le scritte con lui - invece di rimpicciolirsi.
    W, H = 440.0, 280.0
    # pr tiene la parola "raffica" dentro la tela: a 50 usciva dal bordo.
    pl, pr, pt, pb = 28.0, 58.0, 26.0, 50.0
    # L'osservato entra nella scala insieme alla previsione: una raffica
    # misurata piu' alta del previsto deve stare DENTRO il disegno, altrimenti
    # la curva che conta di piu' e' quella che esce dal grafico.
    oss_righe = [r for r in ((osservato or {}).get("righe") or [])
                 if rows[0]["hour"] <= r["hour"] <= rows[-1]["hour"]]
    peak = max([r["gust"] for r in rows]
               + [r[k] for r in oss_righe for k in ("wind", "gust")
                  if r.get(k) is not None]
               + [12.0])
    top = max(15.0, 5 * math.ceil(peak / 5.0))
    step = 5 if top <= 30 else 10

    def x(h):
        return pl + (W - pl - pr) * ((h - hours[0]) / max(1, hours[-1] - hours[0]))

    def y(v):
        return H - pb - (H - pb - pt) * (max(0.0, min(top, v)) / top)

    p = ['<defs><linearGradient id="%s-g" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0%%" stop-color="var(--pc)" stop-opacity=".33"/>'
         '<stop offset="100%%" stop-color="var(--pc)" stop-opacity="0"/>'
         '</linearGradient></defs>' % chart_id]

    for band in bands:
        a, b = max(band["from"], hours[0]), min(band["to"], hours[-1])
        if b <= a:
            continue
        p.append('<rect x="%.1f" y="%g" width="%.1f" height="%.1f" fill="%s" rx="6"/>'
                 % (x(a), pt, x(b) - x(a), H - pb - pt, band["fill"]))
        # Un bordo verticale al confine: due riquadri quasi dello stesso grigio
        # si distinguono male, e sapere DOVE finisce il Peler e comincia l'Ora
        # e' mezza informazione della giornata.
        p.append('<line x1="%.1f" y1="%g" x2="%.1f" y2="%g" stroke="var(--axis)" '
                 'stroke-width="1" stroke-dasharray="3 4" opacity=".7"/>'
                 % (x(a), pt, x(a), H - pb))
        p.append('<text x="%.1f" y="%g" font-size="10.5" font-weight="800" '
                 'letter-spacing=".1em" fill="var(--ink-2)">%s</text>'
                 % (x(a) + 7, pt - 9, E(band["label"].upper())))
        p.append('<text x="%.1f" y="%g" font-size="10" fill="var(--ink-3)">'
                 '%02d\u2013%02d</text>'
                 % (x(a) + 7, pt + 14, band["from"], band["to"]))

    for v in range(0, int(top) + 1, step):
        yy = y(v)
        p.append('<line x1="%g" y1="%.1f" x2="%g" y2="%.1f" stroke="var(--grid)" '
                 'stroke-width="1"/>' % (pl, yy, W - pr, yy))
        # Lo zero non si scrive: sta alla stessa altezza delle ore e alla
        # stessa ascissa della prima, e le due scritte si leggevano insieme -
        # "004" al posto di "0" e "04". Che la linea di base sia zero si vede
        # dalla scala, e una scritta in meno non toglie niente.
        if v == 0:
            continue
        p.append('<text x="%g" y="%.1f" text-anchor="end" font-size="11" '
                 'fill="var(--ink-3)">%d</text>' % (pl - 7, yy + 4, v))

    area = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["wind"])) for r in rows)
    p.append('<polygon points="%.1f,%.1f %s %.1f,%.1f" fill="url(#%s-g)"%s/>'
             % (x(hours[0]), H - pb, area, x(hours[-1]), H - pb, chart_id,
                ' opacity=".45"' if oss_righe else ""))

    # Con l'osservato in scena la previsione si fa piu' tenue: le due linee
    # dicono cose diverse - una e' un'ipotesi, l'altra e' una misura - e la
    # misura deve essere quella che si legge per prima.
    tenue = ' opacity=".5"' if oss_righe else ""
    gust = " ".join("%.1f,%.1f" % (x(r["hour"]), y(r["gust"])) for r in rows)
    p.append('<polyline points="%s" fill="none" stroke="var(--gust)" stroke-width="2" '
             'stroke-dasharray="7 5" stroke-linecap="round"%s/>' % (gust, tenue))
    p.append('<polyline points="%s" fill="none" stroke="var(--pc)" stroke-width="2.8" '
             'stroke-linejoin="round" stroke-linecap="round"%s/>' % (area, tenue))

    # L'OSSERVATO: piu' marcato, e si ferma dove finisce il dato. Non viene
    # prolungato fino a "adesso" ne' interpolato sui buchi: il senso di questa
    # curva e' il confronto, e un confronto con un dato inventato non e' un
    # confronto.
    if oss_righe:
        w_oss = [(r["hour"], r["wind"]) for r in oss_righe if r.get("wind") is not None]
        g_oss = [(r["hour"], r["gust"]) for r in oss_righe if r.get("gust") is not None]
        if len(g_oss) >= 2:
            p.append('<polyline points="%s" fill="none" stroke="var(--gust)" '
                     'stroke-width="2.6" stroke-dasharray="3 3" '
                     'stroke-linecap="round"/>'
                     % " ".join("%.1f,%.1f" % (x(h), y(v)) for h, v in g_oss))
        if len(w_oss) >= 2:
            p.append('<polyline points="%s" fill="none" stroke="var(--pc)" '
                     'stroke-width="3.6" stroke-linejoin="round" '
                     'stroke-linecap="round"/>'
                     % " ".join("%.1f,%.1f" % (x(h), y(v)) for h, v in w_oss))
        # Un punto pieno sull'ultima misura: e' il "fin qui" della realta'.
        if w_oss:
            hh, vv = w_oss[-1]
            p.append('<circle cx="%.1f" cy="%.1f" r="3.6" fill="var(--pc)" '
                     'stroke="var(--card)" stroke-width="2"/>' % (x(hh), y(vv)))
            p.append('<text x="%.1f" y="%.1f" font-size="10.5" font-weight="800" '
                     'fill="var(--pc)" text-anchor="%s">misurato</text>'
                     % (x(hh) + (7 if hh < hours[-1] - 2 else -7), y(vv) + 16,
                        "start" if hh < hours[-1] - 2 else "end"))

    hi = max(rows, key=lambda r: r["wind"])
    op_picco = ' opacity=".55"' if oss_righe else ""
    p.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="var(--pc)" '
             'stroke="var(--card)" stroke-width="2.5"%s/>'
             % (x(hi["hour"]), y(hi["wind"]), op_picco))
    p.append('<text x="%.1f" y="%.1f" font-size="12.5" font-weight="800" '
             'fill="var(--pc)"%s>%.0f kn</text>'
             % (x(hi["hour"]) + 8, y(hi["wind"]) - 8, op_picco, hi["wind"]))
    # Etichette dirette a fine linea. A fine giornata medio e raffica possono
    # arrivare quasi allo stesso valore: le due scritte si sovrapponevano e
    # diventavano illeggibili. Se sono piu' vicine di una riga di testo le
    # separo, tenendo la raffica sopra perche' e' sempre la maggiore.
    last = rows[-1]
    ly_w, ly_g = y(last["wind"]) + 4, y(last["gust"]) + 4
    if abs(ly_w - ly_g) < 13:
        mid = (ly_w + ly_g) / 2.0
        ly_g, ly_w = mid - 6.5, mid + 6.5
    lx = x(last["hour"]) + 6
    p.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="700" '
             'fill="var(--pc)">medio</text>' % (lx, ly_w))
    p.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="700" '
             'fill="var(--gust)">raffica</text>' % (lx, ly_g))

    ay = H - pb + 22
    for r in rows:
        if r["hour"] % 2 or r.get("dir") is None:
            continue
        p.append('<g transform="translate(%.1f %g) rotate(%.0f) scale(.6)" opacity=".7">'
                 '<path d="M0 -9 L0 9 M0 9 L-4.4 3.4 M0 9 L4.4 3.4" fill="none" '
                 'stroke="var(--ink-2)" stroke-width="2.8" stroke-linecap="round" '
                 'stroke-linejoin="round"/></g>'
                 % (x(r["hour"]), ay, (r["dir"] or 0) % 360))

    for h in hours:
        if h % 2 == 0:
            p.append('<text x="%.1f" y="%g" text-anchor="middle" font-size="11" '
                     'fill="var(--ink-3)">%02d</text>' % (x(h), H - pb + 4, h))

    p.append('<line id="%s-cross" x1="0" y1="%g" x2="0" y2="%g" stroke="var(--axis)" '
             'stroke-width="1.5" opacity="0"/>' % (chart_id, pt, H - pb))

    # Il segno dell'ora corrente. Viene disegnato invisibile e lo posiziona il
    # browser: la pagina e' statica e puo' essere vecchia di ore, quindi un
    # "adesso" scritto al momento della costruzione sarebbe un "adesso" falso -
    # lo stesso errore che la Fase 2 ha tolto dalle condizioni attuali.
    if oggi:
        p.append('<line id="%s-now" x1="0" y1="%g" x2="0" y2="%g" '
                 'stroke="var(--ink-2)" stroke-width="1.5" '
                 'stroke-dasharray="2 3" opacity="0"/>' % (chart_id, pt, H - pb))
        p.append('<text id="%s-nowlab" x="0" y="%g" text-anchor="middle" '
                 'font-size="10" font-weight="800" letter-spacing=".08em" '
                 'fill="var(--ink-2)" opacity="0">ADESSO</text>'
                 % (chart_id, H - pb + 36))

    _sc = scarto_line(rows, osservato) if oss_righe else None
    _fonte = (osservato or {}).get("raffica_fonte") or "massimo dell'ora"
    payload = [{"h": r["hour"],
                place: [round(r["wind"], 1), round(r["gust"], 1),
                        compass(r.get("dir"))]} for r in rows]
    body = "".join(
        "<tr><td>%02d:00</td><td class='num'>%.0f</td><td class='num'>%.0f</td>"
        "<td class='num'>%s</td></tr>"
        % (r["hour"], r["wind"], r["gust"], E(compass(r.get("dir")) or "\u2014"))
        for r in rows)

    return (
        '<div class="chartwrap">'
        '<svg class="chart" id="%s" viewBox="0 0 %g %g" role="img" '
        'data-today="%d" data-w="%g" data-pl="%g" data-pr="%g" '
        'data-h0="%g" data-h1="%g" '
        'aria-label="Vento previsto a %s, ora per ora">%s</svg>'
        '<div class="tip" id="%s-tip"></div></div>'
        '%s'
        '<div class="legend">'
        '<span style="color:var(--pc)"><i></i>vento medio</span>'
        '<span style="color:var(--gust)"><i class="dash"></i>raffica</span>'
        '<span style="color:var(--ink-3)"><i class="box" '
        'style="background:currentColor;opacity:.5"></i>finestra del regime</span>'
        '<span>frecce: da dove viene</span>%s</div>'
        '<details class="tbl"><summary>i numeri, ora per ora</summary>'
        '<div class="scroller"><table><tr><th>Ora</th><th class="num">Medio</th>'
        '<th class="num">Raffica</th><th class="num">Da</th></tr>%s</table></div>'
        '</details>'
        # In coda, non chiamata diretta: questo <script> sta nel corpo e
        # gwChart e' definita in fondo alla pagina, quindi una chiamata qui
        # arriva prima della definizione. Era rotto da sempre - "gwChart is
        # not defined" dieci volte per pagina, e il tooltip dei grafici non
        # ha mai funzionato. La coda viene svuotata quando la funzione esiste.
        '<script>(window.gwq=window.gwq||[]).push([%s,%s,%g,%g,%g,%g,%g]);</script>'
        % (chart_id, W, H, 1 if oggi else 0, W, pl, pr, hours[0], hours[-1],
           E(place), "".join(p), chart_id,
           ('<p class="scarto">%s</p>' % scarto_words(_sc)) if _sc else "",
           ('<span>linea piena spessa: misurato (raffica: %s) &middot; '
            'linea tenue: previsto</span>' % E(_fonte)) if oss_righe else "",
           body,
           json.dumps(chart_id), json.dumps(payload), W, pl, pr, hours[0], hours[-1]))


def half_cards(place, sessions):
    """Mattina contro pomeriggio, affiancate, con la stessa grammatica."""
    spots = place_spots(place)
    cards = []
    for key, lab, when in META_REGIME:
        name = spots.get(key)
        data = sessions.get(name) if name else None
        if not data:
            continue
        spot = config.SPOTS[name]
        cls, word = quality(data, spot)
        h0, h1 = spot["window"]
        win = data.get("window")
        # I minuti compaiono SOLO se esiste una finestra di ingresso con
        # copertura misurata a questa scadenza. Senza quella misura si scrive
        # l'ora piena: e' meno preciso ed e' vero, mentre "meglio 14:20-17:40"
        # senza copertura nota e' preciso e non si sa se e' vero.
        ing = data.get("ingresso")
        if win and ing and win.get("from_min") is not None:
            wtxt = "meglio %s\u2013%s" % (hhmm(win["from_min"]), hhmm(win["to_min"]))
        elif win:
            wtxt = "meglio fra le %02d e le %02d" % (win["from"], win["to"])
        else:
            wtxt = "nessuna finestra"
        cards.append(
            '<div class="half"><div class="h">%s \u00b7 %s</div>'
            '<div class="when">%02d:00 \u2013 %02d:00</div>'
            '<div class="q q-%s"><i></i>%s</div>'
            '<div class="kn">%.0f\u2013%.0f <small>kn</small></div>'
            '<div class="win">%s</div></div>'
            % (E(when.upper()), E(lab), h0, h1 + 1, cls, E(word),
               data["lo"], data["hi"], E(wtxt)))
    return '<div class="halves">%s</div>' % "".join(cards) if cards else ""


def best_callout(place, sessions):
    """Una frase: dove sta la giornata. E se non c'e', lo dice."""
    spots = place_spots(place)
    best = None
    for key, lab, when in META_REGIME:
        name = spots.get(key)
        data = sessions.get(name) if name else None
        if not data:
            continue
        spot = config.SPOTS[name]
        cls, _word = quality(data, spot)
        score = (data.get("prob") or 0.0) * min(
            (data.get("speed") or 0.0) / spot["planing_kn"], 1.6)
        if best is None or score > best[0]:
            best = (score, cls, lab, when, data, spot)
    if best is None:
        return ('<div class="callout no"><div class="big no">Nessun dato</div>'
                '<p>Per questo giorno non c\u2019\u00e8 ancora una previsione.</p></div>')
    _score, cls, lab, when, data, spot = best
    if cls == "no":
        return ('<div class="callout no"><div class="big no">Niente da fare</div>'
                '<p>N\u00e9 la mattina n\u00e9 il pomeriggio arrivano a vento '
                'navigabile.</p></div>')
    win = data.get("window") or {}
    gust = (" \u00b7 raffiche fino a <b>%.0f kn</b>" % win["gust"]) if win.get("gust") else ""
    hint = engine.wing_hint(data.get("speed") or 0.0)
    wing = (" \u00b7 wing %s" % E(hint)) if hint and (data.get("prob") or 0) >= 0.4 else ""
    return ('<div class="callout %s"><div class="big %s">Meglio %s</div>'
            '<p>%s fino a <b>%.0f kn</b>%s%s</p></div>'
            % (cls, cls, E("la mattina" if when == "mattina" else "nel pomeriggio"),
               E(lab), data.get("speed") or 0.0, gust, wing))


# La finestra si mostra con i suoi estremi in orologio, non come "±35 min", e
# la sua qualita' con una parola. La percentuale di copertura e' corretta ed e'
# la cosa sbagliata da mettere in home: chiede a chi si sta vestendo di fare
# statistica. Vive in diagnostica, accanto all'errore medio.
# 25 minuti e' il confine fra "posso programmare l'uscita" e "devo tenermi
# largo"; 45 e' la soglia operativa oltre la quale non mostriamo niente.
TIMING_PAROLA = ((25.0, "buona"), (45.0, "moderata"))


def timing_words(half_min):
    """La parola per una semiampiezza, o None se oltre la soglia operativa."""
    for soglia, parola in TIMING_PAROLA:
        if half_min <= soglia:
            return parola
    return None


def timing_line(place, sessions):
    """La seconda voce, indipendente dalla prima: a che ora entra.

    Qui NON compare l'errore medio del modello. Un "\u00b180 min" e' una
    misura vera che come informazione operativa non serve a niente: chi deve
    decidere se partire da casa non sa cosa farne. Al suo posto c'e' la
    finestra di ingresso con la sua COPERTURA misurata - quanti ingressi reali
    cadono davvero dentro - e quando quella misura non esiste, o non batte il
    climatologico, si dichiara la fascia larga e si dice che l'orario e'
    incerto. L'errore medio resta in diagnostica, che e' il posto dove serve.
    """
    spots = place_spots(place)
    best = None
    for key, _lab, _when in META_REGIME:
        name = spots.get(key)
        data = sessions.get(name) if name else None
        if not data:
            continue
        ing = data.get("ingresso")
        if ing and (best is None or ing["half_min"] < best[0]["half_min"]):
            best = (ing, name)
    if best:
        ing = best[0]
        parola = timing_words(ing["half_min"])
        if parola:
            return ('<div class="tmline tm-%d"><i></i><span>Ingresso pi\u00f9 probabile '
                    '<b>%s</b> \u00b7 finestra %s\u2013%s \u00b7 affidabilit\u00e0 timing '
                    '<b>%s</b></span></div>'
                    % (3 if ing["half_min"] <= TIMING_PAROLA[0][0] else 2,
                       hhmm(ing["min"], 5),
                       hhmm(ing["min"] - ing["half_min"], 5),
                       hhmm(ing["min"] + ing["half_min"], 5), E(parola)))
    return ('<div class="tmline tm-1"><i></i><span>Orario <b>incerto</b> \u2014 '
            'vale la fascia, non un\u2019ora precisa</span></div>')


def regime_bands(place):
    """Le finestre dei due regimi, senza sovrapposizioni."""
    spots = place_spots(place)
    fills = {"PELER": "#1a2635", "ORA": "#20303f"}
    out = []
    for key, lab, _when in META_REGIME:
        name = spots.get(key)
        if not name:
            continue
        h0, h1 = config.SPOTS[name]["window"]
        if out and h0 < out[-1]["to"]:
            out[-1]["to"] = h0
        out.append({"from": h0, "to": h1 + 1, "label": lab, "fill": fills[key]})
    return out


def source_note(place, sessions):
    """Se il numero non e' ancora calibrato su quella centralina, lo si dice."""
    fonti = [sessions[n].get("source") for n in place_spots(place).values()
             if n in sessions]
    for key in FONTI_DA_DICHIARARE:
        if key in fonti:
            return '<div class="snote">%s</div>' % E(SOURCE_LABEL[key])
    return ""


def place_section(place, index, entry, visible):
    """Una sezione per luogo: adesso, poi il grafico, poi il giudizio."""
    sessions = entry["sessions"]
    pl = entry["places"][place]
    conf = confidence.sintesi_giorno(
        [sessions[n].get("affidabilita") for n in place_spots(place).values()
         if n in sessions])
    return (
        '<section class="place p%d" data-day="%d" data-place="%s"%s>'
        '<div class="placehead">%s</div>'
        '<div class="pgrid">'
        '<div class="pchart"><p class="lbl">Previsione vento</p>'
        '<h3>%s</h3>%s</div>'
        '<div class="pjudge">'
        '<div class="ringrow">%s<div><p class="lbl">Affidabilit\u00e0</p>'
        '<div class="rword" style="color:%s">%s</div>'
        '<div class="rtxt">%s</div></div></div>%s'
        '%s%s%s%s</div></div></section>'
        % (index + 1, entry["_i"], E(place), "" if visible else " hidden",
           place_head(place),
           E(day_title(entry["day"], entry["lead"])[1]),
           place_chart(place, pl.get("profile") or [], regime_bands(place),
                       "c%d%d" % (entry["_i"], index),
                       oggi=(entry.get("day") == local_day(utc_now())),
                       osservato=pl.get("osservato")),
           reliability_ring(conf),
           RING_COLOR[int((conf or {}).get("livello") or 0)],
           E(RING_WORD[int((conf or {}).get("livello") or 0)]),
           E((conf or {}).get("motivo") or (conf or {}).get("uso") or ""),
           source_note(place, sessions),
           best_callout(place, sessions),
           half_cards(place, sessions),
           peler_useful_line(place, pl.get("profile") or [], sessions),
           timing_line(place, sessions)))


def week_strip(days):
    """Cinque giorni, compatti. Cliccando si cambia il giorno mostrato sopra."""
    cards = []
    for i, entry in enumerate(days):
        sessions = entry["sessions"]
        name, date = day_title(entry["day"], entry["lead"])
        dt = parse_dt_any(entry["day"] + " 12:00:00")
        best = None
        for place in config.PLACES:
            for n in place_spots(place).values():
                d = sessions.get(n)
                if not d:
                    continue
                spot = config.SPOTS[n]
                score = (d.get("prob") or 0) * min(
                    (d.get("speed") or 0) / spot["planing_kn"], 1.6)
                if best is None or score > best[0]:
                    best = (score, d, spot, config.SPOTS[n]["regime"])
        if best:
            _s, d, spot, regime = best
            kn = ('%.0f <small>/ %.0f kn</small>'
                  % (d.get("speed") or 0, (d.get("window") or {}).get("gust")
                     or (d.get("speed") or 0) * 1.35))
            # Il numero e' il migliore dei due luoghi: senza dire QUALE, la
            # riga sarebbe una media di niente.
            bestxt = "%s \u00b7 %s" % (
                spot["place"],
                "meglio la mattina" if regime == "PELER" else "meglio il pomeriggio")
            if quality(d, spot)[0] == "no":
                bestxt = "nessuna finestra"
        else:
            kn, bestxt = "\u2014", ""
        confs = []
        for place in config.PLACES:
            c = confidence.sintesi_giorno(
                [sessions[n].get("affidabilita") for n in place_spots(place).values()
                 if n in sessions])
            liv = int((c or {}).get("livello") or 0)
            confs.append('<div><i class="cfd-%d"></i>%s \u00b7 %s</div>'
                         % (liv, E(place), E(RING_WORD[liv].lower())))
        cards.append(
            '<button class="dcard" type="button" data-goto="%d" aria-current="%s">'
            '<div class="dd">%s</div><div class="dl">%s</div>'
            '<div class="dk">%s</div><div class="dbest">%s</div>'
            '<div class="dconf">%s</div></button>'
            % (i, "true" if i == 0 else "false", E(name),
               "%s %d" % (GIORNI[dt.weekday()][:3], dt.day),
               kn, E(bestxt), "".join(confs)))
    return ('<section class="week"><div class="whead">'
            '<h2 class="display">Previsione 5 giorni</h2>'
            '<div class="wlegend">'
            '<span><i style="background:var(--good)"></i>buono per wing</span>'
            '<span><i style="background:var(--warn)"></i>discreto</span>'
            '<span><i style="background:var(--crit)"></i>scarso</span>'
            '</div></div><div class="days">%s</div></section>'
            % "".join(cards))


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


# La previsione visibile si ferma a cinque giorni. Non e' una semplificazione
# grafica: a sette giorni il Brier del Pel\u00e8r misurato e' 0,240 contro 0,238
# climatologici, cioe' zero. Mostrare quei due giorni sarebbe riempire spazio
# con qualcosa che non sa niente.
MAX_GIORNI = 5


# La riga in testa alla pagina: quanto e' fresco il dato osservato piu' fresco.
# Come per ETA_PAROLE, la tabella sta in un posto solo, perche' la riscrive
# anche il browser mentre il dato invecchia - e se l'intestazione dicesse
# "aggiornati adesso" mentre la scheda sotto dice "tre ore fa", una delle due
# frasi sarebbe una bugia, e chi legge non saprebbe quale.
# (limite in minuti, frase, classe del pallino, unita' del numero)
BANNER_PAROLE = (
    (12.0, "dati reali aggiornati adesso", "", None),
    (60.0, "dati reali aggiornati %d min fa", "", "min"),
    (24 * 60.0, "ultimo dato reale %d ore fa", "warn", "ore"),
    (None, "dati reali non aggiornati", "bad", None),
)


def banner_parole(minuti):
    """(frase, classe) per l'eta' del dato piu' fresco. None = nessuna lettura."""
    if minuti is None:
        return "nessuna lettura dalle centraline", "bad"
    for limite, frase, classe, unita in BANNER_PAROLE:
        if limite is None or minuti < limite:
            if unita == "min":
                return frase % round(minuti), classe
            if unita == "ore":
                return frase % round(minuti / 60.0), classe
            return frase, classe
    return BANNER_PAROLE[-1][1], BANNER_PAROLE[-1][2]


def live_summary(days):
    """Eta' del dato osservato piu' fresco fra le due centraline."""
    if not days:
        return "nessun dato dalle centraline", "bad"
    ages = [pl["live"]["age_min"] for pl in days[0]["places"].values()
            if pl.get("live") and pl["live"].get("age_min") is not None]
    return banner_parole(min(ages) if ages else None)


# Dove la pagina va a cercare il dato osservato. Con un server dietro - l'app
# sul Mac - e' una richiesta a se stessi. Nel sito pubblicato non puo' esserlo:
# GitHub Pages si pubblica tutto insieme, quindi il live.json che sta accanto
# alla pagina si aggiorna solo quando si ricostruisce il sito. L'esportazione
# sostituisce questo valore con l'indirizzo del ramo dedicato.
LIVE_URL = "/live.json"


def _live_vars(attivo=True):
    """I valori che il modello di pagina passa al pezzo di JavaScript dell'adesso.

    Le parole dell'eta' vengono da ETA_PAROLE, che e' anche quello che usa
    Python per scrivere la pagina: una definizione, due consumatori. Il limite
    None diventa null, cioe' "per tutto il resto".
    """
    # Piu' di un indirizzo, provati in ordine. Il primo e' il ramo dedicato,
    # che e' l'unico che si aggiorna fra due ricostruzioni del sito; l'ultimo
    # e' il file accanto alla pagina, scritto quando la pagina e' stata
    # costruita. Se il primo non e' raggiungibile - rete, CORS, ramo non
    # ancora creato - si finisce sul secondo, che e' vecchio ma vero, e la sua
    # eta' si vede. Non ho potuto verificare da qui che raw.githubusercontent
    # mandi l'intestazione CORS giusta: e' documentato che lo faccia, ma
    # "documentato" non e' "provato", e questa catena fa in modo che, se non
    # lo facesse, la pagina peggiori invece di rompersi.
    indirizzi = []
    if attivo:
        indirizzi.append(LIVE_URL)
        if LIVE_URL != "live.json" and not LIVE_URL.startswith("/"):
            indirizzi.append("live.json")
    return {
        "liveurls": json.dumps(indirizzi),
        "livems": int(config.LIVE_REFRESH_MIN * 60000) if attivo else 0,
        "etawords": json.dumps([[lim, parola] for lim, parola in ETA_PAROLE]),
        "bannerwords": json.dumps([[lim, frase, classe, unita]
                                   for lim, frase, classe, unita in BANNER_PAROLE]),
        "stale": ETA_STANTIA_MIN,
    }


def page_home():
    engine.ensure_update(False)
    days = engine.by_day()[:MAX_GIORNI]
    for i, entry in enumerate(days):
        entry["_i"] = i
    text, cls = status_line()
    live_txt, live_cls = live_summary(days)

    if not days:
        body = ('<div class="panel"><div class="empty">Sto raccogliendo i dati\u2026'
                '</div></div>')
    else:
        sezioni = "".join(
            place_section(place, pi, entry, visible=(entry["_i"] == 0))
            for entry in days
            for pi, place in enumerate(config.PLACES))
        body = current_conditions_panel(days[0]) + sezioni + week_strip(days)

    valori = {
        "title": "Garda Wind",
        "css": CSS, "status": E(text), "dotcls": cls,
        "live": E(live_txt), "livecls": live_cls,
        "nav": '<a href="/diagnostica">dati e modelli</a> · <a href="/aggiorna">aggiorna</a>',
        "body": body,
        "reload": 8000 if engine.STATE["running"] else 900000,
    }
    valori.update(_live_vars(True))
    return TEMPLATE % valori

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
    valori = {
        "title": "Diagnostica",
        "css": CSS, "status": E(text), "dotcls": cls,
        "live": "diagnostica", "livecls": "",
        "nav": '<a href="/">previsione</a> · <a href="/aggiorna?deep=1">ricalcola</a>',
        "body": sources_panel() + "".join(r),
        "reload": 600000,
    }
    # La diagnostica non ha blocchi "adesso" da aggiornare: nessuna richiesta.
    valori.update(_live_vars(False))
    return TEMPLATE % valori


SHUTDOWN_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Garda Wind</title><style>body{font:16px/1.6 system-ui,-apple-system,sans-serif;
padding:70px 20px;text-align:center;color:#0c1722;background:#dbe9f4}</style></head><body>
<h2>Garda Wind è chiusa.</h2><p>I dati raccolti restano salvati.<br>
Riaprila quando vuoi dall’icona dell’app.</p></body></html>"""


TEMPLATE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>%(title)s</title><style>%(css)s</style></head><body>
<header><div class="wrap"><div class="hbar">
<div class="brand">
<svg width="38" height="38" viewBox="0 0 38 38" aria-hidden="true">
<path d="M3 27 L13 9 L23 27 Z" fill="var(--s1)"/>
<path d="M17 27 L25 13 L33 27 Z" fill="var(--s2)" opacity=".9"/>
<path d="M2 31 C9 28 14 34 20 31 C26 28 31 33 36 30" fill="none" stroke="var(--ink-3)"
 stroke-width="2" stroke-linecap="round"/></svg>
<h1 class="display">Garda<em>Wind</em><span class="sub">Lago di Garda &middot;
previsioni vento per wing</span></h1>
</div>
<div class="status"><span class="when">%(status)s</span>
<span class="live"><span class="dot %(livecls)s" id="gwdot"></span
><span id="gwlive">%(live)s</span></span><br>%(nav)s</div>
</div></div></header>
<main class="wrap">%(body)s</main>
<footer class="wrap">Previsione corretta sullo storico delle centraline di Torbole e
Malcesine. &nbsp;&middot;&nbsp; <a href="/diagnostica">quanto sbaglia</a>
&nbsp;·&nbsp; <a href="/spegni">chiudi Garda Wind</a></footer>
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
    keys.forEach(function(k){ if(best[k]) h+='<br>medio <b>'+best[k][0]+' kn</b>'+
      ' <span style="opacity:.65">raffica '+best[k][1]+' &middot; '+best[k][2]+'</span>';});
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
/* Svuota la coda dei grafici gia' emessi nel corpo, poi accetta le chiamate
   successive come se la funzione fosse sempre stata li'. */
(window.gwq||[]).forEach(function(a){gwChart.apply(null,a)});
window.gwq={push:function(a){gwChart.apply(null,a)}};
/* La striscia dei giorni cambia il giorno mostrato sopra. Tutti i giorni sono
   gia' nella pagina: nessuna richiesta, funziona anche senza rete. */
document.addEventListener('click',function(ev){
  var b=ev.target.closest ? ev.target.closest('.dcard') : null;
  if(!b) return;
  var i=b.getAttribute('data-goto');
  var cards=document.querySelectorAll('.dcard');
  for(var c=0;c<cards.length;c++)
    cards[c].setAttribute('aria-current', cards[c]===b ? 'true':'false');
  var secs=document.querySelectorAll('.place');
  for(var s=0;s<secs.length;s++)
    secs[s].hidden = (secs[s].getAttribute('data-day')!==i);
  var current=document.getElementById('current-panel');
  if(current) current.hidden = (i!=='0');
  var first=(i==='0' && current) ? current : document.querySelector('.place:not([hidden])');
  if(first) first.scrollIntoView({block:'start',behavior:'smooth'});
});
/* ----------------------------------------------------------------------
   L'ADESSO, separato dalla previsione.

   Due tempi diversi: le centraline ogni dieci minuti, i modelli globali ogni
   sei ore. La pagina nasce con dentro il dato osservato del momento in cui e'
   stata costruita, poi si tiene aggiornata da sola rileggendo un file
   piccolo. Due regole:

     l'eta' si ricalcola sempre dall'ORARIO del campione, ogni mezzo minuto,
     anche senza rete: un dato vecchio deve VEDERSI invecchiare;

     se la richiesta non riesce, non si svuota niente: restano i valori con
     cui la pagina e' nata, con la loro eta' che cresce.

   Le parole dell'eta' arrivano da Python (GW_ETA), non sono riscritte qui:
   due copie della stessa frase prima o poi dicono due cose diverse.
   ---------------------------------------------------------------------- */
var GW_LIVE_URLS=%(liveurls)s, GW_LIVE_MS=%(livems)d, GW_ETA=%(etawords)s,
    GW_BANNER=%(bannerwords)s;
function gwEtaParole(min){
  if(min===null||isNaN(min)) return 'orario sconosciuto';
  for(var i=0;i<GW_ETA.length;i++){
    var lim=GW_ETA[i][0], w=GW_ETA[i][1];
    if(lim===null||min<lim) return w.indexOf('%%d')>=0
      ? w.replace('%%d',String(Math.round(min))) : w;
  }
  return GW_ETA[GW_ETA.length-1][1];
}
function gwBanner(min){
  var el=document.getElementById('gwlive'), dot=document.getElementById('gwdot');
  if(!el) return;
  if(min===null){ el.textContent='nessuna lettura dalle centraline';
                  if(dot) dot.className='dot bad'; return; }
  for(var i=0;i<GW_BANNER.length;i++){
    var lim=GW_BANNER[i][0], f=GW_BANNER[i][1], c=GW_BANNER[i][2], u=GW_BANNER[i][3];
    if(lim===null||min<lim){
      var n = (u==='ore') ? Math.round(min/60) : Math.round(min);
      el.textContent = u ? f.replace('%%d',String(n)) : f;
      if(dot) dot.className='dot'+(c?' '+c:'');
      return;
    }
  }
}
/* L'ora corrente sul grafico di oggi. La calcola il browser, e la calcola
   nell'ora del LAGO: un telefono in un altro fuso mostrerebbe altrimenti una
   riga verticale spostata di ore su un grafico che parla di ore locali. Se il
   browser non sa fare i fusi si ripiega sull'ora locale del dispositivo, che
   per chi e' sul posto e' la stessa. */
function gwOraLago(){
  var d=new Date();
  try{
    var p=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Rome',hour:'2-digit',
      minute:'2-digit',hour12:false}).format(d).split(':');
    var h=parseInt(p[0],10), m=parseInt(p[1],10);
    if(!isNaN(h)&&!isNaN(m)) return h+m/60;
  }catch(e){}
  return d.getHours()+d.getMinutes()/60;
}
function gwNowLine(){
  var ora=gwOraLago();
  var g=document.querySelectorAll('svg.chart[data-today="1"]');
  for(var i=0;i<g.length;i++){
    var svg=g[i];
    var W=parseFloat(svg.getAttribute('data-w')),
        pl=parseFloat(svg.getAttribute('data-pl')),
        pr=parseFloat(svg.getAttribute('data-pr')),
        h0=parseFloat(svg.getAttribute('data-h0')),
        h1=parseFloat(svg.getAttribute('data-h1'));
    var linea=document.getElementById(svg.id+'-now'),
        lab=document.getElementById(svg.id+'-nowlab');
    if(!linea) continue;
    /* Fuori dalla finestra disegnata non si mette una riga al bordo: si
       nasconde. Una riga incollata al margine sinistro alle sei del mattino
       direbbe "sei qui" nel punto sbagliato. */
    if(ora<h0||ora>h1){
      linea.setAttribute('opacity','0');
      if(lab) lab.setAttribute('opacity','0');
      continue;
    }
    var xx=pl+(W-pl-pr)*((ora-h0)/Math.max(1,h1-h0));
    linea.setAttribute('x1',xx.toFixed(1));
    linea.setAttribute('x2',xx.toFixed(1));
    linea.setAttribute('opacity','.85');
    if(lab){ lab.setAttribute('x',xx.toFixed(1)); lab.setAttribute('opacity','.9'); }
  }
}
function gwPaintAge(){
  var now=Date.now(), b=document.querySelectorAll('.nowblock'), fresca=null;
  for(var i=0;i<b.length;i++){
    var el=b[i].querySelector('.nowage'); if(!el) continue;
    var ts=b[i].getAttribute('data-ts'), t=ts?Date.parse(ts):NaN;
    if(isNaN(t)){ el.textContent='orario sconosciuto'; continue; }
    var min=(now-t)/60000;
    if(fresca===null||min<fresca) fresca=min;
    el.textContent=gwEtaParole(min);
    var meta=el.parentNode;
    if(meta&&meta.className.indexOf('nowmeta')>=0)
      meta.className='nowmeta'+(min>%(stale)g?' stale':'');
  }
  /* L'intestazione dice la stessa cosa della scheda piu' fresca, con le sue
     parole: due frasi diverse sullo stesso dato sarebbero una bugia e mezza. */
  if(b.length) gwBanner(fresca);
}
function gwApplyLive(d){
  if(!d||!d.luoghi) return;
  var b=document.querySelectorAll('.nowblock');
  for(var i=0;i<b.length;i++){
    var v=d.luoghi[b[i].getAttribute('data-live-place')];
    if(!v||!v.ts||!v.html) continue;
    /* Non si sostituisce mai con qualcosa di piu' vecchio di quello che c'e'
       gia': un file pubblicato in ritardo non deve far tornare indietro la
       pagina. */
    var vecchio=Date.parse(b[i].getAttribute('data-ts')||''), nuovo=Date.parse(v.ts);
    if(isNaN(nuovo)) continue;
    if(!isNaN(vecchio)&&nuovo<=vecchio) continue;
    var box=b[i].querySelector('.nowobs');
    if(box){ box.innerHTML=v.html; b[i].setAttribute('data-ts',v.ts); }
  }
  gwPaintAge();
}
function gwFetchLive(i){
  i=i||0;
  if(!window.fetch||i>=GW_LIVE_URLS.length) return;
  var b=GW_LIVE_URLS[i];
  var u=b+(b.indexOf('?')<0?'?':'&')+'t='+Math.floor(Date.now()/60000);
  fetch(u,{cache:'no-store'}).then(function(r){
    if(!r.ok) throw new Error('http');
    return r.json();
  }).then(function(d){
    if(d&&d.luoghi) gwApplyLive(d); else gwFetchLive(i+1);
  }).catch(function(){ gwFetchLive(i+1); });
}
gwPaintAge();
gwNowLine();
setInterval(function(){gwPaintAge();gwNowLine();},30000);
if(GW_LIVE_MS>0&&GW_LIVE_URLS.length){
  gwFetchLive(0);
  setInterval(function(){gwFetchLive(0);},GW_LIVE_MS);
  document.addEventListener('visibilitychange',function(){
    if(!document.hidden) gwFetchLive(0);});
}
setTimeout(function(){location.reload()},%(reload)d);
</script></body></html>"""



# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "GardaWind/" + config.APP_VERSION

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
        if u.path == "/live.json":
            from . import live as live_mod
            return self._send(200, json.dumps(live_mod.snapshot(), default=str,
                                              ensure_ascii=False),
                              "application/json; charset=utf-8")
        if u.path == "/api/previsione":
            return self._send(200, json.dumps(engine.full_product(), default=str),
                              "application/json; charset=utf-8")
        if u.path == "/":
            return self._send(200, page_home())
        return self._send(404, "non trovato", "text/plain; charset=utf-8")


def serve(port=None):
    port = port or config.RUNTIME_PORT
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
