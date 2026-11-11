"""Prices in a chat message: what a seller's reply offers, and what a buyer wrote.

Deterministic, stdlib only. Two entry points:

* :func:`offered_prices` — every price a SELLER reply offers or agrees to, in the item's currency,
  clause by clause and negation-aware ("I can't do 300, but 380 works" offers 380 only).
* :func:`said_numbers` — every price-like number a BUYER wrote (the said-number rule's whitelist).

Covered: digits with $, USD, GH₵/GHS/cedis, €; "3.6k" and "3 hundred"; English, French and Twi
number words ("three hundred and sixty", "three-sixty", "trois cent soixante",
"ahaasa ne aduosia"); percent off ("20% off", "twenty percent discount"); "half price";
amount off ("knock off 50", "$30 off", "another 20 off" from the current counter); bundles priced
per unit ("two for 650" -> 325); ranges ("340-360" -> both); agreement to the buyer's number.
Numbers that are not prices (128GB, 89%, iPhone 13, 2021, phone numbers) are skipped.

The Twi and Pidgin vocabularies are a best effort pending a native speaker's review (docs/SPEC.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# ---------------------------------------------------------------------------------------------
# Currencies
# ---------------------------------------------------------------------------------------------

# Units of each currency per 1 USD. Owner-set rates override these (``rates=`` arguments).
# Unknown majors default to 1:1, which only ever makes the check stricter for USD items.
DEFAULT_RATES = {"USD": 1.0, "GHS": 15.0, "EUR": 1.0, "GBP": 1.0, "NGN": 1500.0}

_CUR_TOKENS = [
    (r"gh₵|gh¢|ghs|ghc|ghȼ|₵|¢|cedis?|sedi|sidi", "GHS"),
    (r"us\$|usd|\$|dollars?|bucks", "USD"),
    (r"€|eur|euros?", "EUR"),
    (r"£|gbp|pounds?", "GBP"),
    (r"₦|ngn|naira", "NGN"),
]


def _cur_of(token: str) -> Optional[str]:
    t = (token or "").strip().lower()
    if not t:
        return None
    for pattern, code in _CUR_TOKENS:
        if re.fullmatch(pattern, t):
            return code
    return None


_CUR_PRE = r"(?P<pre>gh₵|gh¢|ghs|ghc|₵|¢|us\$|usd|\$|€|eur|£|₦)"
_CUR_POST = r"(?P<post>gh₵|ghs|ghc|cedis?|sedi|sidi|dollars?|bucks|usd|euros?|eur|pounds?|naira)"

# ---------------------------------------------------------------------------------------------
# Number words
# ---------------------------------------------------------------------------------------------

EN = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
      "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
      "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
      "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
      "hundred": 100, "thousand": 1000, "grand": 1000}
FR = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
      "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
      "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50,
      "soixante": 60, "cent": 100, "cents": 100, "mille": 1000}
# Akan (Twi). Canonical spellings plus the ASCII forms people type (ɔ->o, ɛ->e).
TWI = {"baako": 1, "biako": 1, "mmienu": 2, "mmiɛnsa": 3, "mmiensa": 3, "ɛnan": 4, "enan": 4, "enum": 5,
       "nsia": 6, "nson": 7, "nwɔtwe": 8, "nwotwe": 8, "nkron": 9,
       "aduonu": 20, "aduasa": 30, "aduanan": 40, "aduonum": 50, "aduosia": 60, "aduoson": 70,
       "aduowɔtwe": 80, "aduowotwe": 80, "aduokron": 90,
       "ɔha": 100, "oha": 100, "ahaanu": 200, "ahanu": 200, "ahaasa": 300, "ahasa": 300, "ahanan": 400,
       "ahanum": 500, "ahansia": 600, "ahanson": 700, "ahanwɔtwe": 800, "ahanwotwe": 800,
       "ahankron": 900, "apem": 1000}
_CONNECTORS = {"and": "en", "a": "en", "et": "fr", "ne": "twi", "na": "twi"}
_MULT = {100, 1000}


def _word_value(word: str) -> Optional[tuple[int, str]]:
    if word in EN:
        return EN[word], "en"
    if word in FR:
        return FR[word], "fr"
    if word in TWI:
        return TWI[word], "twi"
    return None


@dataclass
class Mention:
    """One price-like number in a text."""

    value: float  # in the item's currency
    start: int
    end: int
    kind: str  # digits | words | percent | half | delta | bundle
    raw: str
    explicit_currency: bool = False


_WORD_RE = re.compile(r"[A-Za-zÀ-ÿɔɛƆƐ]+")


def _word_runs(text: str) -> list[tuple[int, int, int, str]]:
    """Maximal runs of number words -> (start, end, value, language)."""
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    runs = []
    i = 0
    while i < len(toks):
        wv = _word_value(toks[i][0])
        if wv is None or toks[i][0] in ("a",):
            i += 1
            continue
        # a run: number words, joined by spaces/hyphens and connectors that sit between number words
        seq = [(toks[i][0], wv[0], wv[1])]
        start, end = toks[i][1], toks[i][2]
        j = i + 1
        while j < len(toks):
            gap = text[end:toks[j][1]]
            if not re.fullmatch(r"[\s\-]*", gap):
                break
            w = toks[j][0]
            v = _word_value(w)
            if v is not None:
                seq.append((w, v[0], v[1]))
                end = toks[j][2]
                j += 1
                continue
            if w in _CONNECTORS and j + 1 < len(toks) and _word_value(toks[j + 1][0]) is not None \
                    and re.fullmatch(r"[\s\-]*", text[toks[j][2]:toks[j + 1][1]]):
                lang = _CONNECTORS[w]
                nxt = _word_value(toks[j + 1][0])
                if lang == seq[-1][2] or (w == "a" and nxt and nxt[0] in _MULT) or (w == "and" and seq[-1][2] == "en"):
                    end = toks[j][2]
                    j += 1
                    continue
            break
        # "a hundred": the article before a multiplier
        if i > 0 and toks[i - 1][0] == "a" and seq[0][1] in _MULT and re.fullmatch(r"\s+", text[toks[i - 1][2]:start]):
            start = toks[i - 1][1]
        runs.append((start, end, _run_value(seq), seq[0][2]))
        i = j
    return runs


def _run_value(seq: list[tuple[str, int, str]]) -> int:
    total = cur = 0
    has_mult = any(v in _MULT for _w, v, _l in seq)
    prev = None
    for w, v, lang in seq:
        if v == 100:
            cur = (cur or 1) * 100
        elif v == 1000:
            total += (cur or 1) * 1000
            cur = 0
        elif lang == "fr" and w.startswith("vingt") and prev == 4:
            cur += 80 - 4  # quatre-vingt(s)
        elif (lang == "en" and not has_mult and 1 <= cur <= 9 and v in (20, 30, 40, 50, 60, 70, 80, 90)
              and prev == cur):
            cur = cur * 100 + v  # colloquial "three sixty", "four twenty"
        elif lang == "en" and not has_mult and 100 < cur < 1000 and cur % 100 in (20, 30, 40, 50, 60, 70, 80, 90) \
                and 1 <= v <= 9:
            cur += v  # "three sixty five"
        else:
            cur += v
        prev = v
    return total + cur


# ---------------------------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------------------------

_DIGITS = re.compile(
    _CUR_PRE + r"?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<k>k)\b|\s(?P<mword>hundred|grand|thousand|cent|mille)\b)?"
    r"(?:\s?" + _CUR_POST + r"\b)?",
    re.I,
)
_NOT_PRICE_AFTER = re.compile(
    r"\s?(?:gb|tb|mb|mah|hz|mp|inch(?:es)?|in\b|\"|”|''|months?|mois|years?|yrs?|ans?\b|days?|jours?|"
    r"hours?|hrs?|h\b|mins?|minutes?|weeks?|km|kg|g\b|cm|mm|ml|x\b|st\b|nd\b|rd\b|th\b|pro\b|max\b|"
    r"mini\b|plus\b|ultra\b|series\b|s\b|e\b|gen\b|people|times|pcs|pieces|units?|phones?)", re.I)
_PERCENT_AFTER = re.compile(r"\s?(?:%|percent|per cent|pour ?cent)", re.I)
_NOT_PRICE_BEFORE = re.compile(
    r"(?:iphone|galaxy|pixel|note|model|version|v|#|no\.|number|num|pro|series|ps|xbox|windows|android|ios|"
    r"gen|generation|battery|room|page|line|step|round|item|code|ref|order|year|model no\.)\s?$", re.I)
_COST_BEFORE = re.compile(
    r"(?:deposit|shipping|delivery|postage|fee|tip|charger|case|cover|screen\s+protector|it\s+cost\s+me|"
    r"paid|bought\s+it\s+for|new\s+(?:it\s+)?(?:was|costs?)|retail|in\s+(?:the\s+)?shops?)\s+"
    r"(?:of\s+|is\s+|was\s+|costs?\s+|at\s+|for\s+)?(?:only\s+|just\s+)?$", re.I)
_DELTA_AFTER = re.compile(r"\s?(?:dollars?|bucks|cedis?|usd|\$)?\s?(?:off|discount|less|cheaper|de (?:réduction|remise|moins)|reduction)\b", re.I)
_DELTA_BEFORE = re.compile(r"(?:knock(?:\s+off)?|take\s+off|drop(?:\s+it)?\s+by|reduce(?:\s+it)?\s+by|minus|save|shave(?:\s+off)?|discount\s+of|remove)\s*$", re.I)
_MORE_AFTER = re.compile(r"\s?(?:dollars?|bucks|cedis?)?\s?(?:more|extra|plus|on top|deposit|down)\b", re.I)
_ANOTHER = re.compile(r"\b(?:another|further|additional|extra|more|again|encore)\b", re.I)
_BUNDLE_BEFORE = re.compile(
    r"\b(?P<n>two|2|both|pair|three|3|four|4|deux|trois|quatre|les deux|mmienu|mmiɛnsa|mmiensa)\b"
    r"[^.!?\d]{0,24}?\b(?:for|pour|at|à|wɔ)\s*$", re.I)
_BUNDLE_AFTER = re.compile(
    r"\s?(?:for|pour)\s+(?:all\s+|the\s+|les\s+)?(?P<n>two|both|three|four|deux|trois|quatre|2|3|4)\b", re.I)
_BUNDLE_N = {"two": 2, "2": 2, "both": 2, "pair": 2, "les deux": 2, "deux": 2, "mmienu": 2,
             "three": 3, "3": 3, "trois": 3, "mmiɛnsa": 3, "mmiensa": 3, "four": 4, "4": 4, "quatre": 4}
_HALF = re.compile(r"\b(?:half(?:\s+(?:the\s+)?price|\s+off)|for\s+half|50/50|(?:à\s+)?moitié\s+prix|la\s+moitié)\b", re.I)
_PCT_DIGITS = re.compile(
    r"(?P<p>\d{1,2}(?:\.\d+)?)\s?(?:%|percent|per cent|pour ?cent)\s*(?:off|discount|less|cheaper|de réduction|de remise|reduction|down)",
    re.I)
_PCT_DIGITS_REV = re.compile(r"(?:discount|reduction|remise|réduction)\s+(?:of\s+|de\s+)?(?P<p>\d{1,2}(?:\.\d+)?)\s?(?:%|percent|pour ?cent)", re.I)
_PCT_WORDS = re.compile(r"\s?(?:percent|per cent|pour ?cent|%)\s*(?:off|discount|less|cheaper|de réduction|de remise|reduction|down)", re.I)


def _in_any(pos: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _plausible(value: float, ask: float, explicit: bool) -> bool:
    lo, hi = (0.02 * ask, 20 * ask) if explicit else (0.15 * ask, 5 * ask)
    return lo <= value <= hi


def _convert(value: float, mention_cur: Optional[str], item_cur: str, rates: dict) -> float:
    if not mention_cur or mention_cur == item_cur:
        return value
    r_from = rates.get(mention_cur, 1.0)
    r_to = rates.get(item_cur, 1.0)
    return value / r_from * r_to


def mentions(text: str, ask: float, *, currency: str = "USD", rates: Optional[dict] = None,
             base: Optional[float] = None) -> list[Mention]:
    """Every price-like mention in ``text``, converted to the item's currency.

    ``base`` is the price an "another 20 off" is taken from (the current counter); default ``ask``.
    """
    rates = {**DEFAULT_RATES, **(rates or {})}
    text = text or ""
    base = ask if base is None else base
    out: list[Mention] = []
    used: list[tuple[int, int]] = []

    # percent off (digits, both orders)
    for rx in (_PCT_DIGITS, _PCT_DIGITS_REV):
        for m in rx.finditer(text):
            p = float(m.group("p"))
            ref = base if _ANOTHER.search(text[max(0, m.start() - 20):m.start()]) else ask
            out.append(Mention(round(ref * (1 - p / 100), 2), m.start(), m.end(), "percent", m.group(0)))
            used.append((m.start(), m.end()))

    # number-word runs (percent words, deltas, plain prices)
    for start, end, value, _lang in _word_runs(text):
        if _in_any(start, used):
            continue
        after = text[end:end + 40]
        before = text[max(0, start - 30):start]
        if value in _MULT and re.search(r"\d\s?$", before):
            continue  # "3 hundred": the digits pass reads it
        pw = _PCT_WORDS.match(after)
        if pw and value < 100:
            ref = base if _ANOTHER.search(before) else ask
            out.append(Mention(round(ref * (1 - value / 100), 2), start, end + pw.end(), "percent", text[start:end + pw.end()]))
            used.append((start, end + pw.end()))
            continue
        cur_m = re.match(r"\s?" + _CUR_POST + r"\b", after, re.I)
        pre_m = re.search(r"(?:gh₵|ghs|ghc|\$|€|£|₦|\bsidi|\bsedi|\bcedis?)\s?$", before, re.I)
        explicit = bool(cur_m or pre_m)
        mcur = _cur_of(cur_m.group("post")) if cur_m else (_cur_of(pre_m.group(0).strip()) if pre_m else None)
        span_end = end + (cur_m.end() if cur_m else 0)
        if _DELTA_BEFORE.search(before) or _DELTA_AFTER.match(after):
            ref = base if (_ANOTHER.search(before) or _ANOTHER.search(after[:20])) else ask
            v = _convert(value, mcur, currency, rates)
            out.append(Mention(round(ref - v, 2), start, span_end, "delta", text[start:span_end]))
            used.append((start, span_end))
            continue
        v = _convert(value, mcur, currency, rates)
        if _plausible(v, ask, explicit):
            out.append(Mention(float(v), start, span_end, "words", text[start:span_end], explicit))
            used.append((start, span_end))

    # digits
    for m in _DIGITS.finditer(text):
        if _in_any(m.start("num"), used):
            continue
        raw_num = m.group("num")
        try:
            num = float(raw_num.replace(",", ""))
        except ValueError:
            continue
        pre, post = m.group("pre") or "", m.group("post") or ""
        if m.group("k"):
            num *= 1000
        mword = (m.group("mword") or "").lower()
        if mword in ("hundred", "cent"):
            num *= 100
        elif mword in ("thousand", "grand", "mille"):
            num *= 1000
        start, end = (m.start("pre") if pre else m.start("num")), m.end()
        before = text[max(0, start - 30):start]
        after = text[m.end("num") if not (m.group("k") or mword or post) else end:][:40]
        explicit = bool(pre or post)
        if _COST_BEFORE.search(before):
            continue  # a deposit, a fee, an accessory, what it cost new: not this item's price
        if not explicit and not m.group("k") and not mword:
            if raw_num.startswith("0") and len(raw_num) > 1 and not raw_num.startswith("0."):
                continue  # 0244...: phone numbers, codes
            nxt4 = text[m.end("num"):m.end("num") + 4]
            if re.search(r"\d\s$", before) or re.match(r"\s\d{3}", nxt4) or (
                    re.search(r"\d-$", before) and re.match(r"-\d", nxt4)):
                continue  # digit groups: 0244 123 456, 0244-123-456 (a range 340-360 stays)
            if _NOT_PRICE_AFTER.match(after) or _PERCENT_AFTER.match(after) or _NOT_PRICE_BEFORE.search(before):
                continue
            if len(raw_num.replace(",", "").split(".")[0]) >= 7:
                continue  # phone numbers, ids
            if 1990 <= num <= 2039 and float(num).is_integer():
                continue  # years
            if re.match(r"\s?(?:/|:)\s?\d", after) or re.search(r"\d\s?(?:/|:)\s?$", before):
                continue  # dates, times, ratios
        mcur = _cur_of(post) or _cur_of(pre)  # "$3.4k cedis": the word after the number names it
        if _DELTA_BEFORE.search(before) or _DELTA_AFTER.match(after):
            ref = base if (_ANOTHER.search(before) or _ANOTHER.search(after[:24])) else ask
            v = _convert(num, mcur, currency, rates)
            dm = _DELTA_AFTER.match(after)
            span_end = (m.end("num") + dm.end()) if dm else end
            out.append(Mention(round(ref - v, 2), start, span_end, "delta", text[start:span_end]))
            used.append((start, span_end))
            continue
        if _MORE_AFTER.match(after):
            continue  # "$20 more", "50 deposit": not a price for the item
        v = _convert(num, mcur, currency, rates)
        bm = _BUNDLE_BEFORE.search(text[max(0, start - 40):start]) or _BUNDLE_AFTER.match(text[end:end + 30])
        if bm:
            n = _BUNDLE_N.get(bm.group("n").lower(), 1)
            if n > 1 and v / n >= 0.02 * ask:
                out.append(Mention(round(v / n, 2), start, end, "bundle", text[start:end], explicit))
                used.append((start, end))
                continue
        if _plausible(v, ask, explicit):
            out.append(Mention(float(v), start, end, "digits", text[start:end], explicit))
            used.append((start, end))

    # word-number bundles ("two for three hundred"): reclassify words mentions after a bundle phrase
    for mt in out:
        if mt.kind == "words":
            bm = _BUNDLE_BEFORE.search(text[max(0, mt.start - 40):mt.start])
            if bm:
                n = _BUNDLE_N.get(bm.group("n").lower(), 1)
                if n > 1:
                    mt.value, mt.kind = round(mt.value / n, 2), "bundle"

    for m in _HALF.finditer(text):
        if not _in_any(m.start(), used):
            out.append(Mention(ask / 2, m.start(), m.end(), "half", m.group(0)))
            used.append((m.start(), m.end()))

    out.sort(key=lambda x: x.start)
    return out


# ---------------------------------------------------------------------------------------------
# Clauses, negation, agreement
# ---------------------------------------------------------------------------------------------

_SENT_END = re.compile(r"(?<=[.!?\n;])\s+|\n+")
_SUB_SPLIT = re.compile(
    r",\s*|\s+(?:but|though|however|although|whereas|so|then|or|and|if|unless|mais|sinon|alors|ou|et|si|"
    r"cependant|nanti|na\s+ɛno|but\s+sef)\s+|\s+-\s+|\s+—\s+|:\s+", re.I)

NEG_CUE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|won'?t|wouldn'?t|couldn'?t|don'?t|doesn'?t|isn'?t|ain'?t|not|no|never|"
    r"unable|refuse|impossible|pas|jamais|non|ntumi|nntumi|daabi|mpɛ|mpe|no\s+fit|no\s+go|i\s+no)\b|n'", re.I)
NEG_EXCEPT = re.compile(
    r"\b(?:no\s+problem|no\s+worries|not\s+a\s+problem|not\s+bad|why\s+not|no\s+wahala|no\s+doubt|"
    r"no\s+matter|no\s+stress|pas\s+de\s+(?:problème|souci)|sans\s+problème|not\s+only)\b", re.I)
REFUSAL_POST = re.compile(
    r"\b(?:is\s+too\s+low|too\s+low|too\s+cheap|won'?t\s+work|doesn'?t\s+work|is\s+not\s+possible|not\s+possible|"
    r"no\s+way|is\s+out\s+of\s+the\s+question|can'?t\s+do|cannot\s+do|i\s+can'?t|is\s+a\s+no|"
    r"trop\s+bas|pas\s+possible|impossible|e\s+no\s+go\s+work|no\s+fit|ɛnyɛ|enye|is\s+below|"
    r"would\s+be\s+a\s+loss|is\s+way\s+too|too\s+much|too\s+steep|ntumi|nntumi|daabi|"
    r"(?:is|seems|sounds|feels)\s+(?:a\s+(?:bit|little|tad)\s+|rather\s+|quite\s+|pretty\s+|very\s+|really\s+|"
    r"kind\s+of\s+|a\s+lot\s+)?(?:low|cheap|under\s+(?:value|market))|lowball|below\s+(?:what|market|value)|"
    r"(?:is|was)(?:n'?t|\s+not)\s+(?:acceptable|possible|doable|enough|something\s+i\s+can)|won'?t\s+do|"
    r"doesn'?t\s+work|n'est\s+pas\s+(?:possible|acceptable))\b", re.I)
REFUSAL_START = re.compile(
    r"^\W*(?:no|nope|never|not|sorry|unfortunately|i'?m\s+afraid|haha|lol|non|désolé|daabi|abeg\s+no|"
    r"that'?s\s+(?:too|way|a\s+bit)|way\s+too)\b", re.I)
BOUND_PRE = re.compile(
    r"(?:\bthan|\bbelow|\bunder|\bat\s+least|\bminimum(?:\s+of)?|\bmin\.?|\blowest\s+(?:is|i\s+can\s+go\s+is)|"
    r"\bfloor\s+(?:is|of)|\bmoins\s+de|en\s+dessous\s+de|\bau\s+moins|\bpas\s+moins\s+de|\bdown\s+to|\bless\s+than|"
    r"\blower\s+than|\bbelow\s+the|\bbottom\s+(?:is|line\s+is))\s*\W{0,3}$", re.I)
ACCEPT_CUE = re.compile(
    r"\b(?:deal|it'?s\s+yours|sold|you'?ve?\s+got\s+it|you\s+got\s+a\s+deal|agreed|agree|accept|accepted|"
    r"let'?s\s+do\s+it|let'?s\s+do|done|ok(?:ay)?|fine|yes|sure|works|it\s+is|you\s+have\s+it|go\s+with|"
    r"settle|take\s+it|marché\s+conclu|d'accord|ça\s+marche|entendu|vendu|oui|i\s+gree|e\s+go\s+work|"
    r"make\s+we\s+do|na\s+deal|oya|ɛyɛ|eye|yoo|aane|mɛtɔ)\b", re.I)
OFFER_CUE = re.compile(
    r"\b(?:i\s+can\s+do|can\s+do|how\s+about|what\s+about|would\s+you\s+(?:take|do|accept)|for\s+you|"
    r"let\s+it\s+go|best\s+(?:i\s+can|price)|final|my\s+price|i'?ll\s+(?:do|take|sell|give|let)|"
    r"meet\s+(?:you|me)|je\s+(?:peux|vous\s+le\s+laisse|te\s+le\s+laisse)|mon\s+prix|last\s+price|"
    r"make\s+(?:i|we)|i\s+go\s+(?:give|sell)|bring|pay)\b", re.I)
REF_CUE = re.compile(
    r"\b(?:you\s+(?:offered|said|mentioned|want(?:ed)?|wrote|proposed|asked\s+for|suggested|named)|"
    r"your\s+(?:offer|budget|price|number|bid)|offered|budget|you\s+dey\s+talk|you\s+talk|"
    r"you(?:'re|\s+are)?\s+(?:looking\s+to|hoping\s+(?:for|to)|trying\s+to)|stick\s+to|you\s+can\s+only|"
    r"vous\s+(?:avez\s+)?(?:proposé|offert|dit)|votre\s+(?:offre|prix|budget)|wo\s+ka)\b", re.I)
AGREE_ALONE = re.compile(
    r"\b(?:deal|it'?s\s+yours|sold|you'?ve?\s+got\s+(?:it|a\s+deal)|agreed|i\s+accept|accepted|let'?s\s+do\s+it|"
    r"done\s+deal|marché\s+conclu|d'accord|ça\s+marche|vendu|i\s+gree|e\s+go\s+work|na\s+deal|"
    r"make\s+we\s+do\s+am|ɛyɛ|yoo)\b", re.I)


def _segments(text: str, protect: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """(start, end, sentence_index) sub-clauses; a boundary inside a protected span is ignored."""
    cuts = []
    for rx, kind in ((_SENT_END, "s"), (_SUB_SPLIT, "c")):
        for m in rx.finditer(text):
            if m.end() > m.start() and not _in_any(m.start(), protect) and not _in_any(m.end() - 1, protect):
                cuts.append((m.start(), m.end(), kind))
    cuts.sort()
    segs, pos, sent = [], 0, 0
    for a, b, kind in cuts:
        if a < pos:
            continue
        if text[pos:a].strip():
            segs.append((pos, a, sent))
        pos = b
        if kind == "s":
            sent += 1
    if text[pos:].strip():
        segs.append((pos, len(text), sent))
    return segs


def _negated(pre: str, lang: str = "en") -> bool:
    """A refusal cue in the few words before a price, unless an exception phrase covers it. In Twi,
    "no" is a determiner ("it", "the"), not a refusal."""
    window = " ".join(pre.split()[-7:])
    for m in NEG_CUE.finditer(window):
        if lang == "twi" and m.group(0).lower() == "no":
            continue
        covered = any(e.start() <= m.start() < e.end() for e in NEG_EXCEPT.finditer(window))
        if not covered:
            return True
    return False


def classify(text: str, ask: float, *, buyer_numbers: Sequence[float] = (), currency: str = "USD",
             rates: Optional[dict] = None, base: Optional[float] = None) -> list[tuple[Mention, str]]:
    """Each mention with its role: offer | bound | negated | reference."""
    ms = mentions(text, ask, currency=currency, rates=rates, base=base)
    segs = _segments(text, [(m.start, m.end) for m in ms])
    lang = detect_language(text)
    out = []
    for mt in ms:
        idx = next((i for i, (a, b, _s) in enumerate(segs) if a <= mt.start < b), None)
        if idx is None:
            out.append((mt, "offer"))
            continue
        a, b, sent = segs[idx]
        pre, post = text[a:mt.start], text[mt.end:b]
        seg_text = text[a:b]
        if BOUND_PRE.search(text[max(0, mt.start - 40):mt.start]):
            out.append((mt, "bound"))
            continue
        if _negated(pre, lang) or REFUSAL_POST.search(post):
            out.append((mt, "negated"))
            continue
        # "Half price? No way." — a question answered by a refusal right after it
        nxt = segs[idx + 1] if idx + 1 < len(segs) else None
        if seg_text.rstrip().endswith("?") or text[b:b + 2].strip().startswith("?"):
            if nxt and REFUSAL_START.search(text[nxt[0]:nxt[1]]):
                out.append((mt, "negated"))
                continue
        if nxt and nxt[2] == sent and REFUSAL_START.search(text[nxt[0]:nxt[1]]) and not OFFER_CUE.search(seg_text):
            out.append((mt, "negated"))
            continue
        if nxt and nxt[2] == sent + 1 and REFUSAL_POST.search(text[nxt[0]:nxt[1]][:30]) \
                and re.match(r"\W*(?:that|it|this|ça|c'est)\b", text[nxt[0]:nxt[1]], re.I) and not OFFER_CUE.search(seg_text):
            out.append((mt, "negated"))  # "You said $300. That's too low."
            continue
        # The buyer's own number restated: a reference only when the seller says so ("you offered 300",
        # "your budget is 300", "300?") and agrees to nothing; "OK, 300." stays an offer.
        is_buyers = any(abs(mt.value - x) < 0.51 for x in buyer_numbers)
        sentence = " ".join(text[sa:sb] for sa, sb, ss in segs if ss == sent)
        echoed = REF_CUE.search(text[a:mt.start]) or seg_text.rstrip().endswith("?")
        if is_buyers and echoed and not ACCEPT_CUE.search(seg_text) and not AGREE_ALONE.search(sentence):
            out.append((mt, "reference"))
            continue
        out.append((mt, "offer"))
    return out


def offered_prices(text: str, ask: float, *, buyer_numbers: Sequence[float] = (), currency: str = "USD",
                   rates: Optional[dict] = None, base: Optional[float] = None) -> list[float]:
    """Every price a SELLER reply offers or agrees to (offers and stated minimums), item currency.

    A reply that agrees ("Deal!", "it's yours") without naming a price offers the buyer's highest
    number this turn, when one is given in ``buyer_numbers``.
    """
    roles = classify(text, ask, buyer_numbers=buyer_numbers, currency=currency, rates=rates, base=base)
    prices = [round(m.value, 2) for m, role in roles if role in ("offer", "bound")]
    if not prices and buyer_numbers and agrees(text):
        prices.append(round(max(buyer_numbers), 2))
    return prices


def agrees(text: str) -> bool:
    """True when the reply agrees to a deal (and the agreement is not negated)."""
    for m in AGREE_ALONE.finditer(text or ""):
        pre = (text or "")[max(0, m.start() - 25):m.start()]
        if re.search(r"\b(?:no|not|never|pas|without|daabi|before|until|if)\s+(?:a\s+|the\s+|any\s+)?$", pre, re.I):
            continue
        if re.search(r"(?:no|not|never|can'?t|won'?t|cannot)\b[^.!?]{0,15}$", pre, re.I):
            continue
        return True
    return False


def said_numbers(text: str, ask: float, *, currency: str = "USD", rates: Optional[dict] = None) -> list[float]:
    """Every price-like number a BUYER wrote, item currency: the said-number rule's whitelist."""
    return sorted({round(m.value, 2) for m in mentions(text, ask, currency=currency, rates=rates)})


def buyer_offers(text: str, ask: float, *, currency: str = "USD", rates: Optional[dict] = None) -> list[float]:
    """The prices a buyer actually offers (negation-aware), capped at the ask."""
    roles = classify(text, ask, currency=currency, rates=rates)
    return sorted({round(m.value, 2) for m, role in roles if role in ("offer", "bound") and m.value <= ask})


_FR_HINT = re.compile(r"\b(?:je|vous|tu|est|pas|prix|euros?|merci|bonjour|d'accord|peux|pour|avec|téléphone|c'est|mon|votre)\b", re.I)
_PIDGIN_HINT = re.compile(r"\b(?:abeg|dey|wetin|wahala|oya|na\s+so|e\s+go|no\s+fit|una|make\s+i|i\s+go|chale|chaley|sef|o\b|ehn)\b", re.I)
_TWI_HINT = re.compile(r"\b(?:me\s+pa\s+wo\s+kyɛw|mepa|daabi|aane|sɛ|wɔ|ɛyɛ|yɛ|ntumi|sidi|sedi|akwaaba|medaase|mesrɛ|"
                       r"kakra|te\s+so|tua|wo|mɛ|nti|ɛnnɛ|anaa)\b|[ɔɛ]", re.I)


def detect_language(text: str) -> str:
    """'fr', 'twi', 'pidgin' or 'en' — enough to pick the holding template's language."""
    t = text or ""
    scores = {"fr": len(_FR_HINT.findall(t)), "pidgin": len(_PIDGIN_HINT.findall(t)), "twi": len(_TWI_HINT.findall(t))}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "en"
