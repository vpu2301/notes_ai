"""Jinja2 email rendering: content-free (templates see only the allow-listed
projection, never a payload splat), autoescaped, and deterministic (no clock, no random).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from notification_events import Category

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text_body: str
    html_body: str


def build_environment(template_dir: Path | None = None) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        # A typo'd variable must fail the render.
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml"]),
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


_ENV: Environment | None = None


def _env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = build_environment()
    return _ENV


def render_email(
    category: Category,
    *,
    template_stem: str,
    fields: dict[str, Any],
    deep_link: str,
    env: Environment | None = None,
    items: list[str] | None = None,
) -> RenderedEmail:
    """Render one category's mail.

    `fields` MUST already be the allow-listed projection; nothing is filtered here.
    `items` (digest lines) is a separate parameter so an event payload can never supply it.
    """
    environment = env or _env()
    context = {
        "fields": fields,
        "deep_link": deep_link,
        "category": str(category),
        "items": items or [],
    }

    subject = environment.get_template(f"{template_stem}.subject.txt").render(**context)
    text = environment.get_template(f"{template_stem}.txt").render(**context)
    html = environment.get_template(f"{template_stem}.html").render(**context)

    # A subject with a newline is a header-injection vector.
    return RenderedEmail(
        subject=subject.replace("\n", " ").replace("\r", " ").strip(),
        text_body=text.strip(),
        html_body=html.strip(),
    )
