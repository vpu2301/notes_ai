"""Safety filter — completions are linguistic, never factual.

Table-driven: every money amount / percent / date-like / bare number in
the completion must appear verbatim in the typed text, else filtered.
"""

from __future__ import annotations

import pytest
from generation_service.domain.safety_filter import check_completion

PREFIX_PLAIN = "Домовилися про наступні кроки щодо"
PREFIX_WITH_MONEY = "Бюджет проєкту — $1,234.56, обговорили"
PREFIX_WITH_UAH = "Погоджено оплату 1 200 грн за годину, а також"
PREFIX_WITH_PERCENT = "Знижка 15% погоджена, обговорили"


@pytest.mark.parametrize(
    ("completion", "prefix", "allowed", "reason"),
    [
        # Plain prose passes.
        ("постачання та строків наступного релізу", PREFIX_PLAIN, True, None),
        ("маркетингової кампанії у наступному кварталі", PREFIX_PLAIN, True, None),
        # Invented money amount → filtered as money.
        ("бюджету, який складе $2,500 на квартал", PREFIX_PLAIN, False, "money"),
        # Money echoed from the prefix is fine.
        ("бюджету ($1,234.56 підтверджено)", PREFIX_WITH_MONEY, True, None),
        # Invented UAH amount with spaced thousands → filtered as money.
        ("оплати у розмірі 1 200 грн за годину", PREFIX_PLAIN, False, "money"),
        # UAH amount echoed from the prefix is fine.
        ("індексації ставки 1 200 грн з березня", PREFIX_WITH_UAH, True, None),
        # Invented scaled currency amount → filtered as money.
        ("expansion budget of €50k next year", PREFIX_PLAIN, False, "money"),
        # Invented percent → filtered as percent.
        ("знижки 15% для ключових клієнтів", PREFIX_PLAIN, False, "percent"),
        # Percent echoed from the prefix is fine.
        ("умови: знижка 15% лишається чинною", PREFIX_WITH_PERCENT, True, None),
        # Invented date-like fragment → filtered.
        ("зустрічі 12.05.2026 з підрядником", PREFIX_PLAIN, False, "date_like"),
        # Bare invented number → filtered.
        ("замовлення 38 одиниць обладнання", PREFIX_PLAIN, False, "bare_number"),
    ],
)
def test_filter_matrix(completion: str, prefix: str, allowed: bool, reason: str | None):
    verdict = check_completion(completion, text_before_cursor=prefix)
    assert verdict.allowed is allowed
    if not allowed:
        assert verdict.reason == reason
        assert verdict.matched is not None


def test_money_components_not_double_reported():
    # "$1,234.56" present in prefix: neither the amount nor the digit
    # groups inside it fire as date_like/bare_number.
    verdict = check_completion(
        "суму $1,234.56 затверджено остаточно", text_before_cursor=PREFIX_WITH_MONEY
    )
    assert verdict.allowed


def test_empty_completion_allowed():
    assert check_completion("", text_before_cursor=PREFIX_PLAIN).allowed
