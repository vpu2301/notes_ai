"""Map a CommandSlot's intent → frontend Operation; the test suite enforces a 1:1 mapping."""

from __future__ import annotations

from ..pipeline.base import CommandSlot, Operation

_TABLE: dict[str, tuple[str, dict[str, str] | None]] = {
    "newparagraph": ("insert_paragraph_break", None),
    "newline": ("insert_line_break", None),
    "period": ("insert_punctuation", {"value": "."}),
    "comma": ("insert_punctuation", {"value": ","}),
    "question_mark": ("insert_punctuation", {"value": "?"}),
    "dash": ("insert_punctuation", {"value": "—"}),
    "colon": ("insert_punctuation", {"value": ":"}),
    "exclamation_mark": ("insert_punctuation", {"value": "!"}),
    "semicolon": ("insert_punctuation", {"value": ";"}),
    "ellipsis": ("insert_punctuation", {"value": "…"}),
    "hyphen": ("insert_punctuation", {"value": "-"}),
    "en_dash": ("insert_punctuation", {"value": "–"}),
    "open_double_quote": ("insert_punctuation", {"value": "“"}),
    "close_double_quote": ("insert_punctuation", {"value": "”"}),
    "open_single_quote": ("insert_punctuation", {"value": "‘"}),
    "close_single_quote": ("insert_punctuation", {"value": "’"}),
    "open_paren": ("insert_punctuation", {"value": "("}),
    "close_paren": ("insert_punctuation", {"value": ")"}),
    "open_bracket": ("insert_punctuation", {"value": "["}),
    "close_bracket": ("insert_punctuation", {"value": "]"}),
    "open_brace": ("insert_punctuation", {"value": "{"}),
    "close_brace": ("insert_punctuation", {"value": "}"}),
    "slash": ("insert_punctuation", {"value": "/"}),
    "backslash": ("insert_punctuation", {"value": "\\"}),
    "apostrophe": ("insert_punctuation", {"value": "’"}),
    "asterisk": ("insert_punctuation", {"value": "*"}),
    "hash": ("insert_punctuation", {"value": "#"}),
    "numero_sign": ("insert_punctuation", {"value": "№"}),
    "percent_sign": ("insert_punctuation", {"value": "%"}),
    "ampersand": ("insert_punctuation", {"value": "&"}),
    "at_sign": ("insert_punctuation", {"value": "@"}),
    "plus_sign": ("insert_punctuation", {"value": "+"}),
    "minus_sign": ("insert_punctuation", {"value": "−"}),
    "equals_sign": ("insert_punctuation", {"value": "="}),
    "underscore": ("insert_punctuation", {"value": "_"}),
    "vertical_bar": ("insert_punctuation", {"value": "|"}),
    "save_draft": ("save_draft", None),
    "undo_last": ("undo_last", None),
    "stop_dictation": ("stop_dictation", None),
    "begin_quote": ("insert_quote_marker", {"value": "open"}),
    "end_quote": ("insert_quote_marker", {"value": "close"}),
    "insert_template": ("insert_template", None),
    # ── Typed-field commands ───────────────────────────────────────
    # arg: {section_key, value}; ``value`` is the option slug. The FE writes it as source "manual".
    "choice.set": ("set_choice", None),
    "choice.add": ("add_choice", None),
    "choice.remove": ("remove_choice", None),
}


def operations_for(slot: CommandSlot) -> Operation:
    """Translate one CommandSlot into a single Operation; ``slot.arg`` passes through."""
    intent = slot.intent
    if intent.startswith("section."):
        return Operation(op="navigate_section", arg=slot.arg or {})
    # An unresolved argument carries a ``reason``: a no-op with a precise reason, never a guess.
    if slot.arg and "reason" in slot.arg:
        return Operation(op="unknown_intent", arg={"intent": intent, **slot.arg})
    if intent not in _TABLE:
        # No-op marker so the frontend warns rather than guesses.
        return Operation(op="unknown_intent", arg={"intent": intent})
    op_name, arg = _TABLE[intent]
    if slot.arg:
        merged: dict[str, str] = dict(arg or {})
        merged.update(slot.arg)
        return Operation(op=op_name, arg=merged)
    return Operation(op=op_name, arg=arg)


KNOWN_INTENTS: frozenset[str] = frozenset({*_TABLE.keys(), "section"})  # "section.*"
