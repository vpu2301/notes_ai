"""One name, one spelling: a read-time overlay, never a rewrite of the artefact (ADR-0061).

Pure: :func:`plan` proposes corrections from a transcript and its priors (glossary,
calendar, hint); :func:`apply` returns a copy with the accepted ones applied.
Mentions cluster by phonetic key (Kölner / Double Metaphone / KMU romanisation) and
Jaro–Winkler; at most one anchor per cluster; common words join only with a glossary
or calendar canonical. Canonical: glossary > calendar > hint > majority.
Status: source or confidence ≥ 0.80 → accepted; 0.60–0.80 with support ≥ 3 → proposed.
Returns text to its caller; logs nothing.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any, Literal

from asr_models import Segment, TranscriptionOutput, WordTiming

Source = Literal["glossary", "calendar", "hint", "majority", "user"]
Status = Literal["proposed", "accepted", "rejected"]

ACCEPT_AT = 0.80
PROPOSE_AT = 0.60
PROPOSE_MIN_SUPPORT = 3
MIN_SUPPORT = 2
JW_MERGE = 0.85
JW_KEY_GUARD = 0.70
ANCHOR_MARGIN = 0.05
LENGTH_RATIO = 0.7
MIN_LETTERS = 3
SOURCE_CONFIDENCE: dict[str, float] = {"glossary": 0.95, "calendar": 0.90, "hint": 0.85}
TO_TEXT_MAX = 80

# Kept in step with note-service glossary.ROLE_WORDS (asserted against the fixture).
ROLE_WORDS: frozenset[str] = frozenset(
    {
        "speaker", "moderator", "host", "narrator", "guest", "interviewer", "interviewee",
        "presenter", "caller", "background", "unknown", "voice", "participant", "translator",
        "announcer", "sprecher", "sprecherin", "moderatorin", "gast", "gastgeber", "erzähler",
        "erzählerin", "hintergrund", "unbekannt", "stimme", "teilnehmer", "teilnehmerin",
        "übersetzer", "спікер", "ведучий", "ведуча", "гість", "гостя", "оповідач", "фон",
        "невідомий", "голос", "учасник", "учасниця", "перекладач",
    }
)  # fmt: skip

_EDGE_PUNCT = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_LETTERS = re.compile(r"^[^\W\d_]+(?:[-'’][^\W\d_]+)*$", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?…:]$")


# ── Resources ────────────────────────────────────────────────────────


@cache
def common_words(language: str) -> frozenset[str]:
    """The recording language's 50 000 most frequent word forms ∪ English
    (Tatoeba-derived, CC-BY 2.0 FR; ``scripts/models/build_frequency_lists.py``)."""
    langs = {language, "en"} if language in ("de", "uk", "en") else {"en"}
    out: set[str] = set()
    for lang in langs:
        text = (
            resources.files("asr_models")
            .joinpath("resources", f"freq_{lang}.txt")
            .read_text(encoding="utf-8")
        )
        out.update(line.strip() for line in text.splitlines() if line.strip())
    return frozenset(out)


# ── Phonetics and similarity ─────────────────────────────────────────


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    reach = max(0, max(len(a), len(b)) // 2 - 1)
    a_hit = [False] * len(a)
    b_hit = [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):
        lo, hi = max(0, i - reach), min(len(b), i + reach + 1)
        for j in range(lo, hi):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    a_seq = [c for c, hit in zip(a, a_hit, strict=True) if hit]
    b_seq = [c for c, hit in zip(b, b_hit, strict=True) if hit]
    transpositions = sum(x != y for x, y in zip(a_seq, b_seq, strict=True)) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4], strict=False):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def koelner(word: str) -> str:
    """Kölner Phonetik (Postel 1969)."""
    w = word.upper().replace("Ä", "A").replace("Ö", "O").replace("Ü", "U").replace("ß", "S")
    w = "".join(c for c in w if "A" <= c <= "Z")
    codes: list[str] = []
    for i, c in enumerate(w):
        prev = w[i - 1] if i else ""
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if c in "AEIJOUY":
            code = "0"
        elif c == "H":
            code = "-"
        elif c == "B":
            code = "1"
        elif c == "P":
            code = "3" if nxt == "H" else "1"
        elif c in "DT":
            code = "8" if nxt in ("C", "S", "Z") and nxt else "2"
        elif c in "FVW":
            code = "3"
        elif c in "GKQ":
            code = "4"
        elif c == "C":
            if i == 0:
                code = "4" if nxt in "AHKLOQRUX" and nxt else "8"
            else:
                code = "4" if nxt in "AHKOQUX" and nxt and prev not in "SZ" else "8"
        elif c == "X":
            code = "8" if prev in "CKQ" and prev else "48"
        elif c == "L":
            code = "5"
        elif c in "MN":
            code = "6"
        elif c == "R":
            code = "7"
        elif c in "SZ":
            code = "8"
        else:
            code = ""
        codes.append(code)
    out: list[str] = []
    for code in "".join(codes):
        if code == "-":
            continue
        if out and out[-1] == code:
            continue
        out.append(code)
    if not out:
        return ""
    return out[0] + "".join(c for c in out[1:] if c != "0")


_UK_ROMAN = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu",
    "я": "ia", "'": "", "’": "", "ʼ": "",
    # Russian letters heard inside Ukrainian speech (surzhyk, names).
    "ы": "y", "э": "e", "ъ": "", "ё": "io",
}  # fmt: skip


def romanise_uk(word: str) -> str:
    return "".join(_UK_ROMAN.get(ch, ch) for ch in word.casefold())


@cache
def phonetic_key(word: str, language: str) -> str:
    """The sound of a word, per language (TQ3 design)."""
    from metaphone import doublemetaphone

    w = word.casefold().replace("-", "").replace(" ", "")
    if language == "de":
        return koelner(w)
    if language == "uk" or any("а" <= ch <= "я" or ch in "іїєґ" for ch in w):
        w = romanise_uk(w)
    primary, _secondary = doublemetaphone(w)
    return str(primary)


_ENDINGS: dict[str, tuple[str, ...]] = {
    "de": ("ern", "ens", "es", "en", "er", "em", "s", "n", "e"),
    "en": ("'s", "es", "s"),
    "uk": (
        "ами", "ями", "ові", "еві", "ого", "ому", "ою", "ею", "ом", "ем", "ам", "ям", "ах",
        "ях", "ів", "ей", "ий", "ій", "ої", "им", "а", "я", "у", "ю", "і", "ї", "и", "о", "е",
    ),
}  # fmt: skip


def _stem(form: str, language: str) -> str:
    for ending in _ENDINGS.get(language, ()):
        if form.endswith(ending) and len(form) - len(ending) >= MIN_LETTERS:
            return form[: -len(ending)]
    return form


def inflected(a: str, b: str, language: str) -> bool:
    """Two forms of one word ("Lagersystem"/"Lagersystems", "Петро"/"Петра"):
    the same entity, but rewriting one into the other would break the
    grammar — never merged."""
    if a == b:
        return False
    langs = {language, "en"}
    for lang in langs:
        sa, sb = _stem(a, lang), _stem(b, lang)
        if sa in (sb, b) or sb == a:
            return True
    return False


def _trigrams(form: str) -> set[str]:
    padded = f"^{form}$"
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def compact(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


# ── Mentions ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mention:
    s: int  # segment index in the artefact
    w: int  # first word index in that segment
    n: int  # words covered
    surface: str  # as written ("Hand aller")
    form: str  # compact, case-folded ("handaller")
    t: int  # start_ms of the first word — the anchor that survives re-splits
    seg_ms: int  # length of the segment it is in (canonical tie-break)


def _clean(word: str) -> str:
    return _EDGE_PUNCT.sub("", unicodedata.normalize("NFKC", word))


def _words(output: TranscriptionOutput) -> list[list[WordTiming]]:
    return [list(seg.words) for seg in output.segments]


def mentions(
    output: TranscriptionOutput, *, language: str, exact_forms: frozenset[str]
) -> tuple[list[Mention], list[Mention]]:
    """``(unigrams, bigrams)`` worth clustering."""
    common = common_words(language)
    uni: list[Mention] = []
    bi: list[Mention] = []
    for s, seg in enumerate(output.segments):
        words = seg.words
        seg_ms = max(1, seg.end_ms - seg.start_ms)
        for w, word in enumerate(words):
            surface = _clean(word.text)
            if not surface or not _LETTERS.match(surface):
                continue
            form = compact(surface)
            initial = w == 0 or bool(_SENTENCE_END.search(words[w - 1].text.strip()))
            if form in ROLE_WORDS:
                continue
            is_mention = form in exact_forms or (
                len(form) >= MIN_LETTERS
                and ((surface[:1].isupper() and not initial) or form not in common)
            )
            if is_mention:
                uni.append(Mention(s, w, 1, surface, form, word.start_ms, seg_ms))
            if w + 1 < len(words):
                nxt = _clean(words[w + 1].text)
                if nxt and _LETTERS.match(nxt) and not _SENTENCE_END.search(word.text.strip()):
                    pair = f"{surface} {nxt}"
                    bi.append(Mention(s, w, 2, pair, compact(pair), word.start_ms, seg_ms))
    return uni, bi


# ── Anchors ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Anchor:
    text: str  # canonical spelling of one token ("Welchering")
    source: Literal["glossary", "calendar", "hint"]
    forms: frozenset[str]  # compact forms that map here exactly (term + heard_as)


def anchors(
    *,
    glossary: Iterable[tuple[str, Sequence[str]]],
    attendees: Iterable[str],
    hint_terms: Iterable[str],
) -> list[Anchor]:
    """One anchor per name token (a person is heard by surname more than by
    full name). ``glossary`` is ``(term, heard_as)``; a single-token term's
    ``heard_as`` spellings map to it exactly."""
    out: dict[str, Anchor] = {}

    def add(
        token: str, source: Literal["glossary", "calendar", "hint"], extra: Iterable[str]
    ) -> None:
        clean = _clean(token)
        form = compact(clean)
        if len(form) < MIN_LETTERS or form in ROLE_WORDS or not _LETTERS.match(clean):
            return
        if form in out:
            prev = out[form]
            out[form] = Anchor(prev.text, prev.source, prev.forms | {compact(e) for e in extra})
            return
        out[form] = Anchor(clean, source, frozenset({form, *(compact(e) for e in extra)}))

    for term, heard_as in glossary:
        parts = term.split()
        for part in parts:
            add(part, "glossary", heard_as if len(parts) == 1 else ())
    for name in attendees:
        for part in name.split():
            add(part, "calendar", ())
    for term in hint_terms:
        for part in term.split():
            add(part, "hint", ())
    return list(out.values())


# ── Clusters ─────────────────────────────────────────────────────────


@dataclass
class Cluster:
    forms: set[str] = field(default_factory=set)
    anchor: Anchor | None = None
    mentions: list[Mention] = field(default_factory=list)


@dataclass(frozen=True)
class Proposal:
    to_text: str
    from_forms: tuple[str, ...]
    occurrences: tuple[dict[str, int], ...]
    source: Source
    confidence: float
    status: Status


@dataclass(frozen=True)
class PlanResult:
    proposals: list[Proposal]
    discarded: int


def _similar(a: str, b: str, language: str) -> float:
    """Jaro–Winkler, raised to the merge bar when the keys agree and the
    spellings are not far apart. Inflections of one word score 0."""
    if inflected(a, b, language):
        return 0.0
    # A much shorter form is a different word with the same start ("Hand"/"Handala").
    if min(len(a), len(b)) < LENGTH_RATIO * max(len(a), len(b)):
        return 0.0
    jw = jaro_winkler(a, b)
    if jw >= JW_KEY_GUARD and phonetic_key(a, language) == phonetic_key(b, language):
        return max(jw, JW_MERGE)
    return jw


def plan(
    output: TranscriptionOutput,
    *,
    language: str,
    glossary: Iterable[tuple[str, Sequence[str]]] = (),
    attendees: Iterable[str] = (),
    hint_terms: Iterable[str] = (),
    auto_apply: bool = True,
) -> PlanResult:
    """The corrections this transcript should carry (TQ3 design)."""
    anchor_list = anchors(glossary=glossary, attendees=attendees, hint_terms=hint_terms)
    exact = frozenset(f for a in anchor_list for f in a.forms)
    uni, bi = mentions(output, language=language, exact_forms=exact)
    common = common_words(language)
    by_form: dict[str, list[Mention]] = defaultdict(list)
    for m in uni:
        by_form[m.form].append(m)

    clusters: list[Cluster] = [Cluster(anchor=a) for a in anchor_list]
    anchored: dict[str, Cluster] = {}
    loose: list[str] = []
    for form in sorted(by_form):
        exact_hit = [c for c in clusters if c.anchor and form in c.anchor.forms]
        if len(exact_hit) == 1:
            anchored[form] = exact_hit[0]
            continue
        scored = sorted(
            (
                (_similar(form, compact(c.anchor.text), language), k)
                for k, c in enumerate(clusters)
                if c.anchor
            ),
            reverse=True,
        )
        best = scored[0] if scored else (0.0, -1)
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best[0] >= JW_MERGE and best[0] - second >= ANCHOR_MARGIN:
            target = clusters[best[1]]
            assert target.anchor is not None
            if form in common and target.anchor.source == "hint":
                continue  # a hint is not proof enough to rename a word
            anchored[form] = target
        elif form not in common:
            loose.append(form)
        # A common word close to two anchors, or to none, stays as it is.

    for form, cluster in anchored.items():
        cluster.forms.add(form)
    # Loose (non-common) forms cluster among themselves.
    parent = {f: f for f in loose}

    def find(f: str) -> str:
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f

    # Only pairs sharing two trigrams are compared (all pairs would cost seconds).
    index: dict[str, list[str]] = defaultdict(list)
    for f in loose:
        for g in _trigrams(f):
            index[g].append(f)
    for a in loose:
        shared: Counter[str] = Counter()
        for g in _trigrams(a):
            shared.update(b for b in index[g] if b > a)
        for b, k in shared.items():
            if k >= 2 and abs(len(a) - len(b)) <= 4 and _similar(a, b, language) >= JW_MERGE:
                parent[find(a)] = find(b)
    groups: dict[str, set[str]] = defaultdict(set)
    for f in loose:
        groups[find(f)].add(f)
    clusters.extend(Cluster(forms=g) for g in groups.values())

    for cluster in clusters:
        for form in cluster.forms:
            cluster.mentions.extend(by_form[form])
    # Two-word spans attach to the cluster they sound like most.
    targets: dict[str, list[tuple[str, Cluster]]] = defaultdict(list)
    for cluster in clusters:
        if not cluster.mentions:
            continue
        forms = cluster.forms | ({compact(cluster.anchor.text)} if cluster.anchor else set())
        for f in forms:
            for g in _trigrams(f):
                targets[g].append((f, cluster))
    for m in bi:
        if m.form in by_form:
            continue
        parts = [compact(part) for part in m.surface.split(" ")]
        span_hits: Counter[tuple[str, int]] = Counter()
        lookup: dict[tuple[str, int], Cluster] = {}
        for g in _trigrams(m.form):
            for f, cluster in targets.get(g, ()):
                span_hits[(f, id(cluster))] += 1
                lookup[(f, id(cluster))] = cluster
        best_c, best_s = None, 0.0
        for (f, cid), k in span_hits.items():
            if k < 2 or abs(len(f) - len(m.form)) > 4:
                continue
            # A span is a mishearing split in two, not the name with its neighbour.
            cluster = lookup[(f, cid)]
            members = cluster.forms | ({compact(cluster.anchor.text)} if cluster.anchor else set())
            if any(
                p in members
                or any(
                    inflected(p, x, language) or _similar(p, x, language) >= JW_MERGE
                    for x in members
                )
                for p in parts
            ):
                continue  # one of its words is the variant itself, not the pair
            score = _similar(m.form, f, language)
            if score > best_s:
                best_c, best_s = lookup[(f, cid)], score
        if best_c is not None and best_s >= JW_MERGE:
            best_c.mentions.append(m)

    proposals: list[Proposal] = []
    discarded = 0
    for cluster in clusters:
        result = _decide(cluster, common=common, auto_apply=auto_apply)
        if result is None:
            discarded += 1 if cluster.mentions else 0
        else:
            proposals.append(result)
    return PlanResult(proposals=proposals, discarded=discarded)


def _decide(cluster: Cluster, *, common: frozenset[str], auto_apply: bool) -> Proposal | None:
    ms = cluster.mentions
    if not ms:
        return None
    surfaces = Counter(m.surface for m in ms if m.n == 1)
    if cluster.anchor is not None:
        to_text = cluster.anchor.text
        source: Source = cluster.anchor.source
    else:
        if not surfaces:
            return None
        top = max(surfaces.values())
        tied = [s for s, n in surfaces.items() if n == top]
        to_text = max(tied, key=lambda s: max(m.seg_ms for m in ms if m.surface == s))
        source = "majority"
        if not to_text[:1].isupper():
            return None  # names are capitalised in de, en and uk
    canonical = compact(to_text)
    if canonical in ROLE_WORDS:
        return None
    variants = [m for m in ms if m.form != canonical]
    support = len(ms)
    if not variants or support < MIN_SUPPORT:
        return None
    if source in SOURCE_CONFIDENCE:
        confidence = SOURCE_CONFIDENCE[source]
    else:
        similarity = sum(jaro_winkler(m.form, canonical) for m in variants) / len(variants)
        share = (support - len(variants)) / support
        confidence = 0.45 * similarity + 0.25 * min(1.0, support / 6) + 0.30 * share
    confidence = round(min(1.0, confidence), 3)
    strong = source in ("glossary", "calendar")
    if strong or confidence >= ACCEPT_AT:
        status: Status = "accepted"
    elif confidence >= PROPOSE_AT and support >= PROPOSE_MIN_SUPPORT:
        status = "proposed"
    else:
        return None
    if status == "accepted" and not strong and canonical in common:
        # A common word as the canonical: never applied on majority alone.
        if support < PROPOSE_MIN_SUPPORT:
            return None
        status = "proposed"
    if not auto_apply and status == "accepted" and source != "user":
        status = "proposed"
    from_forms = tuple(sorted({m.surface for m in variants}))
    occurrences = tuple(
        {"s": m.s, "w": m.w, "n": m.n, "t": m.t} for m in sorted(variants, key=lambda m: (m.s, m.w))
    )
    return Proposal(to_text, from_forms, occurrences, source, confidence, status)


# ── Applying ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Applied:
    """What :func:`apply` needs of one stored correction."""

    to_text: str
    from_forms: tuple[str, ...]
    occurrences: tuple[dict[str, Any], ...]


def _locate(
    segments: Sequence[Segment], occ: dict[str, Any], forms: frozenset[str]
) -> tuple[int, int, int] | None:
    """Where an occurrence is now: its indices if they still hold the
    variant, else the word that starts at its time (a re-label can split
    segments differently; the words and their times do not change)."""
    s, w, n, t = int(occ["s"]), int(occ["w"]), int(occ["n"]), occ.get("t")

    def holds(si: int, wi: int) -> bool:
        if si >= len(segments) or wi + n > len(segments[si].words):
            return False
        span = " ".join(_clean(x.text) for x in segments[si].words[wi : wi + n])
        return compact(span) in forms

    if holds(s, w):
        return s, w, n
    if t is not None:
        for si, seg in enumerate(segments):
            if not (seg.start_ms <= int(t) <= seg.end_ms):
                continue
            for wi, word in enumerate(seg.words):
                if word.start_ms == int(t) and holds(si, wi):
                    return si, wi, n
    return None


def apply(output: TranscriptionOutput, corrections: Sequence[Applied]) -> TranscriptionOutput:
    """A copy of ``output`` with each correction's occurrences replaced by
    its ``to_text``. The artefact passed in is not modified."""
    if not corrections:
        return output
    segments = [seg.model_copy(deep=True) for seg in output.segments]
    edits: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for corr in corrections:
        forms = frozenset(compact(f) for f in corr.from_forms)
        for occ in corr.occurrences:
            at = _locate(segments, occ, forms)
            if at is not None:
                edits[at[0]].append((at[1], at[2], corr.to_text))
    for si, items in edits.items():
        segments[si] = _rewrite(segments[si], items)
    return output.model_copy(update={"segments": segments})


def _rewrite(seg: Segment, items: list[tuple[int, int, str]]) -> Segment:
    words = list(seg.words)
    text = seg.text
    cursor = 0
    taken: set[int] = set()
    for w, n, to_text in sorted(items, reverse=True):
        if any(k in taken for k in range(w, w + n)):
            continue
        taken.update(range(w, w + n))
        first, last = words[w], words[w + n - 1]
        lead = re.match(r"^[^\w]*", first.text, re.UNICODE)
        tail = re.search(r"[^\w]*$", last.text, re.UNICODE)
        new_text = (lead.group(0) if lead else "") + to_text + (tail.group(0) if tail else "")
        words[w : w + n] = [
            WordTiming(
                text=new_text,
                start_ms=first.start_ms,
                end_ms=last.end_ms,
                probability=min(x.probability for x in words[w : w + n]),
            )
        ]
    # The segment text: each original span, left to right, replaced once.
    spans = sorted(items)
    out: list[str] = []
    for w, n, to_text in spans:
        original = [_clean(x.text) for x in seg.words[w : w + n]]
        pattern = r"(?<!\w)" + r"[^\w]*\s+[^\w]*".join(re.escape(p) for p in original) + r"(?!\w)"
        found = re.compile(pattern, re.UNICODE).search(text, cursor)
        if found is None:
            continue
        out.append(text[cursor : found.start()])
        out.append(to_text)
        cursor = found.end()
    out.append(text[cursor:])
    return seg.model_copy(update={"words": words, "text": "".join(out)})


def valid_to_text(value: str) -> bool:
    """An edited spelling: whole words, ≤ 80 characters, letters, spaces,
    hyphens and apostrophes only — nothing that could carry markup."""
    v = value.strip()
    if not v or len(v) > TO_TEXT_MAX or v != value.strip():
        return False
    return all(_LETTERS.match(part) for part in v.split(" ") if part) and "  " not in v
