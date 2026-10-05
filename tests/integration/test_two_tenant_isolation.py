"""Two workspaces on one stack: nothing of A's (glossary names, note, generation, share
link, ASR job) reaches B's hint, job, transcript, search, logs, Redis, object keys or
eval report, and B cannot open anything of A's by id. The in-process worker uses an
engine that ECHOES ITS PROMPT (the incident's failure mode, made deterministic).
Requires ``RUN_DB_INTEGRATION=1``, ``make dev-up``, ``make migrate-up``; ``make test-isolation``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import pytest_asyncio

from .test_first_use_guarantee import (  # noqa: F401 — fixtures are used by name
    MASTER_KEY,
    _client,
    _email,
    _point_at_native_issuer,
    _serve_jwks_from,
    _sign_up,
    auth_app,
    note_app,
    su,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack (Postgres + Redis + MinIO)",
)

REPO = Path(__file__).resolve().parents[2]
API_DOCS = REPO / "docs" / "api"
# The suite's own queue, so the dev stack's asr-worker cannot race the echo engine.
STREAM = f"asr:jobs:isolation-{secrets.token_hex(4)}"


def _nonsense(stem: str) -> str:
    # Surname-shaped and unique per run, so leftovers cannot affect a later run.
    return stem + "".join(secrets.choice("bdfgklmnprstvz") for _ in range(5))


# ── the echoing engine: the incident, made deterministic ──────────────────


class EchoEngine:
    """An ASR backend that writes back its prompt, as Whisper does when the
    audio gives it nothing better — the 2026-09-25 transcript."""

    backend = "echo"
    model_name = "echo"
    is_loaded = True
    warmup_seconds = 0.0

    def __init__(self) -> None:
        self.prompts: list[str | None] = []

    async def warm_up(self) -> None:
        return None

    async def transcribe(self, audio_pcm, *, language, prompt, should_cancel=None):  # noqa: ANN001, ANN201
        from asr_models.output import (
            Segment,
            TranscriptionMetadata,
            TranscriptionOutput,
            WordTiming,
        )

        self.prompts.append(prompt)
        text = f"{prompt or ''} and then someone talked about boats".strip()
        words = [
            WordTiming(text=w, start_ms=i * 100, end_ms=i * 100 + 90, probability=0.9)
            for i, w in enumerate(text.split())
        ]
        return TranscriptionOutput(
            language="en",
            segments=[
                Segment(
                    text=text,
                    start_ms=0,
                    end_ms=words[-1].end_ms,
                    words=words,
                    avg_confidence=0.9,
                )
            ],
            metadata=TranscriptionMetadata(
                model="echo", vad_seconds_speech=1.0, infer_seconds=0.0, beam_size=1
            ),
        )

    async def aclose(self) -> None:
        return None


def _two_seconds_of_noise() -> bytes:
    """Not silence: the worker's no-speech guard would stop a silent file
    before the engine is ever asked, and the echo is what is under test."""
    rate = 16_000
    rng = np.random.default_rng(7)
    data = (rng.normal(0, 3000, rate * 2)).astype("<i2").tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


# ── what the suite watches: object writes and every log record ────────────


@dataclass
class Watch:
    object_keys: list[tuple[str, str]] = field(default_factory=list)
    records: list[logging.LogRecord] = field(default_factory=list)


class _Capture(logging.Handler):
    def __init__(self, sink: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record)


@pytest.fixture
def watch(monkeypatch: pytest.MonkeyPatch):
    from storage.s3_client import S3Client

    seen = Watch()
    original = S3Client.put_object

    async def recording_put(self, *, bucket: str, key: str, body: bytes) -> None:  # noqa: ANN001
        seen.object_keys.append((bucket, key))
        await original(self, bucket=bucket, key=key, body=body)

    monkeypatch.setattr(S3Client, "put_object", recording_put)

    handler = _Capture(seen.records)
    # Some service loggers do not propagate: attach to the root AND every logger.
    loggers = [logging.getLogger()] + [
        lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    levels = {lg: lg.level for lg in loggers}
    for lg in loggers:
        lg.addHandler(handler)
        if lg.level > logging.DEBUG or lg.level == logging.NOTSET:
            lg.setLevel(logging.DEBUG)
    try:
        yield seen
    finally:
        for lg in loggers:
            lg.removeHandler(handler)
            lg.setLevel(levels[lg])


# ── the services, the asr one on the suite's own queue ────────────────────


@pytest_asyncio.fixture
async def asr_app(monkeypatch: pytest.MonkeyPatch, auth_app):  # noqa: F811
    from asr_service.config import settings
    from asr_service.main import create_app

    monkeypatch.setattr(settings, "asr_jobs_stream", STREAM)
    _point_at_native_issuer(monkeypatch, settings)
    app = create_app()
    async with app.router.lifespan_context(app):
        _serve_jwks_from(app, auth_app)
        yield app


@pytest_asyncio.fixture
async def cleanup(su):  # noqa: F811
    """Rows the first-use teardown does not know about, removed before it
    runs (this fixture depends on `su`, so it is torn down first)."""
    yield su
    like = "%@firstuse.example"
    await su.execute(
        "DELETE FROM note_share_links WHERE note_id IN (SELECT n.id FROM notes n"
        " JOIN identities i ON i.id = n.primary_author_id WHERE i.email LIKE $1)",
        like,
    )
    await su.execute(
        "DELETE FROM workspace_glossary WHERE created_by IN"
        " (SELECT id FROM identities WHERE email LIKE $1)",
        like,
    )
    await su.execute(
        "UPDATE tenants SET status = 'active' WHERE id IN (SELECT tenant_id FROM"
        " tenant_memberships m JOIN identities i ON i.id = m.user_sub WHERE i.email LIKE $1)",
        like,
    )
    import redis.asyncio as aioredis

    r = aioredis.from_url("redis://localhost:6379/0")
    try:
        await r.delete(STREAM, f"{STREAM}:dlq")
    finally:
        await r.aclose()


# ── the two workspaces ────────────────────────────────────────────────────


@dataclass
class World:
    a_token: str
    b_token: str
    a_tenant: str
    b_tenant: str
    a_user: str
    b_user: str
    a_terms: list[str]
    b_term: str
    a_note: str
    a_item_key: str
    a_link_id: str
    a_job: str
    b_job: str
    b_hint: str

    def bearer(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.a_token if who == 'a' else self.b_token}"}

    @property
    def a_secrets(self) -> list[str]:
        return list(self.a_terms)

    @property
    def all_terms(self) -> list[str]:
        return [*self.a_terms, self.b_term]


async def _meeting_template(notes) -> dict[str, Any]:  # noqa: ANN001
    listed = await notes.get("/templates")
    assert listed.status_code == 200, listed.text
    meeting = [t for t in listed.json() if "meeting" in json.dumps(t).lower()]
    detail = await notes.get(f"/templates/{meeting[0]['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


async def _build(auth_app, note_app, asr_app, su) -> World:  # noqa: ANN001, F811
    a = await _sign_up(auth_app, _email())
    b = await _sign_up(auth_app, _email())
    a_terms = [_nonsense("Quorvex"), _nonsense("Blandimar"), _nonsense("Zeltrovane")]
    b_term = _nonsense("Pellucidor")
    ab = {"Authorization": f"Bearer {a['access_token']}"}
    bb = {"Authorization": f"Bearer {b['access_token']}"}

    async with _client(note_app, **ab) as notes:
        # A's glossary — what "Remember this?" writes after a speaker rename.
        for term in a_terms:
            added = await notes.post("/v1/glossary", json={"term": term, "kind": "person"})
            assert added.status_code in (200, 201), added.text
        template = await _meeting_template(notes)
        section = template["schema"]["sections"][0]["id"] if "schema" in template else "user_notes"
        created = await notes.post(
            "/v1/notes",
            json={
                "content": {
                    "template_id": template["id"],
                    "template_schema_version": template["schema_version"],
                    "title": f"Call with {a_terms[0]}",
                    "sections": [
                        {
                            "section_key": section,
                            "text": f"{a_terms[0]} and {a_terms[1]} agreed; {a_terms[2]} objected.",
                        }
                    ],
                }
            },
        )
        assert created.status_code == 201, created.text
        a_note = created.json()["id"]
        link = await notes.post(f"/v1/notes/{a_note}/public-link", json={})
        assert link.status_code in (200, 201), link.text

    link_id = await su.fetchval(
        "SELECT id FROM note_share_links WHERE note_id = $1 ORDER BY created_at DESC LIMIT 1",
        uuid.UUID(a_note),
    )
    # One written line, so the generated-items and dates routes have rows to refuse.
    generation = await su.fetchval(
        "INSERT INTO note_generations (tenant_id, note_id, job_id, requested_by, reason, status,"
        " prompt_version, finished_at) VALUES ($1, $2, $3, $4, 'auto', 'complete', 'isolation',"
        " now()) RETURNING id",
        uuid.UUID(a["tenant_id"]),
        uuid.UUID(a_note),
        uuid.uuid4(),
        uuid.UUID(a["identity"]["id"]),
    )
    item_key = secrets.token_hex(16)
    await su.execute(
        "INSERT INTO note_generated_items (tenant_id, note_id, generation_id, item_key, kind,"
        " section_key, text, quote, start_ms, end_ms, placement) VALUES ($1, $2, $3, $4,"
        " 'key_point', 'gen:overview', $5, $5, 0, 1000, 'written')",
        uuid.UUID(a["tenant_id"]),
        uuid.UUID(a_note),
        generation,
        item_key,
        f"{a_terms[0]} agreed with {a_terms[1]}",
    )

    async with _client(asr_app, **ab) as asr:
        a_hint_resp = None
        async with _client(note_app, **ab) as notes:
            a_hint_resp = (await notes.get("/v1/glossary/hint")).json()["hint"]
        a_job = await asr.post(
            "/asr/jobs",
            files={"audio": ("a.wav", _two_seconds_of_noise(), "audio/wav")},
            data={"language": "en", "vocabulary_hint": a_hint_resp},
        )
        assert a_job.status_code == 202, a_job.text

    async with _client(note_app, **bb) as notes:
        added = await notes.post("/v1/glossary", json={"term": b_term, "kind": "person"})
        assert added.status_code in (200, 201), added.text
        b_hint = (await notes.get("/v1/glossary/hint")).json()["hint"]
    async with _client(asr_app, **bb) as asr:
        b_job = await asr.post(
            "/asr/jobs",
            files={"audio": ("b.wav", _two_seconds_of_noise(), "audio/wav")},
            data={"language": "en", "vocabulary_hint": b_hint},
        )
        assert b_job.status_code == 202, b_job.text

    return World(
        a_token=a["access_token"],
        b_token=b["access_token"],
        a_tenant=a["tenant_id"],
        b_tenant=b["tenant_id"],
        a_user=a["identity"]["id"],
        b_user=b["identity"]["id"],
        a_terms=a_terms,
        b_term=b_term,
        a_note=a_note,
        a_item_key=item_key,
        a_link_id=str(link_id),
        a_job=a_job.json()["id"],
        b_job=b_job.json()["id"],
        b_hint=b_hint,
    )


@pytest_asyncio.fixture
async def world(auth_app, note_app, asr_app, cleanup) -> World:  # noqa: F811
    return await _build(auth_app, note_app, asr_app, cleanup)


def _contains_any(text: str, terms: list[str]) -> list[str]:
    folded = text.casefold()
    return [t for t in terms if t.casefold() in folded]


async def _stream_payload(job_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    import redis.asyncio as aioredis

    from messaging.redis_streams import _to_message

    r = aioredis.from_url("redis://localhost:6379/0")
    try:
        for msg_id, fields in await r.xrange(STREAM):
            msg = _to_message(STREAM, msg_id, fields)
            if msg.headers.get("job_id") == job_id:
                return json.loads(msg.value), msg.headers
    finally:
        await r.aclose()
    raise AssertionError(f"job {job_id} was never enqueued on {STREAM}")


async def _run_worker(job_id: str, monkeypatch: pytest.MonkeyPatch) -> EchoEngine:
    """The real worker's `_process_one` on this job, with the echo engine."""
    import redis.asyncio as aioredis

    from asr_service.config import settings as service_settings
    from asr_worker import main_deps, processor
    from asr_worker.config import settings as worker_settings
    from messaging.redis_streams import _to_message

    engine = EchoEngine()
    # The worker's defaults are compose hostnames.
    for name in ("db_app_role_dsn", "db_audit_writer_dsn", "db_crypto_writer_dsn", "redis_url"):
        monkeypatch.setattr(worker_settings, name, getattr(service_settings, name))
    monkeypatch.setattr(worker_settings, "s3_endpoint", service_settings.s3_endpoint)
    monkeypatch.setattr(worker_settings, "master_key_path", MASTER_KEY)
    monkeypatch.setattr(worker_settings, "asr_jobs_stream", STREAM)
    monkeypatch.setattr(worker_settings, "asr_jobs_dlq_stream", f"{STREAM}:dlq")
    monkeypatch.setattr(main_deps, "build_asr", lambda _name: engine)
    state = await main_deps.build_state()
    r = aioredis.from_url("redis://localhost:6379/0")
    try:
        for msg_id, fields in await r.xrange(STREAM):
            msg = _to_message(STREAM, msg_id, fields)
            if msg.headers.get("job_id") == job_id:
                await processor._process_one(state, msg)
                return engine
        raise AssertionError(f"job {job_id} not on {STREAM}")
    finally:
        await r.aclose()
        await main_deps.teardown_state(state)


# ── 1–3: the hint, the job, the transcript ────────────────────────────────


async def test_b_hint_has_none_of_a_terms(world: World, note_app) -> None:  # noqa: F811
    async with _client(note_app, **world.bearer("b")) as notes:
        hint = await notes.get("/v1/glossary/hint")
    assert hint.status_code == 200, hint.text
    assert world.b_term in hint.json()["hint"]
    assert not _contains_any(hint.text, world.a_terms)


async def test_b_job_payload_carries_only_b_hint(world: World) -> None:
    payload, headers = await _stream_payload(world.b_job)
    assert payload["tenant_id"] == world.b_tenant == headers["tenant_id"]
    assert payload["vocabulary_hint"] == world.b_hint
    assert not _contains_any(json.dumps(payload), world.a_terms)


async def test_an_echoing_worker_writes_b_hint_into_b_transcript_and_nothing_of_a(
    world: World, asr_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The incident, reproduced: the transcript IS the prompt. It is B's
    prompt, so B's transcript carries B's name — and none of A's."""
    engine = await _run_worker(world.b_job, monkeypatch)
    assert engine.prompts == [world.b_hint]
    async with _client(asr_app, **world.bearer("b")) as asr:
        result = await asr.get(f"/asr/jobs/{world.b_job}/result")
    assert result.status_code == 200, result.text
    assert world.b_term in result.text, "the echo did not reach the transcript"
    assert not _contains_any(result.text, world.a_terms)


def test_one_engine_instance_gives_each_call_only_its_own_prompt() -> None:
    """Two jobs back to back on the same engine: the second decoder call
    sees only the second job's prompt (unit-level; mocked model)."""
    from asr_worker.inference import WhisperEngine

    engine = WhisperEngine()
    seen: list[str | None] = []

    class _Model:
        def transcribe(self, audio, **kwargs):  # noqa: ANN001, ANN003, ANN201
            seen.append(kwargs.get("initial_prompt"))
            return iter(()), type("Info", (), {"language": "en", "language_probability": 1.0})()

    engine._model = _Model()  # type: ignore[attr-defined]
    chunk = np.zeros(16_000, dtype=np.float32)
    for prompt in ("Alpha Tenant", "Bravo Tenant"):
        engine._run_chunk(chunk, "en", prompt, 0)  # type: ignore[attr-defined]
    assert seen == ["Alpha Tenant", "Bravo Tenant"]


# ── 4: B cannot open anything of A's by id ────────────────────────────────


def _id_routes(service: str) -> list[tuple[str, str, dict[str, str]]]:
    """Every (method, path, required query) of a service's OpenAPI dump that takes a note
    or job id, with required query parameters filled so ownership checks answer.
    """
    spec = json.loads((API_DOCS / f"{service}-openapi.json").read_text("utf-8"))
    out = []
    for path, ops in spec["paths"].items():
        if "{note_id}" not in path and "{job_id}" not in path:
            continue
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete", "head"):
                continue
            query = {
                p["name"]: _sample(p.get("schema") or {})
                for p in op.get("parameters", [])
                if p.get("in") == "query" and p.get("required")
            }
            out.append((method, path, query))
    return out


def _sample(schema: dict[str, Any]) -> str:
    kinds = {schema.get("type")} | {s.get("type") for s in schema.get("anyOf", [])}
    if "integer" in kinds or "number" in kinds:
        return "1"
    if "boolean" in kinds:
        return "false"
    if schema.get("enum"):
        return str(schema["enum"][0])
    return str(uuid.uuid4()) if schema.get("format") == "uuid" else "x"


def _fill(path: str, world: World) -> str:
    values = {
        "note_id": world.a_note,
        "job_id": world.a_job,
        "item_key": world.a_item_key,
        "link_id": world.a_link_id,
        "user_sub": world.a_user,
        "version_number": "1",
        "section_key": "user_notes",
    }
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), str(uuid.uuid4())), path)


@pytest.mark.parametrize("service", ["note-service", "asr-service"])
async def test_b_cannot_open_anything_of_a_by_id(
    service: str,
    world: World,
    note_app,  # noqa: F811
    asr_app,
    su,  # noqa: F811
) -> None:
    app = note_app if service == "note-service" else asr_app
    routes = _id_routes(service)
    assert routes, f"no id routes found in the {service} dump"
    state_sql = (
        "SELECT (SELECT count(*) FROM note_versions WHERE note_id = $1),"
        " (SELECT count(*) FROM workspace_glossary WHERE tenant_id = $2 AND deleted_at IS NULL),"
        " (SELECT count(*) FROM note_share_links WHERE note_id = $1 AND revoked_at IS NULL)"
    )
    ids = (uuid.UUID(world.a_note), uuid.UUID(world.a_tenant))
    before = tuple(await su.fetchrow(state_sql, *ids))
    # The ids are real (A opens them), so a typo cannot make a route "refuse" B.
    own = f"/v1/notes/{world.a_note}" if service == "note-service" else f"/asr/jobs/{world.a_job}"
    async with _client(app, **world.bearer("a")) as client:
        assert (await client.get(own)).status_code == 200
    opened: list[str] = []
    async with _client(app, **world.bearer("b")) as client:
        for method, path, query in routes:
            url = _fill(path, world)
            kwargs: dict[str, Any] = {"params": query} if query else {}
            if method in ("post", "put", "patch"):
                kwargs["json"] = {}
            response = await client.request(method.upper(), url, **kwargs)
            leaked = _contains_any(response.text, world.a_secrets)
            if method in ("get", "head"):
                if response.status_code not in (403, 404) or leaked:
                    opened.append(f"{method.upper()} {path} → {response.status_code}")
            elif 200 <= response.status_code < 300 or leaked:
                opened.append(f"{method.upper()} {path} → {response.status_code}")
    assert not opened, "B reached A's resources:\n" + "\n".join(opened)
    # Nothing B sent changed A's note, glossary or share links.
    after = tuple(await su.fetchrow(state_sql, *ids))
    assert after == before, "B changed A's versions, glossary or links"


# ── 5: search ─────────────────────────────────────────────────────────────


async def test_b_search_finds_nothing_of_a(world: World, note_app) -> None:  # noqa: F811
    term = world.a_terms[0]
    async with _client(note_app, **world.bearer("a")) as notes:
        own = await notes.get("/v1/notes/search", params={"q": term})
    assert own.status_code == 200, own.text
    assert world.a_note in own.text, "search cannot find A's note for A — the check below is void"
    async with _client(note_app, **world.bearer("b")) as notes:
        other = await notes.get("/v1/notes/search", params={"q": term})
    assert other.status_code == 200, other.text
    assert world.a_note not in other.text
    assert not _contains_any(other.text, world.a_terms)


# ── 6: A suspended ────────────────────────────────────────────────────────


async def test_suspending_a_leaves_b_working_and_a_unreachable_to_b(
    world: World,
    note_app,  # noqa: F811
    su,  # noqa: F811
) -> None:
    await su.execute(
        "UPDATE tenants SET status = 'suspended' WHERE id = $1", uuid.UUID(world.a_tenant)
    )
    async with _client(note_app, **world.bearer("b")) as notes:
        hint = await notes.get("/v1/glossary/hint")
        assert hint.status_code == 200, hint.text
        assert world.b_term in hint.text and not _contains_any(hint.text, world.a_terms)
        mine = await notes.get("/v1/notes/search", params={"q": world.a_terms[0]})
        assert world.a_note not in mine.text
        theirs = await notes.get(f"/v1/notes/{world.a_note}")
        assert theirs.status_code in (403, 404)


# ── 7–8: Redis and object keys ────────────────────────────────────────────

# Keys with tenant data that do NOT start with `workspace:<tid>:`, each with
# the reason it is acceptable.
REDIS_ALLOWED: dict[str, str] = {
    r"^asr:jobs(:isolation-[0-9a-f]+)?(:dlq)?$": "the ASR queue stream; tenant_id is in every "
    "entry and the worker scopes by it (F-1: plaintext hint retention)",
    r"^mdx:streams:[^:]+:[^:]+:attempts$": "delivery attempt counters, ids only",
    r"^mdx:notifications:events(:dlq)?$": "notification stream; ids and counts only",
    r"^mdx:dict:worker:[^:]+:hb$": "dictation worker heartbeat, no tenant data",
    r"^mdx:nlp:cache:[0-9a-f]{64}$": "nlp result cache; the tenant id is inside the hashed "
    "key (F-3)",
    r"^mdx:nlp:rl:": "nlp rate limit counters",
    r"^mdx:revoked:": "session revocation list, identity-scoped",
    r"^mdx:auth:": "auth failure/lock counters, identity-scoped",
    r"^auth:": "auth rate limits and challenges, identity-scoped",
    r"^audio-clip:[0-9a-f-]{36}$": "clip registry {key, tenant_id, note_id}; the reader checks "
    "the tenant",
    r"^note:(resp-notify|share-mail-rl|clip-rl):": "per-link / per-user rate limits",
    r"^gen:inline-rl:": "per-user rate limit",
    r"^autocomplete:": "per-tenant/user phrase trie; tenant id in the key body",
    r"^mdx:notif:cap:": "notification caps; tenant id in the key body",
    r"^ai:budget:": "AI budget flag; tenant id in the key body",
    r"^mdx:notify:user:": "pub/sub channel, ids only",
    r"^rl:|^ratelimit:|^mdx:rl:": "rate limit counters",
    r"^mdx:asr:rl:[a-z_]+:[0-9a-f-]{36}:\d+$": "per-user asr rate limit windows (counts only)",
}


async def test_every_redis_key_with_tenant_data_is_prefixed_or_allowed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import redis.asyncio as aioredis

    await _run_worker(world.b_job, monkeypatch)
    r = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
    try:
        keys = [k async for k in r.scan_iter(count=1000)]
    finally:
        await r.aclose()
    tenant_ids = (world.a_tenant, world.b_tenant)
    unexplained = []
    for key in keys:
        if key.startswith("workspace:"):
            owner = key.split(":", 2)[1]
            assert owner not in tenant_ids or key.startswith(f"workspace:{owner}:"), key
            continue
        if not any(re.search(pattern, key) for pattern in REDIS_ALLOWED):
            unexplained.append(key)
    assert not unexplained, "keys without a tenant prefix or an allow-list reason:\n" + "\n".join(
        sorted(unexplained)
    )


# ── 9–10: logs and eval report ────────────────────────────────────────────


@pytest_asyncio.fixture
async def watched_world(watch: Watch, auth_app, note_app, asr_app, cleanup):  # noqa: F811
    """The world built WHILE writes and logs are being watched."""
    return watch, await _build(auth_app, note_app, asr_app, cleanup)


async def test_object_keys_during_both_flows_start_with_their_tenant(
    watched_world, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch, w = watched_world
    await _run_worker(w.b_job, monkeypatch)
    ours = {w.a_tenant, w.b_tenant}
    assert watch.object_keys, "no object was written — the watch is not wired"
    wrong = []
    for bucket, key in watch.object_keys:
        first = key.split("/", 1)[0]
        if first in ours:
            continue
        # Keys in other layouts must still name exactly one of our tenants.
        if not any(t in key for t in ours):
            wrong.append(f"{bucket}/{key}")
    assert not wrong, "objects written without their tenant in the key:\n" + "\n".join(wrong)


async def test_logs_during_both_flows_carry_no_terms_or_transcript(
    watched_world, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch, w = watched_world
    await _run_worker(w.b_job, monkeypatch)
    assert watch.records, "no log record was captured — the watch is not wired"
    leaked = []
    for record in watch.records:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — a malformed record is still a record
            message = str(record.msg)
        blob = (
            message
            + " "
            + " ".join(str(v) for k, v in vars(record).items() if k not in ("msg", "args"))
        )
        hits = _contains_any(blob, w.all_terms) + _contains_any(
            blob, ["someone talked about boats"]
        )
        if hits:
            leaked.append(f"{record.name}: {hits}")
    assert not leaked, "content reached the logs:\n" + "\n".join(leaked)


async def test_an_eval_report_from_b_run_carries_no_term_text(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    sys.path.insert(0, str(REPO / "scripts" / "eval"))
    sys.path.insert(0, str(REPO / "services" / "note-service" / "tests" / "unit"))
    import _common
    import notes_eval
    from meeting_doc_fakes import ScriptedProvider
    from notes_scoring import score_meeting

    monkeypatch.setattr(_common, "DOCS_EVAL", tmp_path)
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "eval" / "notes" / "m01_en_product_sync.json").read_text(
            "utf-8"
        )
    )
    # B's name spoken in the meeting and named as its speaker.
    for turn in fixture["transcript"][:2]:
        turn["text"] = f"{world.b_term} said: {turn['text']}"
    fixture.setdefault("gold", {})["speakers"] = {"SPEAKER_1": world.b_term}
    produced = await notes_eval.run_pipeline(fixture, ScriptedProvider())
    totals = notes_eval.Totals()
    row = notes_eval.score(fixture, produced, totals)
    row.update(score_meeting(fixture, produced))
    path = _common.write_report(
        "notes-pipeline", "scripted", {"runs": [{"run": 1, "meetings": [row]}]}
    )
    assert world.b_term not in path.read_text("utf-8")
