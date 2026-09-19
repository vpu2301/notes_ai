"""Markdown-lite → HTML for the note PDF body.

A generated meeting note is not flat prose: it arrives as bullets,
numbered decisions, checkbox action items, bold run-in leads and the
occasional small table. Rendered with ``white-space: pre-wrap`` (what
the PDF template used to do) all of that lands in the document as raw
``- `` and ``**…**`` — a text dump wearing a page.

This module turns that text into real block structure so the renderer
can typeset it: paragraphs, lists, checklists, headings, quotes and
pipe tables.

Safety
------
The input is user/model text and the output is injected into the Jinja
template *unescaped*, so escaping happens HERE and first:
:func:`_escape` runs over the raw text before any markup is produced,
and every tag emitted afterwards is our own literal. No attribute ever
carries user bytes (no links, no ``style``, no ``class`` from input),
so there is nothing for a crafted note to break out of.

Determinism: pure function of the input string — no time, no locale,
no dict ordering.
"""

from __future__ import annotations

import re
from html import escape as _escape

__all__ = ["render_rich_text"]

# ── block-level line shapes ──────────────────────────────────────────
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_CHECK = re.compile(r"^\s{0,4}(?:[-*+•])\s*\[([ xX])\]\s+(.*)$")
_BULLET = re.compile(r"^\s{0,4}(?:[-*+•‣–])\s+(.*)$")
_ORDERED = re.compile(r"^\s{0,4}(\d{1,3})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_RULE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")

# ── inline shapes (applied to already-escaped text) ──────────────────
_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(\S(?:[^*]*\S)?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(\S(?:[^*\n]*\S)?)\*(?![\w*])")
_ITALIC_ = re.compile(r"(?<![\w_])_(\S(?:[^_\n]*\S)?)_(?![\w_])")
# A run-in lead the model writes as "**Retention.**" or "Retention:" at
# the head of a paragraph reads as a heading, not as body — the template
# styles <b class=lead> that way.
_LEAD = re.compile(r"^<strong>([^<]{1,60}?)</strong>(?=[\s:—–-]|$)")
# "Anna: we ship Friday" — a transcript turn or a run-in label. The label
# is at most four words, carries no markup and is not a URL scheme.
_SPEAKER = re.compile(r"^([^\s<>:][^<>:]{0,39}?):\s+(?=\S)")


def _inline(text: str) -> str:
    """Escape one line and apply inline emphasis. Escaping happens first,
    so every tag below is ours."""
    out = _escape(text, quote=False)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    out = _ITALIC_.sub(r"<em>\1</em>", out)
    return out


def _paragraph(lines: list[str]) -> str:
    """Join a soft-wrapped paragraph; promote a run-in bold lead."""
    body = _inline(" ".join(line.strip() for line in lines if line.strip()))
    if not body:
        return ""
    body = _LEAD.sub(r'<strong class="lead">\1</strong>', body, count=1)
    if not body.startswith("<"):
        turn = _SPEAKER.match(body)
        if (
            turn
            and len(turn.group(1).split()) <= 4
            and not turn.group(1).lower().startswith("http")
        ):
            return (
                f'<p class="turn"><span class="speaker">{turn.group(1)}</span> '
                f"{body[turn.end() :]}</p>"
            )
    return f"<p>{body}</p>"


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _table(rows: list[str]) -> str:
    """A pipe table: first row is the header, the dashed row is dropped."""
    header, *body = [r for r in rows if not _TABLE_SEP.match(r)]
    head_cells = "".join(f"<th>{_inline(c)}</th>" for c in _split_row(header))
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _split_row(r)) + "</tr>" for r in body
    )
    return f"<table><thead><tr>{head_cells}</tr></thead><tbody>{body_rows}</tbody></table>"


def _is_table(lines: list[str]) -> bool:
    return len(lines) >= 2 and "|" in lines[0] and any(_TABLE_SEP.match(x) for x in lines[1:2])


def render_rich_text(text: str) -> str:
    """Render one section body as block-level HTML.

    Recognises: ATX headings, ``- ``/``* ``/``• `` bullets, ``1.``
    ordered items, ``- [ ]`` / ``- [x]`` checklists, ``>`` quotes,
    ``---`` rules and pipe tables. Everything else is a paragraph, with
    single newlines treated as soft wraps (a blank line starts a new
    block) — which is how the note editor's plain-text fields behave.
    """
    if not text or not text.strip():
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    html: list[str] = []
    para: list[str] = []
    # Open list state: ("ul" | "ol" | "check", items).
    kind: str | None = None
    items: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            html.append(_paragraph(para))
            para = []

    def flush_list() -> None:
        nonlocal kind, items
        if kind and items:
            tag = "ol" if kind == "ol" else "ul"
            cls = ' class="checklist"' if kind == "check" else ""
            html.append(f"<{tag}{cls}>" + "".join(items) + f"</{tag}>")
        kind, items = None, []

    def flush() -> None:
        flush_para()
        flush_list()

    def push(new_kind: str, item: str) -> None:
        nonlocal kind
        flush_para()
        if kind != new_kind:
            flush_list()
            kind = new_kind
        items.append(item)

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            flush()
            i += 1
            continue

        if _is_table(lines[i:]):
            flush()
            block: list[str] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            html.append(_table(block))
            continue

        if _RULE.match(line):
            flush()
            html.append('<hr class="rule" />')
            i += 1
            continue

        if m := _HEADING.match(line):
            flush()
            level = min(len(m.group(1)) + 2, 4)  # h1/h2 belong to the document chrome
            html.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if m := _CHECK.match(line):
            done = m.group(1).lower() == "x"
            box = f'<span class="box{" done" if done else ""}"></span>'
            body = _inline(m.group(2))
            push("check", f'<li>{box}<span class="task">{body}</span></li>')
            i += 1
            continue

        if m := _BULLET.match(line):
            push("ul", f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        if m := _ORDERED.match(line):
            push("ol", f"<li>{_inline(m.group(2))}</li>")
            i += 1
            continue

        if m := _QUOTE.match(line):
            quote = [m.group(1)]
            i += 1
            while i < len(lines) and (q := _QUOTE.match(lines[i])):
                quote.append(q.group(1))
                i += 1
            flush()
            html.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
            continue

        # A continuation line inside a list keeps the item it belongs to.
        if kind and line.startswith((" ", "\t")):
            items[-1] = items[-1].replace("</li>", f" {_inline(line.strip())}</li>")
            i += 1
            continue

        flush_list()
        para.append(line)
        i += 1

    flush()
    return "".join(html)
