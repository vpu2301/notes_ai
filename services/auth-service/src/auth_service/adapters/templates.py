"""Jinja environment for account mail; ``StrictUndefined`` so a missing variable dead-letters instead of mailing a broken link."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATE_DIR: Final = Path(__file__).parent / "templates"

# What files exist on disk. Duplicates ``domain.copy.KINDS``/``SUPPORTED_LANGS`` on
# purpose (adapters must not import domain); the render test keeps them in step.
KINDS: Final[tuple[str, ...]] = (
    "password_reset",
    "password_changed",
    "auth_code",
    "auth_locked",
    # Account notices.
    "mfa_enabled",
    "mfa_disabled",
    "recovery_code_used",
    "email_changed",
    "account_deletion_scheduled",
    # Self-serve signup.
    "signup_verify",
    "signup_exists",
    "concierge_welcome",
)
SUPPORTED_LANGS: Final[tuple[str, ...]] = ("en", "de", "uk")


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text_body: str
    html_body: str


def build_environment(template_dir: Path | None = None) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml"], default_for_string=True),
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


def template_name(kind: str, lang: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown email kind {kind!r}")
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"unsupported language {lang!r}")
    return f"{kind}.{lang}.html"


def render_html(
    kind: str, lang: str, context: dict[str, Any], *, env: Environment | None = None
) -> str:
    template = (env or _env()).get_template(template_name(kind, lang))
    return template.render(**context).strip()


def render(
    kind: str,
    lang: str,
    *,
    subject: str,
    text_body: str,
    context: dict[str, Any],
    env: Environment | None = None,
) -> RenderedEmail:
    return RenderedEmail(
        # A newline in a subject is a header-injection primitive.
        subject=subject.replace("\n", " ").replace("\r", " ").strip(),
        text_body=text_body.strip(),
        html_body=render_html(kind, lang, context, env=env),
    )
