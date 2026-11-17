"""Ground-truth fixtures: structure, spot-checked cells, and derived aggregates."""

from __future__ import annotations

import pytest

from schema import SCHEMA_VERSION


def test_four_cards_load(cards):
    assert len(cards) == 4
    assert all(c.schema_version == SCHEMA_VERSION for c in cards.values())
    assert {c.source for c in cards.values()} == {f"image{i}.png" for i in range(1, 5)}


@pytest.mark.parametrize(
    ("card_id", "labor", "equipment", "codes"),
    [
        ("card1-steven-powell-wkA", 5, 6, 6),
        ("card2-steven-powell-wkA", 5, 6, 2),
        ("card3-dylan-powell-wkB", 5, 4, 3),
        ("card4-dylan-powell-wkB", 4, 4, 2),
    ],
)
def test_card_shape(cards, card_id, labor, equipment, codes):
    c = cards[card_id]
    assert (len(c.labor_rows), len(c.equipment_rows), len(c.cost_codes)) == (
        labor,
        equipment,
        codes,
    )


def test_spot_cells(cards):
    c1 = cards["card1-steven-powell-wkA"]
    assert str(c1.row("903784").cells["51234.5"]) == "5/2.5"
    assert str(c1.row("903784").cells["73020.7000"]) == "/1"
    assert str(c1.row("903784").week_total) == "40/10"
    assert c1.row("ACF02025").operator_id == "903784"
    assert c1.row("UAT7698").operator_id is None
    assert c1.cost_code("51056.5").quantity == 0.25 and c1.cost_code("51056.5").unit == "LS"
    c4 = cards["card4-dylan-powell-wkB"]
    assert str(c4.row("904952").day_total) == "8/4/1"
    assert str(c4.row("904952").cells["73020.7000"]) == "//1"


def test_cost_code_day_aggregates(cards):
    days = {d.cost_code: d for d in cards["card1-steven-powell-wkA"].cost_code_days()}
    steel = days["51234.5"]
    # 7.5 + 4.5 + 8.5 + 6.5 + 8 man-hours (ST + OT) over 12 EA
    assert steel.crew_man_hours == 35 and steel.headcount == 5
    assert steel.equipment_hours == 15 and steel.equipment_count == 6
    assert steel.unit_rate == pytest.approx(35 / 12)
    assert days["73180.7000"].unit_rate is None  # LS
    assert days["51214.4"].unit_rate is None  # 0 EA
    c2 = {d.cost_code: d for d in cards["card2-steven-powell-wkA"].cost_code_days()}
    assert c2["51234.5"].unit_rate == pytest.approx(50 / 155)


def test_entries_cover_every_nonzero_cell(cards):
    for c in cards.values():
        n_cells = sum(1 for r in c.rows for h in r.cells.values() if not h.is_zero)
        entries = c.entries()
        assert len(entries) == n_cells
        assert sum(e.hours for e in entries) == pytest.approx(
            sum(r.day_total.total for r in c.rows)
        )
