"""Erzeugt rs485tcp/vfs15_params.json aus der deutschen VF-S15-Anleitung (Kap. 11).

Liest die Parametertabellen spaltenweise über Wortpositionen (PyMuPDF).

    py tools/extract_vfs15_params.py docs/VFS15_Handbuch-Langversion_032013.pdf
"""

import json
import os
import re
import sys

import pymupdf

FIRST_PAGE, LAST_PAGE = 280, 310          # PDF-Seiten mit den Parametertabellen
HEADER_WORDS = {
    "comm": "Kommunikations-", "func": "Funktion", "unit": "Einheit", "res": "Auflösung",
    "range": "Einstellbereich", "default": "Grundein-", "user": "Benutzer-",
}
TITLE_RE = re.compile(r"^(f\d{3}|[a-z]{2,4}\d?)$")
COMM_RE = re.compile(r"^\d{4}$")
RES_RE = re.compile(r"^\d[\d,.]*/\d[\d,.]*$")
OUT = os.path.join(os.path.dirname(__file__), "..", "rs485tcp", "vfs15_params.json")


def join_words(words):
    """Wörter zeilenweise zusammensetzen, Trennstriche am Zeilenende auflösen."""
    lines = {}
    for w in sorted(words, key=lambda w: (round(w[1] / 2), w[0])):
        lines.setdefault(round(w[1] / 2), []).append(w[4])
    text = ""
    for parts in lines.values():
        line = " ".join(parts)
        if text.endswith("\xad") or (text.endswith("-") and line[:1].islower()):
            text = text[:-1] + line
        else:
            text = f"{text} {line}".strip()
    text = re.sub(r"\xad\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_options(text):
    """'0: Klemmleiste 1: Tastenblock ...' -> {"0": "Klemmleiste", "1": "Tastenblock ..."}."""
    parts = re.split(r"(?:(?<=\s)|^)(\d{1,3}(?:\s*,\s*\d{1,3})*)\s*:\s", text)
    options = {}
    for i in range(1, len(parts) - 1, 2):
        label = parts[i + 1].strip(" -")
        for key in re.split(r"\s*,\s*", parts[i]):
            options[key] = label
    return options


def clean_heading(text):
    """Gruppenüberschrift säubern; None, wenn es keine ist (z. B. Tabellenzeile)."""
    text = re.sub(r"[^\wäöüÄÖÜß/ ()-]", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+11$", "", text)           # Kapitelreiter "11" am Seitenrand
    if "arameter" not in text or re.search(r"\b\d{4}\b|\bf\d{3}\b", text):
        return None
    return text


def parse_scale(res):
    """'0,1/0,01' -> 0.01 (Auflösung serielle Kommunikation)."""
    m = re.search(r"/\s*([\d,]+)", res or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def headers_on_page(words):
    """Alle Tabellenköpfe auf der Seite: (y_unten, Spalten-x, Gruppenüberschrift)."""
    heads = []
    for w in words:
        if w[4] != HEADER_WORDS["comm"]:
            continue
        y = w[1]
        row = [v for v in words if abs(v[1] - y) < 12]
        cols = {"title": min((v[0] for v in row if v[4].startswith("Bezeich")), default=w[0] - 35)}
        for key, label in HEADER_WORDS.items():
            hit = [v[0] for v in row if v[4] == label]
            if hit:
                cols[key] = min(hit)
        bottom = max(v[3] for v in words if abs(v[1] - y) < 14)
        above = [v for v in words if y - 30 < v[1] < y - 3 and v[0] < cols.get("res", 200)
                 and v[4] not in ("Frequenzumrichter", "VF-S15")]
        heads.append((bottom, cols, join_words(above)))
    return sorted(heads)


def extract(pdf):
    doc = pymupdf.open(pdf)
    params, group = {}, ""
    for pno in range(FIRST_PAGE - 1, LAST_PAGE):
        words = [w for w in doc[pno].get_text("words") if w[1] > 15]
        heads = headers_on_page(words)
        for i, (top, cols, heading) in enumerate(heads):
            heading = clean_heading(heading)
            if heading:
                group = heading
            bottom = heads[i + 1][0] - 40 if i + 1 < len(heads) else 10_000
            if "func" not in cols or "res" not in cols:
                continue
            x = cols
            body = [w for w in words if top < w[1] < bottom]
            # Überschriften stehen mittig über den Spalten -> Grenzen aus den Daten ableiten
            nums = [w for w in body if COMM_RE.match(w[4]) and x["comm"] - 5 <= w[0] <= x["comm"] + 30]
            func_lo = max((w[2] for w in nums), default=x["func"] - 15) + 1.5
            res_lo = min(v for k, v in x.items() if k == "res") - 3
            bounds = [
                ("title", 0, x["comm"] - 4),
                ("comm", x["comm"] - 4, func_lo),
                ("func", func_lo, x["unit"] + 2),
                ("unit", x["unit"] + 2, res_lo),
                ("res", res_lo, x["default"] - 3),      # wird unten in res/range getrennt
                ("default", x["default"] - 3, x.get("user", x["default"] + 25) - 3),
            ]
            col_of = {}
            for w in body:
                for name, lo, hi in bounds:
                    if lo <= w[0] < hi:
                        dash = w[4] in ("-", "–") and w[0] < res_lo + 25
                        if name == "res" and not (RES_RE.match(w[4]) or dash):
                            name = "range"
                        col_of[id(w)] = name
                        break
            bounds.append(("range", 0, 0))
            anchors = sorted((w for w in body if col_of.get(id(w)) == "comm" and COMM_RE.match(w[4])),
                             key=lambda w: w[1])
            for k, a in enumerate(anchors):
                y0 = a[1] - 4.5
                y1 = anchors[k + 1][1] - 4.5 if k + 1 < len(anchors) else bottom
                cells = {n: [] for n, _lo, _hi in bounds}
                for w in body:
                    if y0 <= w[1] < y1 and id(w) in col_of:
                        cells[col_of[id(w)]].append(w)
                title = next((w[4] for w in cells["title"] if TITLE_RE.match(w[4])), "")
                comm = a[4]
                if comm in params:
                    continue
                res = join_words(cells["res"])
                rng = join_words(cells["range"])
                params[comm] = {
                    "comm": comm,
                    "title": title,
                    "name": join_words(cells["func"]),
                    "unit": join_words(cells["unit"]).strip("- ") or "",
                    "resolution": res,
                    "scale": parse_scale(res),
                    "range": rng,
                    "options": parse_options(rng),
                    "signed": bool(re.match(r"^-\d", rng)) or "+" in rng,
                    "default": join_words(cells["default"]),
                    "group": group,
                    "page": pno + 1,
                }
    return [params[k] for k in sorted(params)]


if __name__ == "__main__":
    data = extract(sys.argv[1])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(data)} Parameter -> {os.path.normpath(OUT)}")
