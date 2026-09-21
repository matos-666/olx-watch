"""What the watcher is hunting. The engine (watcher.py) knows nothing else.

Currently: guitar cabinets, 4x12.

To retarget, replace this file. It must export WATCH with:
    name          label for logs
    queries       OLX search terms; results are merged and deduped by ad id
    category_id   OLX category to search within (the API's search is fuzzy
                  full-text — unscoped, "4x12" returns 4x4 pickups, car
                  radios and scaffolding)
    category_path same category as a URL path, for the HTML fallback
    classify      title -> kind string, or None to drop the ad
    brands        title -> list of brand names, for the alert (optional)
    tags          kind -> alert headline
    good_price    kind -> EUR threshold for the "bom preço" flag (optional)
"""
from __future__ import annotations

import re

FOUR_X_12 = re.compile(r"(?<!\d)4\s*[x×*]\s*12(?!\d)", re.I)
# Model codes meaning 4x12 without saying it: PPC412, AVT412, RS412XJ,
# G412A, MG412A, HTV-412A, 8412 (Marshall Valvestate). A trailing "E" is
# excluded: that's the electro-acoustic suffix (Harley Benton CLJ-412E is
# a 12-string guitar), and no cab code uses it.
MODEL_412 = re.compile(r"(?<![\d.,])(?:[a-z]{1,5}-?|8)412(?!e)[a-z]{0,3}(?!\d)", re.I)
# A bare "412" ("Attax 412") only counts next to a cab word.
BARE_412 = re.compile(r"(?<![\d.,])412(?![\d.,])")
CAB_WORD = re.compile(r"\b(coluna|colunas|cabinet|cab|caixa)\b", re.I)
# Marshall 1960 (A/B/AV/BV/AX/BX/TV/HW) is the 4x12 — sellers often skip "4x12".
MARSHALL_1960 = re.compile(r"(?=.*\bmarshall\b).*\b1960(?:a|b|av|bv|ax|bx|tv|hw)?\b", re.I)
# The guitar itself, e.g. Harley Benton CLJ-412E (a 12-string acoustic).
GUITAR_ITSELF = re.compile(r"\b(guitarra|viola|cordas|strings?)\b|\bac[uú]stic|\bel[eé]c?tric", re.I)
# Buyers and rentals, not sellers.
NOT_FOR_SALE = re.compile(r"\b(compro|procuro|procura-se|aluguer|alugo|aluga-se)\b", re.I)
# A head sold with the cab. "+ <cab>" catches listings that name the head
# only by model code ("AVT150H + MG412A") and never say "head".
_CAB_TOKEN = r"(?:marshall\s+|orange\s+|engl\s+|mesa\s+)?(?:coluna|cab\b|cabinet|[a-z]{0,5}-?412|4\s*[x×]\s*12)"
STACK = re.compile(
    r"\b(head|cabe[çc]a|amplificador|stack|half[\s-]?stack)\b"
    r"|\bcom\s+(?:a\s+)?(?:coluna\s+)?4\s*[x×]\s*12"
    r"|\bmais\s+coluna"
    r"|\+\s*" + _CAB_TOKEN, re.I)
# Accessories *for* a 4x12 rather than the cab itself.
PARTS = re.compile(
    r"^\s*(capa|cover|case|flight|rodas|castores|grelha|grill|tecido|tolex|altifalantes?|speakers?)\b"
    r"|\b(capa|cover|rodas|grelha|altifalantes?|speakers?)\s+(para|p/|de|for)\b", re.I)

_BRANDS = [
    ("Marshall", r"marshall"), ("Orange", r"orange"), ("Peavey", r"peavey"), ("ENGL", r"engl"),
    ("Laney", r"laney"), ("Randall", r"randall"), ("Bugera", r"bugera"),
    ("Harley Benton", r"harley\s*benton"), ("Line 6", r"line\s*6"), ("Vox", r"vox"),
    ("Framus", r"framus"), ("DV Mark", r"dv\s*mark"), ("Hughes & Kettner", r"hughes\s*(?:&|and|e)?\s*kettner|h&k"),
    ("EVH", r"evh"), ("Krank", r"krank"), ("Diezel", r"diezel"), ("Bogner", r"bogner"),
    ("Fender", r"fender"), ("Ampeg", r"ampeg"), ("Blackstar", r"blackstar"), ("Egnater", r"egnater"),
    ("Jet City", r"jet\s*city"), ("Kustom", r"kustom"), ("Crate", r"crate"), ("Hiwatt", r"hiwatt"),
    ("Carvin", r"carvin"), ("Behringer", r"behringer"), ("Palmer", r"palmer"), ("Victory", r"victory"),
    ("Friedman", r"friedman"), ("Soldano", r"soldano"), ("Rivera", r"rivera"), ("Splawn", r"splawn"),
    ("Revv", r"revv"), ("Celestion", r"celestion"),
    # "mesa" is also Portuguese for mixing desk / table — only trust it in context.
    ("Mesa Boogie", r"mesa\s*/?\s*boogie|mesa\s+(?:rectifier|recto|standard|oversized|traditional|road\s*king|dual|triple|mark|thiele|widebody)"),
]
_BRAND_RE = [(n, re.compile(r"(?<![a-z])(?:" + p + r")(?![a-z])", re.I)) for n, p in _BRANDS]


def classify(title: str):
    if NOT_FOR_SALE.search(title):
        return None
    has_cab_word = bool(CAB_WORD.search(title))
    if GUITAR_ITSELF.search(title) and not has_cab_word:
        return None
    is_4x12 = (
        FOUR_X_12.search(title)
        or MODEL_412.search(title)
        or MARSHALL_1960.search(title)
        or (BARE_412.search(title) and has_cab_word)
    )
    if not is_4x12:
        return None
    if PARTS.search(title):
        return "parts"
    if STACK.search(title):
        return "stack"
    return "cab"


def brands_of(title: str) -> list[str]:
    """Every brand named, in title order — a stack is often two brands."""
    found = []
    for name, rx in _BRAND_RE:
        m = rx.search(title)
        if m:
            found.append((m.start(), name))
    # Celestion is the speaker, not the cab maker — only show it if alone.
    names = [n for _, n in sorted(found)]
    if len(names) > 1 and "Celestion" in names:
        names.remove("Celestion")
    return names


WATCH = {
    "name": "Colunas 4x12",
    # "4x12" catches every spelling with the size in it; "412" catches the
    # listings that only give a model code (Orange PPC412, Marshall AVT412).
    "queries": ["4x12", "412"],
    "category_id": 243,  # Lazer › Instrumentos Musicais
    "category_path": "lazer/instrumentos-musicais",
    "classify": classify,
    "brands": brands_of,
    "tags": {
        "cab": "🔊 <b>Coluna 4x12</b>",
        "stack": "🎛️ <b>Cabeça + coluna 4x12</b>",
        "parts": "🔧 Acessório p/ 4x12",
    },
    # Measured on live listings, Sep 2026: standalone cabs median 325 €
    # (n=8, range 120-800); head+cab bundles median 700 € (n=3).
    "good_price": {"cab": 200, "stack": 400},
}
