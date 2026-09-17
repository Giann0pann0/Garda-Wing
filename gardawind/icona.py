"""L'icona del sito, disegnata in Python puro.

Serve un PNG - iOS vuole un PNG per l'icona sulla schermata iniziale, e le
anteprime dei link in chat pure - e questo progetto non ha dipendenze fuori
dalla libreria standard. Un PNG e' un'intestazione, dei blocchi compressi con
zlib e un CRC: si scrive in trenta righe, e cosi' l'icona nasce dallo stesso
codice del sito invece di essere un file binario nel repository che nessuno
sa piu' come e' stato fatto.

Il disegno: il fondo scuro della pagina, due triangoli - le due sponde, nei
due colori delle localita' - e una riga d'acqua sotto. E' lo stesso marchio
che stava nell'intestazione della pagina di prima.
"""
import struct
import zlib

FONDO = (10, 18, 28)
TORBOLE = (46, 134, 224)
MALCESINE = (222, 115, 38)
ACQUA = (109, 128, 152)


def _chunk(tipo, dati):
    corpo = tipo + dati
    return (struct.pack(">I", len(dati)) + corpo
            + struct.pack(">I", zlib.crc32(corpo) & 0xffffffff))


def _dentro(x, y, tri):
    """Punto dentro un triangolo, col metodo dei segni."""
    (x1, y1), (x2, y2), (x3, y3) = tri

    def segno(ax, ay, bx, by, cx, cy):
        return (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)

    d1 = segno(x, y, x1, y1, x2, y2)
    d2 = segno(x, y, x2, y2, x3, y3)
    d3 = segno(x, y, x3, y3, x1, y1)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def png(lato=180):
    """L'icona come bytes PNG, di lato `lato`."""
    s = lato / 38.0                    # il marchio era disegnato su 38x38
    t1 = ((3 * s, 27 * s), (13 * s, 9 * s), (23 * s, 27 * s))
    t2 = ((17 * s, 27 * s), (25 * s, 13 * s), (33 * s, 27 * s))
    righe = []
    for y in range(lato):
        riga = bytearray([0])          # filtro 0: nessuno
        for x in range(lato):
            c = FONDO
            # angoli arrotondati: fuori dal raggio resta il fondo, che su iOS
            # viene comunque mascherato
            if _dentro(x + .5, y + .5, t2):
                c = MALCESINE
            if _dentro(x + .5, y + .5, t1):
                c = TORBOLE
            if 30 * s <= y < 32.2 * s and 2 * s <= x < 36 * s:
                c = ACQUA
            riga += bytes(c)
        righe.append(bytes(riga))
    idat = zlib.compress(b"".join(righe), 9)
    ihdr = struct.pack(">IIBBBBB", lato, lato, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat) + _chunk(b"IEND", b""))


def manifest(nome, corto=None, colore="#0a121c"):
    """Il manifesto dell'app installabile, come testo JSON."""
    import json
    return json.dumps({
        "name": nome, "short_name": corto or nome, "display": "standalone",
        "start_url": "index.html", "background_color": colore,
        "theme_color": colore,
        "icons": [{"src": "icona-192.png", "sizes": "192x192",
                   "type": "image/png"},
                  {"src": "icona-512.png", "sizes": "512x512",
                   "type": "image/png"}],
    }, ensure_ascii=False, indent=1)
