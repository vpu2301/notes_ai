"""What a workspace's writing profile (note instructions, N2) does to one run, as numbers
and one prompt block. Built once per run; :data:`DEFAULT` reproduces today's constants,
so a run without instructions is the same code with the same numbers. Pure.

Code dials (length, summary cap, bullets, sections left out, figure tables, quoted
sub-points, heading length, terminology) are applied by code; prompt dials (the writing
style's line, emphasis, avoid, guidance, style samples) go to the compose prompts as a FORM block. No
dial reaches extraction, verification or the gate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final

from . import compose, prompts

# The profile's `length` as a share of the standard volume (concept §2).
PROFILE_SCALE: Final[dict[str, float]] = {"short": 0.6, "standard": 1.0, "long": 1.4}
HEADING_WORDS_MAX: Final = 8
SHORT_HEADING_WORDS: Final = 5


def p2_sentences(scale: float) -> tuple[int, int]:
    """The summary's sentence band at this scale: short (2, 4), standard (3, 6), long (4, 6)."""
    lo, hi = compose.P2_SENTENCES
    if scale == 1.0:
        return lo, hi
    return max(2, round(lo * scale)), max(2, min(hi, round(hi * scale)))


@dataclass(frozen=True, slots=True)
class Styling:
    """One run's form settings. ``scale`` is None when the profile leaves length to the
    run (a prompt profile's length then applies)."""

    scale: float | None = None
    summary_sentences: int | None = None
    bullets: tuple[int, int] = compose.BULLETS
    sections_off: frozenset[str] = frozenset()
    figure_tables: bool = True
    quote_children: bool = True
    heading_max_words: int = HEADING_WORDS_MAX
    emphasis: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()
    guidance: tuple[str, ...] = ()
    style_examples: tuple[str, ...] = ()
    """N0 — the workspace's writing style; its line heads the FORM block (none for
    `business`, today's output)."""
    writing_style: str = "business"

    @property
    def topics_off(self) -> bool:
        return "topics" in self.sections_off

    def effective_scale(self, run_scale: float = 1.0) -> float:
        """The profile's length when it sets one, else the run's (a prompt profile's)."""
        return self.scale if self.scale is not None else run_scale

    def summary_cap(self, scale: float) -> int:
        """The most summary sentences: the profile's cap, else the scaled band's top."""
        band_top = p2_sentences(scale)[1]
        return min(self.summary_sentences, band_top) if self.summary_sentences else band_top

    def block(self, language: str) -> str:
        """The FORM block for the compose prompts ("" when there is nothing to say)."""
        return prompts.style_block(
            language,
            preset=prompts.writing_style_lines(self.writing_style, language),
            emphasis=self.emphasis,
            avoid=self.avoid,
            terms=self.terms,
            heading_short=self.heading_max_words < HEADING_WORDS_MAX,
            guidance=self.guidance,
            examples=self.style_examples,
        )

    @property
    def echo_extra(self) -> frozenset[str]:
        """A style sample copied into the note is dropped like a prompt example."""
        return prompts.example_grams(self.style_examples)


DEFAULT: Final = Styling()

# N0 — each writing style's code defaults (business = today's). Note instructions that set
# one of these dials win over the style.
STYLE_DEFAULTS: Final[dict[str, dict[str, Any]]] = {
    "business": {},
    "formal": {},
    "informal": {
        "heading_max_words": SHORT_HEADING_WORDS,
        "figure_tables": False,
        "quote_children": True,
    },
    "academic": {"figure_tables": True, "quote_children": True, "summary_sentences": 6},
}


def build(profile: Any | None, writing_style: str = "business") -> Styling:
    """The run's styling: the writing style — the one the instructions name, else the
    workspace's picker — with its code defaults, and the instructions' dials on top.
    ``business`` with no instructions is :data:`DEFAULT` (today's output)."""
    base = from_profile(profile)
    named = getattr(profile, "style", None) if profile is not None else None
    writing_style = named or writing_style
    if writing_style == "business" or writing_style not in STYLE_DEFAULTS:
        return replace(base, writing_style="business") if base.writing_style != "business" else base
    empty = from_profile(None)
    update: dict[str, Any] = {"writing_style": writing_style}
    for name, value in STYLE_DEFAULTS[writing_style].items():
        # The style fills a dial only where the instructions left it at its default.
        if getattr(base, name) == getattr(empty, name):
            update[name] = value
    return replace(base, **update)


def from_profile(profile: Any | None) -> Styling:
    """The run's styling from a ``WritingProfile`` (None or empty → :data:`DEFAULT`)."""
    if profile is None:
        return DEFAULT
    styling = Styling(
        scale=PROFILE_SCALE[profile.length] if profile.length != "standard" else None,
        summary_sentences=profile.summary_sentences,
        bullets=tuple(profile.bullets_per_section)
        if profile.bullets_per_section
        else compose.BULLETS,
        sections_off=frozenset(profile.sections_off),
        figure_tables=profile.figure_tables,
        quote_children=profile.quote_children,
        heading_max_words=SHORT_HEADING_WORDS
        if profile.heading_style == "short"
        else HEADING_WORDS_MAX,
        # The style the instructions name; its code defaults are applied by `build`.
        writing_style=profile.style or "business",
        emphasis=tuple(profile.emphasis),
        avoid=tuple(profile.avoid),
        terms=tuple((t.use, t.instead_of) for t in profile.terminology),
        guidance=tuple(profile.guidance),
        style_examples=tuple(profile.style_examples),
    )
    return DEFAULT if styling == DEFAULT else styling
