"""``python -m auth_service.ops.onboard`` — concierge onboarding (OPS-0).

    python -m auth_service.ops.onboard --email ada@acme.com --display-name "Ada Lovelace"
    python -m auth_service.ops.onboard --email ada@acme.com --display-name "Ada" --locale uk
    python -m auth_service.ops.onboard --email ada@acme.com --display-name "Ada" --dry-run

Creates an account the way self-serve signup does — same
``OnboardingService``, same Keycloak call, same transaction, same
workspace — and then marks it verified, because an operator vouched for
the address. The person gets one mail with a temporary password and a
link to change it.

Live from day 3, which is the point: demand should not wait for the public
endpoints, and the first twenty users teach more through a person than
through a funnel metric.

── What the operator never does ─────────────────────────────────────────

Never sets a password by hand. Never opens the Keycloak console. Never
writes SQL. Those three rules are why this exists at all — each of them is
a way to create an account that works until the first save and then fails
on a missing row, and each has happened before.

The temporary password is generated here, sent once, and **printed
nowhere**. The operator does not see it, so they cannot paste it into a
chat window, and there is no copy of it outside the recipient's mailbox.
If the mail does not arrive, the fix is to run the command again for a
fresh password — not to go looking for the old one.

Exit codes: 0 created, 1 the command failed (nothing half-created —
``OnboardingService`` compensates), 2 bad arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger("auth_service.ops.onboard")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdx-onboard", description=__doc__)
    parser.add_argument("--email", required=True, help="the person's email address")
    parser.add_argument(
        "--display-name", required=True, help='how their name appears ("Ada Lovelace")'
    )
    parser.add_argument(
        "--workspace-name",
        default="",
        help="override the personal workspace name (default: the email local part)",
    )
    parser.add_argument(
        "--locale",
        default="en",
        choices=("en", "de", "uk"),
        help="language for the welcome mail and the workspace (default en)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report what would happen; create nothing, send nothing",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    # Imported inside the function so `--help` works without a database.
    from ..config import settings
    from ..deps import install_state
    from ..domain import email_code as ec
    from ..domain.onboarding_service import SignupError, generate_password
    from ..main_deps import build_state, teardown_state

    address = ec.normalise_email(args.email)
    display_name = args.display_name.strip()
    if not display_name:
        print("--display-name cannot be empty", file=sys.stderr)
        return 2

    if args.dry_run:
        names = ec.personal_workspace_names(address)
        print(f"would create: {address}")
        print(f"  display name : {display_name}")
        print(f"  workspace    : {args.workspace_name or names.name}  (slug {names.slug})")
        print(f"  locale       : {args.locale}")
        print("  realm roles  : tenant_admin, member")
        print("  verified     : yes (operator vouched)")
        print("nothing was created and no mail was sent")
        return 0

    state = await build_state()
    install_state(state)
    try:
        service = _service_or_explain(state, settings)
        if service is None:
            return 1

        password = generate_password()
        try:
            account = await service.create_account(
                email=address,
                password=password,
                display_name=display_name,
                locale=args.locale,
                source="concierge",
                # The operator is the verification. No code is sent, and
                # the account is enabled at creation.
                verified=True,
            )
        except SignupError as exc:
            if exc.code == "email_taken":
                print(f"{address} already has an account — nothing to do", file=sys.stderr)
                return 1
            print(f"could not create the account: {exc.detail}", file=sys.stderr)
            print(
                "Nothing was half-created; OnboardingService compensates. "
                "If this keeps happening it is a BE-0 bug — open an issue "
                "rather than reaching for the Keycloak console.",
                file=sys.stderr,
            )
            return 1

        try:
            await service.mailer.send_concierge(
                to=address,
                display_name=display_name,
                temporary_password=password,
                lang=args.locale,
            )
        except Exception as exc:  # noqa: BLE001
            # The account exists and is usable; only the mail failed. Say
            # so precisely, because the recovery differs: the person needs
            # a password, and the way to give them one is "Forgot
            # password?" — never a second copy of this one.
            print(
                f"account created ({account.sub}) but the welcome mail FAILED: {exc}",
                file=sys.stderr,
            )
            print(
                "Do not resend the password. Ask them to use "
                f"'Forgot password?' at {settings.app_base_url}/login",
                file=sys.stderr,
            )
            return 1

        print(f"created {address}")
        print(f"  sub       : {account.sub}")
        print(f"  workspace : {account.tenant_id}")
        print("  mailed    : temporary password + change-password link")
        print("The password was not printed and is not recoverable. That is deliberate.")
        return 0
    finally:
        await teardown_state(state)


def _service_or_explain(state: Any, settings: Any) -> Any:
    """The wired service, or a sentence saying which switch is off."""
    service = getattr(state, "onboarding_service", None)
    if service is not None:
        return service
    if settings.idp_mode == "native":
        print(
            "MDX_IDP_MODE=native: Keycloak no longer holds credentials, so "
            "there is no password account to create. Onboard through "
            "/auth/email/start instead.",
            file=sys.stderr,
        )
    elif not settings.signup_enabled:
        print("MDX_SIGNUP_ENABLED is not set on this deployment.", file=sys.stderr)
    else:
        print(
            "signup is not wired: this deployment has no mail provider "
            "(MDX_EMAIL_PROVIDER) or no Redis. Both are required — an "
            "account nobody can be told about is not an onboarding.",
            file=sys.stderr,
        )
    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
