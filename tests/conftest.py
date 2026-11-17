from __future__ import annotations

import pytest

from schema import Timecard
from schema.io import load_cards


@pytest.fixture(scope="session")
def cards() -> dict[str, Timecard]:
    return {c.card_id: c for c in load_cards()}


@pytest.fixture
def card1(cards: dict[str, Timecard]) -> Timecard:
    return cards["card1-steven-powell-wkA"]


@pytest.fixture
def card4(cards: dict[str, Timecard]) -> Timecard:
    return cards["card4-dylan-powell-wkB"]


def with_row(card: Timecard, resource_id: str, **update) -> Timecard:
    """Return a re-validated copy of ``card`` with one row changed (models are frozen).

    Values use fixture notation, e.g. ``day_total="8/2"``, ``end="16:00"``.
    """
    data = card.model_dump(mode="json")
    for row in data["rows"]:
        if row["resource_id"] == resource_id:
            row.update(update)
    return Timecard.model_validate(data)
