#!/usr/bin/env python3
"""IOS-0 smoke: a web-created account, signing in and capturing on iPhone.

The path the ticket names — *create + verify an account through the API,
sign in, record 1 s, assert the note* — as the iPhone app actually sends
it. Every request carries ``X-Client-Type: ios``, because that header is
what decides the shape of the answer: `routers/login.py` puts the refresh
token in the **body** for a native client and sets the ``mdx_rt`` cookie
only for a browser. A smoke that omitted it would exercise the web's
branch and prove nothing about the phone.

    make smoke-ios                       # against `make dev-up`
    scripts/smoke/ios_signup_e2e.py --help

What it does NOT do is drive the app's UI. The recording is a generated
one-second WAV rather than a microphone, for a reason that is not
laziness: a CI runner has no audio input device, and `Recorder` is the one
part of this pipeline that a machine without a microphone cannot exercise
at all. Everything downstream of it — the upload, the job, the transcript,
the note — is the same code either way, and the recorder itself is covered
by the app's own tests. `ios/Tests/…/LiveStackTests.swift` runs the app
half of this against the same stack.

Exit 0 = every step passed. Exit 1 = a step failed. Exit 2 = the stack is
not reachable, which is a missing fixture rather than a failed assertion
and deserves a different signal.
"""

from __future__ import annotations

import argparse
import io
import math
import struct
import sys
import time
import uuid

import httpx

IOS = {"X-Client-Type": "ios"}
SEEDED = ("member@tenant-a.example", "dev-password")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> bool:
    results.append((name, bool(ok), info))
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        -> {info}"))
    return bool(ok)


def skip(name: str, why: str) -> None:
    print(f"SKIP  {name}\n        -> {why}")


def one_second_of_audio(seconds: float = 1.0, rate: int = 16_000) -> bytes:
    """A WAV the ASR service will accept.

    A 440 Hz tone rather than silence: some pipelines treat an all-zero
    buffer as a decode failure, and a tone is at least honestly audio.
    `.wav` is not a compromise for the test's sake — it is the format
    `Recorder` itself falls back to when FLAC is unavailable, so the
    upload path being exercised is one the app really uses.
    """
    frames = int(rate * seconds)
    samples = b"".join(
        struct.pack("<h", int(12_000 * math.sin(2 * math.pi * 440 * n / rate)))
        for n in range(frames)
    )
    data = io.BytesIO()
    data.write(b"RIFF")
    data.write(struct.pack("<I", 36 + len(samples)))
    data.write(b"WAVEfmt ")
    data.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    data.write(b"data")
    data.write(struct.pack("<I", len(samples)))
    data.write(samples)
    return data.getvalue()


# ── 1. the account ───────────────────────────────────────────────────


def create_and_verify(auth: str, mailpit: str, timeout: float) -> tuple[str, str] | None:
    """A BE-0 account, created and confirmed through the API.

    Returns `(email, password)`, or None when this deployment has no
    signup surface — in which case the caller falls back to a seeded user
    and every step after this one still runs. That fallback is the point:
    until BE-0 lands, "the account is new" is the *only* claim this smoke
    cannot make, and losing the other five with it would leave the whole
    path untested for as long as BE-0 takes.
    """
    email = f"ios-smoke-{uuid.uuid4().hex[:10]}@example.test"
    password = f"Sm0ke-{uuid.uuid4().hex[:12]}!"
    try:
        r = httpx.post(
            f"{auth}/auth/signup",
            json={"email": email, "password": password},
            headers=IOS,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        check("signup reachable", False, str(exc))
        return None
    if r.status_code == 404:
        return None
    if not check("POST /auth/signup accepted the account", r.status_code in (200, 201, 202), r.text):
        return None

    # Unconfirmed: `/auth/login` must refuse with the code the app reads.
    refused = httpx.post(
        f"{auth}/auth/login", json={"email": email, "password": password}, headers=IOS, timeout=timeout
    )
    check(
        "an unconfirmed account is refused with `email_not_verified`",
        refused.status_code == 403 and refused.json().get("code") == "email_not_verified",
        f"{refused.status_code} {refused.text}",
    )

    # Resend, then confirm from the mailbox. The link is the only place
    # the token appears — by design, exactly as the sign-in code is.
    resent = httpx.post(
        f"{auth}/auth/signup/resend", json={"email": email}, headers=IOS, timeout=timeout
    )
    check("POST /auth/signup/resend accepted", resent.status_code in (200, 202, 204), resent.text)

    token = confirmation_token(mailpit, email, timeout)
    if not check("a confirmation link arrived", token is not None, "nothing in Mailpit"):
        return None
    confirmed = httpx.post(
        f"{auth}/auth/signup/confirm", json={"token": token}, headers=IOS, timeout=timeout
    )
    if not check("the account confirmed", confirmed.status_code < 300, confirmed.text):
        return None
    return email, password


def confirmation_token(mailpit: str, email: str, timeout: float, wait: float = 20.0) -> str | None:
    """The newest confirmation token Mailpit holds for one address.

    Same shape as `scripts/ci/mailpit-last-code.py`, and for the same
    reason: there is no response field, header or log line to read it
    from. Kept here rather than imported because that script prints a
    six-digit sign-in code and this needs an opaque link token.
    """
    import re

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            box = httpx.get(f"{mailpit}/api/v1/messages", params={"limit": 50}, timeout=timeout)
            box.raise_for_status()
        except httpx.HTTPError:
            return None
        for message in box.json().get("messages", []):
            if email.lower() not in str(message).lower():
                continue
            body = httpx.get(f"{mailpit}/api/v1/message/{message['ID']}", timeout=timeout)
            if body.status_code >= 300:
                continue
            text = body.json().get("Text", "") + body.json().get("HTML", "")
            found = re.search(r"[?&]token=([A-Za-z0-9._\-]{16,})", text)
            if found:
                return found.group(1)
        time.sleep(1)
    return None


# ── 2. signing in, as the phone does ─────────────────────────────────


def sign_in(auth: str, email: str, password: str, timeout: float) -> str | None:
    r = httpx.post(
        f"{auth}/auth/login", json={"email": email, "password": password}, headers=IOS, timeout=timeout
    )
    if not check("POST /auth/login signed the account in", r.status_code == 200, r.text):
        return None
    body = r.json()
    # The IOS-1 invariant, asserted where it can actually be observed: a
    # native client is handed the refresh token and never a cookie it has
    # no jar for. If this ever flips, the phone signs in and is silently
    # signed out fifteen minutes later.
    check("the refresh token came in the body", bool(body.get("refresh_token")), str(body.keys()))
    check("no refresh cookie was set for a native client", "set-cookie" not in r.headers, str(r.headers))
    return body.get("access_token")


# ── 3. a recording, a job, a note ────────────────────────────────────


def capture(asr: str, note: str, token: str, seconds: float, timeout: float) -> bool:
    auth_header = {"Authorization": f"Bearer {token}", **IOS}
    submitted = httpx.post(
        f"{asr}/asr/jobs",
        headers=auth_header,
        files={"audio": ("capture.wav", one_second_of_audio(seconds), "audio/wav")},
        data={"language": "en", "diarize": "false"},
        timeout=timeout,
    )
    if not check(f"POST /asr/jobs accepted {seconds:g}s of audio", submitted.status_code < 300, submitted.text):
        return False
    job_id = submitted.json()["id"]

    deadline = time.monotonic() + 300
    status = ""
    while time.monotonic() < deadline:
        polled = httpx.get(f"{asr}/asr/jobs/{job_id}", headers=auth_header, timeout=timeout)
        status = polled.json().get("status", "")
        if status in {"complete", "completed", "failed", "error"}:
            break
        time.sleep(2)
    if not check("the job reached a terminal state", status.startswith("complet"), f"status={status!r}"):
        return False

    # What `AppState.draftNote` does once the job completes. The note that
    # comes back is the one the app files under Recents.
    drafted = httpx.post(
        f"{note}/v1/notes/from-transcript",
        headers=auth_header,
        json={"asr_job_id": job_id, "title": "iOS smoke"},
        timeout=timeout,
    )
    if not check("POST /v1/notes/from-transcript made a note", drafted.status_code < 300, drafted.text):
        return False
    note_id = drafted.json()["id"]
    read_back = httpx.get(
        f"{note}/v1/notes/{note_id}", headers=auth_header, params={"include_content": "true"}, timeout=timeout
    )
    return check("the note reads back for the same account", read_back.status_code == 200, read_back.text)


# ── main ─────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--auth", default="http://localhost:8000")
    p.add_argument("--asr", default="http://localhost:8001")
    p.add_argument("--note", default="http://localhost:8006")
    p.add_argument("--mailpit", default="http://localhost:8025")
    p.add_argument("--seconds", type=float, default=1.0, help="how much audio to send (default 1)")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args()

    try:
        httpx.get(f"{args.auth}/health", timeout=5).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"auth-service is not reachable at {args.auth}: {exc}", file=sys.stderr)
        print("bring the stack up first:  make dev-up", file=sys.stderr)
        return 2

    account = create_and_verify(args.auth, args.mailpit, args.timeout)
    if account is None:
        skip(
            "create + verify an account",
            "this deployment serves no /auth/signup (BE-0 is not built yet); "
            "falling back to the seeded user so every later step still runs",
        )
        account = SEEDED
    email, password = account

    token = sign_in(args.auth, email, password, args.timeout)
    if token:
        capture(args.asr, args.note, token, args.seconds, args.timeout)

    failed = [name for name, ok, _ in results if not ok]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
