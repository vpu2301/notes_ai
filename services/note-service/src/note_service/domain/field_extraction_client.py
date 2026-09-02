"""Ask nlp-service to extract typed fields from a dictation (sprint 13).

Delivery path (ADR-0028): the ``field_extraction`` stage emits its
proposals on ``StageOutput.metadata``, which ``POST /nlp/process``
returns verbatim in its deterministic ``metadata`` body. Note-service
— the one service that holds BOTH the template (with its options) and
the draft — calls it at draft-assembly time and writes the result into
``NoteSection.field_specific_metadata``.

Fail-open by design: extraction is an assistive proposal, never a
precondition. A timeout, a non-200, or a malformed body yields no
metadata and the draft is created with prose only. Losing a proposal
costs the author one dropdown; failing the draft costs them the
dictation.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from template_models import CHOICE_FIELD_TYPES, TemplateDefinition

from ..config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=2.0, read=10.0, write=5.0, pool=5.0)

# The key the stage writes its proposals under.
_FIELDS_KEY = "field_extraction.fields"


def typed_sections_payload(definition: TemplateDefinition) -> list[dict[str, Any]]:
    """The wire shape nlp-service's ``TemplateSectionIn`` expects.

    Only typed sections are sent: options are the extractor's whole
    input, and a free-text section would just be noise in the request.
    """
    return [
        {
            "id": "00000000-0000-0000-0000-000000000000",
            "name": section.name,
            "aliases": list(section.voice_aliases),
            "section_key": section.id,
            "field_type": section.field_type.value,
            "options": [
                {"value": o.value, "label": o.label, "aliases": list(o.voice_aliases)}
                for o in section.options
            ],
        }
        for section in definition.sections
        if section.field_type in CHOICE_FIELD_TYPES and section.options
    ]


# Languages nlp-service's ``/nlp/process`` accepts (its ``language`` Literal).
EXTRACTION_LANGUAGES = frozenset({"uk", "en", "de"})


async def extract_fields(
    *,
    definition: TemplateDefinition,
    text: str,
    language: str,
    category: str | None,
    authorization: str,
) -> dict[str, dict[str, Any]]:
    """Return ``{section_key: field_specific_metadata}``; ``{}`` on any
    failure or when the template has no typed sections."""
    sections = typed_sections_payload(definition)
    if not sections or not text.strip():
        return {}
    if language not in EXTRACTION_LANGUAGES:
        # nlp-service has no rules for this language and would answer 422;
        # fail-open here the same way, without the round trip.
        return {}

    body = {
        "text": text,
        "language": language,
        "category": category,
        "is_partial": False,
        "template_sections": sections,
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.nlp_service_base_url, timeout=_TIMEOUT
        ) as client:
            resp = await client.post(
                "/nlp/process",
                json=body,
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "field_extraction.transport_error",
            extra={"error_class": type(exc).__name__, "error": str(exc)},
        )
        return {}

    if resp.status_code != 200:
        logger.warning(
            "field_extraction.non_200",
            extra={"status": resp.status_code, "body": resp.text[:200]},
        )
        return {}

    try:
        fields = resp.json().get("metadata", {}).get(_FIELDS_KEY, {})
    except ValueError:
        logger.warning("field_extraction.malformed_body")
        return {}

    if not isinstance(fields, dict):
        return {}
    return {k: v for k, v in fields.items() if isinstance(v, dict)}
