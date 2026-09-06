#!/usr/bin/env python3
"""CI gate — every service verifies against its configured issuer LIST.

FND-1 (ADR-0047) replaced the single ``expected_issuer`` string with a
list resolved from ``AUTH_ISSUERS_JSON``. Two regressions would undo it
silently, and neither shows up as a failing test in the service that
causes it:

1. **A literal issuer at a call site.** ``verify_token(...,
   expected_issuer="https://...")`` or ``build_current_user(...,
   expected_issuer=settings.auth_issuer)`` pins one service to one issuer
   while the rest of the fleet has moved on. During the `dual` period
   that service rejects every native token — an outage confined to one
   endpoint, which is the hardest kind to find.

2. **A service that never reads the list.** A new service copied from an
   older one keeps the three legacy env vars, and the fleet-wide
   ``AUTH_ISSUERS_JSON`` rollout skips it without a word.

The legacy keyword pair is still supported by ``libs/auth`` — the
one-element fallback is how a not-yet-migrated deployment keeps working —
so this gate is what stops the fleet drifting back onto it.

Exit codes:
    0 — no violations
    1 — violations printed to stderr
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = ROOT / "services"

# libs/auth itself defines the legacy path and documents it; its tests
# exercise it deliberately.
EXEMPT_PACKAGES: frozenset[str] = frozenset({"auth"})

VERIFY_CALLS: frozenset[str] = frozenset({"verify_token", "build_current_user"})
LEGACY_KWARGS: frozenset[str] = frozenset({"expected_issuer", "expected_audience"})


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def check_no_legacy_kwargs(path: Path) -> list[str]:
    """No service passes ``expected_issuer=`` / ``expected_audience=``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken file fails elsewhere
        return [f"{path}: could not parse ({exc})"]

    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in VERIFY_CALLS:
            continue
        used = {kw.arg for kw in node.keywords if kw.arg in LEGACY_KWARGS}
        if used:
            problems.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: "
                f"{_call_name(node)}() uses {sorted(used)} — pass issuers=… "
                f"(the list from AUTH_ISSUERS_JSON) instead"
            )
    return problems


def check_reads_the_list(service_src: Path) -> list[str]:
    """Every service's config declares ``AUTH_ISSUERS_JSON``, and something reads it."""
    problems: list[str] = []
    sources = list(service_src.rglob("*.py"))
    if not sources:
        return problems

    declares = any("AUTH_ISSUERS_JSON" in p.read_text(encoding="utf-8") for p in sources)
    # A service that never verifies a token (a pure worker) has no config
    # to check; recognise it by the absence of any verification wiring.
    verifies = any(
        any(name in p.read_text(encoding="utf-8") for name in VERIFY_CALLS) for p in sources
    )
    if verifies and not declares:
        problems.append(
            f"{service_src.relative_to(ROOT)}: verifies tokens but never reads "
            f"AUTH_ISSUERS_JSON — add the field to config.py and build the "
            f"issuer list with auth.issuers_from_env()"
        )
    if verifies and declares:
        uses_helper = any(
            "issuers_from_env" in p.read_text(encoding="utf-8") for p in sources
        )
        if not uses_helper:
            problems.append(
                f"{service_src.relative_to(ROOT)}: declares AUTH_ISSUERS_JSON but "
                f"never calls auth.issuers_from_env() — the value is being ignored"
            )
    return problems


def main() -> int:
    problems: list[str] = []

    for service in sorted(SERVICES_DIR.iterdir()):
        src = service / "src"
        if not src.is_dir():
            continue
        for package in sorted(src.iterdir()):
            if not package.is_dir() or package.name in EXEMPT_PACKAGES:
                continue
            problems.extend(check_reads_the_list(package))
            for path in sorted(package.rglob("*.py")):
                problems.extend(check_no_legacy_kwargs(path))

    if problems:
        print("check-auth-issuer-config: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nFND-1: services verify against the list in AUTH_ISSUERS_JSON "
            "(auth.issuers_from_env), never a single hard-wired issuer. "
            "See docs/adr/0047-dual-issuer-period.md.",
            file=sys.stderr,
        )
        return 1

    print("check-auth-issuer-config: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
