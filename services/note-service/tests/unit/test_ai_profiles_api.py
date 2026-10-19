"""`/v1/ai/prompt-profiles` and `/v1/ai/model-capabilities` (S3-04): save never
activates; activation and rollback move one pointer from the revision the admin saw;
members look, admins change; an id the workspace cannot see is a plain 404.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import ai_settings as settings_rules
from note_service.domain import prompt_profile_repository as repo
from note_service.domain import prompt_profiles as profiles

TENANT = UUID("22222222-2222-2222-2222-222222222222")
USER = UUID("11111111-1111-1111-1111-111111111111")

CAP = profiles.Capability(
    backend="mistral_eu", model_id="mistral-large-2512", processor="Mistral AI", region="EU",
    acknowledged=True, small_model=False, context_window=131_072,
    supported={"temperature": {"min": 0.0, "max": 1.0},
               "max_output_tokens": {"min": 256, "max": 8192},
               "timeout_s": {"min": 10.0, "max": 120.0}},
    unsupported={"seed": "no seed", "reasoning": "no reasoning"},
)  # fmt: skip
UNAGREED = profiles.Capability(
    backend="cand_frontier_eu", model_id="frontier", processor="Frontier", region="EU",
    acknowledged=False, small_model=False, context_window=131_072,
    supported=dict(CAP.supported), unsupported=dict(CAP.unsupported),
)  # fmt: skip


def _claims(role: str = "tenant_admin") -> Claims:
    return Claims(
        sub=USER,
        tid=TENANT,
        roles=[role, "member"] if role != "member" else ["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


class _Repo:
    """The workspace's rows; another workspace's ids simply are not here (RLS)."""

    def __init__(self) -> None:
        self.profiles: dict[UUID, repo.Profile] = {}
        self.versions: dict[UUID, repo.Version] = {}
        self.pointer = repo.Binding(
            profile_version_id=None, revision=0, activated_by=None, activated_at=None
        )
        self.history: list[dict[str, Any]] = []

    def version(
        self, profile_id: UUID, config: profiles.ProfileConfig, **over: Any
    ) -> repo.Version:
        number = 1 + sum(1 for v in self.versions.values() if v.profile_id == profile_id)
        v = repo.Version(
            id=uuid4(), profile_id=profile_id, version_number=number, config=config,
            contract_version=profiles.CONTRACT_VERSION, schema_version=profiles.schema_version(),
            algorithm_version=profiles.ALGORITHM_VERSION, content_hash=profiles.content_hash(config),
            created_by=USER, created_at=datetime.now(UTC),
        )  # fmt: skip
        for k, val in over.items():
            setattr(v, k, val)
        self.versions[v.id] = v
        return v

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r = self

        async def create_profile(
            conn: Any, *, tenant_id: UUID, name: str, description: str, created_by: UUID
        ) -> Any:  # noqa: E501
            p = repo.Profile(
                id=uuid4(),
                name=name,
                description=description,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )  # noqa: E501
            r.profiles[p.id] = p
            return p

        async def list_profiles(conn: Any) -> Any:
            return list(r.profiles.values())

        async def fetch_profile(conn: Any, *, profile_id: UUID) -> Any:
            return r.profiles.get(profile_id)

        async def create_version(
            conn: Any, *, tenant_id: UUID, profile_id: UUID, config: Any, created_by: UUID
        ) -> Any:  # noqa: E501
            return r.version(profile_id, config)

        async def list_versions(conn: Any, *, profile_id: UUID | None = None) -> Any:
            return [v for v in r.versions.values() if profile_id in (None, v.profile_id)]

        async def fetch_version(conn: Any, *, version_id: UUID) -> Any:
            return r.versions.get(version_id)

        async def binding(conn: Any, *, tenant_id: UUID) -> Any:
            return r.pointer

        async def activate(
            conn: Any,
            *,
            tenant_id: UUID,
            version_id: Any,
            expected_revision: int,
            actor: UUID,
            evaluation_ref: Any = None,
        ) -> Any:  # noqa: E501
            if expected_revision != r.pointer.revision:
                raise repo.ActivationConflictError(r.pointer.revision)
            r.history.append(
                {
                    "previous_version_id": r.pointer.profile_version_id,
                    "profile_version_id": version_id,
                }
            )
            r.pointer = repo.Binding(version_id, r.pointer.revision + 1, actor, datetime.now(UTC))
            return r.pointer

        async def history(conn: Any, *, limit: int = 50) -> Any:
            return list(r.history)

        for name, fn in {
            "create_profile": create_profile, "list_profiles": list_profiles,
            "fetch_profile": fetch_profile, "create_version": create_version,
            "list_versions": list_versions, "fetch_version": fetch_version,
            "binding": binding, "activate": activate, "history": history,
        }.items():  # fmt: skip
            monkeypatch.setattr(repo, name, fn)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_profiles

    audit: list[dict[str, Any]] = []

    async def _write_event(**kw: Any) -> None:
        audit.append(kw)

    deps.install_state(
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )  # type: ignore[arg-type]  # noqa: E501

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield None

    caps = {"list": [CAP, UNAGREED]}

    async def _caps(conn: Any, tenant_id: UUID) -> Any:
        return list(caps["list"])

    store = _Repo()
    store.install(monkeypatch)
    evidence = {"problem": None, "critical": None}

    async def _evidence(conn: Any, *, experiment_id: UUID, version_id: UUID) -> Any:
        return evidence["problem"]

    async def _critical(conn: Any, *, version_id: UUID, suite_version: str) -> Any:
        return evidence["critical"]

    monkeypatch.setattr(ai_profiles.experiments, "evidence_problem", _evidence)
    monkeypatch.setattr(ai_profiles.experiments, "acceptance_problem", _critical)
    monkeypatch.setattr(ai_profiles, "tenant_connection", _conn)
    monkeypatch.setattr(ai_profiles, "_capabilities", _caps)
    app = create_app()
    client = TestClient(app)

    def as_(role: str) -> None:
        app.dependency_overrides[deps.current_user] = lambda: _claims(role)

    as_("tenant_admin")
    yield SimpleNamespace(
        client=client, repo=store, audit=audit, as_=as_, caps=caps, evidence=evidence
    )
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def _profile(api: Any) -> str:
    return api.client.post("/v1/ai/prompt-profiles", json={"name": "Broadcasts"}).json()["id"]


EVAL = str(uuid4())
EXTRACTION = {"stages": {"extraction": "List what was said, in {{output_language}}."}}


def test_saving_a_version_never_activates_it(api: Any) -> None:
    pid = _profile(api)
    saved = api.client.post(f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION})
    assert saved.status_code == 201 and saved.json()["version_number"] == 1
    listing = api.client.get("/v1/ai/prompt-profiles").json()
    assert listing["active"] == {
        "profile_version_id": None,
        "revision": 0,
        "activated_by": None,
        "activated_at": None,
    }  # noqa: E501
    assert [e["kind"] for e in api.audit] == ["ai.profile_version_saved"]
    assert "List what was said" not in str(api.audit)  # instruction text never in audit


def test_v2_saved_while_v1_stays_active(api: Any) -> None:
    pid = _profile(api)
    v1 = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )  # noqa: E501
    changed = {
        "stages": {"extraction": "List every claim with its conditions, in {{output_language}}."}
    }
    v2 = api.client.post(f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": changed}).json()
    assert v2["version_number"] == 2
    assert (
        api.client.get("/v1/ai/prompt-profiles").json()["active"]["profile_version_id"] == v1["id"]
    )


def test_a_version_that_failed_the_critical_cases_stays_a_draft(api: Any) -> None:
    pid = _profile(api)
    v1 = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    api.evidence["critical"] = (
        "the critical cases failed: ml11_de_polarity_inversion: must_not_contain[0]"
    )
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )
    assert r.status_code == 409 and r.json()["code"] == "acceptance_required"
    assert "ml11" in r.json()["detail"]
    assert api.client.get("/v1/ai/prompt-profiles").json()["active"]["profile_version_id"] is None
    api.evidence["critical"] = None
    ok = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )
    assert ok.status_code == 200


def test_an_invalid_draft_is_422_with_every_problem_named(api: Any) -> None:
    pid = _profile(api)
    bad = {
        "stages": {"extraction": "{{secret}}"},
        "models": {"extraction": "mistral_eu"},
        "params": {"extraction": {"seed": 1, "temperature": 3.0}},
    }
    r = api.client.post(f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": bad})
    assert r.status_code == 422
    # RFC 9457: a dict detail is flattened, so its members are top-level.
    codes = {(p["field"], p["code"]) for p in r.json()["problems"]}
    assert codes >= {
        ("stages.extraction", "unknown_variable"),
        ("params.extraction.seed", "unsupported"),
        ("params.extraction.temperature", "out_of_range"),
    }
    # An endpoint or a key is not a setting at all.
    r = api.client.post(f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": {"api_key": "x"}})
    assert r.status_code == 422


def test_members_see_the_configuration_but_cannot_change_it(api: Any) -> None:
    pid = _profile(api)
    api.as_("member")
    listing = api.client.get("/v1/ai/prompt-profiles")
    assert listing.status_code == 200 and listing.json()["can_edit"] is False
    assert (
        api.client.post(
            f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
        ).status_code
        == 403
    )  # noqa: E501
    assert api.client.post("/v1/ai/prompt-profiles", json={"name": "x"}).status_code == 403
    assert (
        api.client.post(
            f"/v1/ai/prompt-profiles/{pid}/activate",
            json={"version_id": None, "expected_active_revision": 0},
        ).status_code
        == 403
    )  # noqa: E501


def test_activation_from_a_stale_revision_is_a_conflict_not_an_overwrite(api: Any) -> None:
    pid = _profile(api)
    v1 = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    first = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )  # noqa: E501
    assert first.status_code == 200 and first.json()["revision"] == 1
    stale = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": None, "expected_active_revision": 0},
    )  # noqa: E501
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "active_revision_conflict" and body["current_revision"] == 1
    # Rollback to the bundled profile from the revision actually seen.
    back = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": None, "expected_active_revision": 1},
    )  # noqa: E501
    assert back.status_code == 200 and back.json()["profile_version_id"] is None
    assert len(api.repo.history) == 2  # history is kept, never deleted


def test_an_incompatible_version_cannot_be_activated_and_says_why(api: Any) -> None:
    pid = UUID(_profile(api))
    old = api.repo.version(pid, profiles.ProfileConfig(), contract_version="2026-10-01.3")
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": str(old.id), "expected_active_revision": 0},
    )  # noqa: E501
    assert r.status_code == 409 and r.json()["code"] == "incompatible_version"
    assert "2026-10-01.3" in r.json()["detail"]


def test_a_binding_to_an_unacknowledged_processor_blocks_activation(api: Any) -> None:
    pid = UUID(_profile(api))
    bound = api.repo.version(
        pid, profiles.ProfileConfig(models={"composition": "cand_frontier_eu"})
    )
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": str(bound.id), "expected_active_revision": 0},
    )  # noqa: E501
    assert r.status_code == 409 and r.json()["code"] == "processor_unacknowledged"
    assert r.json()["processors"] == [{"name": "Frontier", "region": "EU"}]


def test_another_workspaces_version_is_a_plain_404(api: Any) -> None:
    pid = _profile(api)
    foreign = uuid4()  # exists only in another workspace: RLS never returns it
    assert api.client.get(f"/v1/ai/prompt-profiles/{pid}/versions/{foreign}").status_code == 404
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": str(foreign), "expected_active_revision": 0},
    )  # noqa: E501
    assert r.status_code == 404


def test_the_preview_is_what_a_generation_sends(api: Any) -> None:
    pid = _profile(api)
    v = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    preview = api.client.get(f"/v1/ai/prompt-profiles/{pid}/versions/{v['id']}?language=de").json()
    config = profiles.ProfileConfig.model_validate(EXTRACTION)
    assert preview["effective"]["extraction"] == profiles.effective_instructions(
        config, "extraction", language="de"
    )  # noqa: E501
    assert "List what was said, in German." in preview["effective"]["extraction"]
    assert preview["compatible"] is True


def test_capabilities_show_supported_and_unsupported_settings(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: E501
    from note_service.routers import ai_profiles

    monkeypatch.setattr(ai_profiles.ai_settings_router, "_writers", lambda: (None, None))
    body = api.client.get("/v1/ai/model-capabilities").json()
    [mistral] = [m for m in body["models"] if m["backend"] == "mistral_eu"]
    assert mistral["supported"]["temperature"] == {"min": 0.0, "max": 1.0}
    assert "seed" in mistral["unsupported"]
    assert body["stage_operations"] == {
        "extraction": "chat",
        "composition": "chat",
        "verification": "chat",
    }  # noqa: E501
    assert all("url" not in str(m).lower() and "key" not in m for m in body["models"])


def test_settings_rules_are_imported_for_acknowledgement() -> None:
    # The acknowledgement read is the AI-settings row: one source of truth.
    assert settings_rules.fetch is not None


def test_an_untested_version_stays_a_draft(api: Any) -> None:
    pid = _profile(api)
    v = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v["id"], "expected_active_revision": 0},
    )  # noqa: E501
    assert r.status_code == 409 and r.json()["code"] == "evaluation_required"
    api.evidence["problem"] = "a reviewer found missing condition in this version's output"
    r = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )  # noqa: E501
    assert r.status_code == 409 and "missing condition" in r.json()["detail"]
    assert api.repo.pointer.revision == 0  # nothing moved


def test_a_rollback_to_a_version_that_was_active_needs_no_new_evidence(api: Any) -> None:
    pid = _profile(api)
    v1 = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/versions", json={"config": EXTRACTION}
    ).json()
    api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 0, "evaluation_ref": EVAL},
    )  # noqa: E501
    api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": None, "expected_active_revision": 1},
    )  # noqa: E501
    back = api.client.post(
        f"/v1/ai/prompt-profiles/{pid}/activate",
        json={"version_id": v1["id"], "expected_active_revision": 2},
    )  # noqa: E501
    assert back.status_code == 200 and back.json()["profile_version_id"] == v1["id"]


def test_a_draft_preview_validates_and_resolves_without_saving(api: Any) -> None:
    from note_service.domain import prompt_profiles as profiles

    composition = profiles.bundled_text("composition").replace(
        "Write clear, concise notes in {{output_language}}.", "Short, in {{output_language}}."
    )
    body = {
        "config": {"stages": {"composition": composition, "extraction": "{{x}}"}},
        "language": "de",
    }
    r = api.client.post("/v1/ai/prompt-profiles/preview", json=body).json()
    assert {(p["field"], p["code"]) for p in r["problems"]} == {
        ("stages.extraction", "unknown_variable")
    }
    assert "Short, in German." in r["effective"]["composition"]
    assert "extraction" not in r["effective"]  # never a preview of an invalid stage
    assert r["calls"] == []  # a draft with problems resolves no calls
    assert r["required_variables"]["composition"] == ["output_language"]
    assert api.repo.versions == {}


def test_a_valid_draft_resolves_every_call_for_the_mode(api: Any) -> None:
    from note_service.domain import prompt_profiles as profiles

    body = {"config": {"stages": {"extraction": "List the claims."}}, "language": "de"}
    test = api.client.post("/v1/ai/prompt-profiles/preview", json=body).json()
    calls = {c["call"]: c for c in test["calls"]}
    assert test["flags"]["mode"] == "test" and test["flags"]["fidelity"] is True
    assert (
        calls["extraction"]["source"] == "profile"
        and "List the claims." in calls["extraction"]["system"]
    )
    assert calls["context"]["source"] == "code" and "verification.final" in calls
    expected = profiles.prompt_hashes(
        profiles.ProfileConfig(stages={"extraction": "List the claims."}), language="de"
    )
    assert {c: v["sha"] for c, v in calls.items()} == expected
    # Production here runs the previous engine: the text is shown as not sent.
    prod = api.client.post(
        "/v1/ai/prompt-profiles/preview", json={**body, "mode": "production"}
    ).json()
    assert prod["flags"]["profile_instructions_apply"] is False
    assert {c["call"]: c["source"] for c in prod["calls"]}["extraction"] == "not_applied"


def test_a_composition_edit_must_keep_its_sections_and_variable() -> None:
    from note_service.domain import prompt_profiles as profiles

    broken = (
        profiles.bundled_text("composition")
        .replace("SUMMARY SUBTASK", "SUMARY SUBTASK")
        .replace("{{output_language}}", "German")
    )
    codes = {
        (p.code, p.detail.split(":")[0])
        for p in profiles.validate(profiles.ProfileConfig(stages={"composition": broken}), [])
    }
    assert ("missing_variable", "keep {{output_language}}") in codes
    assert any(c == "missing_section" for c, _d in codes)
    assert any(c == "unknown_section" for c, _d in codes)
    assert (
        profiles.validate(profiles.ProfileConfig(stages={"composition": "   "}), [])[0].code
        == "empty"
    )
