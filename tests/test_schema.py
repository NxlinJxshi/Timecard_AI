from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from schema import (
    CostCode,
    Direction,
    EntityRef,
    Flag,
    Hours,
    ResourceRow,
    Severity,
    Timecard,
)
from schema.equipment import infer_equipment_category
from schema.io import FIXTURE_DIR, load_card_or_flag


@pytest.mark.parametrize(
    ("text", "st", "ot", "dt"),
    [
        ("8/4/1", 8, 4, 1),
        ("5/2.5", 5, 2.5, 0),
        ("/1", 0, 1, 0),
        ("//1", 0, 0, 1),
        ("8", 8, 0, 0),
        ("0.5", 0.5, 0, 0),
        ("8//1", 8, 0, 1),
    ],
)
def test_hours_parse_roundtrip(text, st, ot, dt):
    h = Hours.model_validate(text)
    assert (h.st, h.ot, h.dt) == (st, ot, dt)
    assert Hours.model_validate(h.to_hcss()) == h


@pytest.mark.parametrize("bad", ["8/x", "8/4/1/2", "-1", "8,4"])
def test_hours_rejects_garbage(bad):
    with pytest.raises(ValidationError):
        Hours.model_validate(bad)


def test_models_are_frozen_and_strict(card1):
    with pytest.raises(ValidationError):
        card1.card_id = "x"
    with pytest.raises(ValidationError):
        CostCode(code="51234.5", description="x", quantity=1, unit="EA", colour="red")


def test_equipment_rows_cannot_carry_ot():
    with pytest.raises(ValidationError):
        ResourceRow(resource_id="E1", resource_type="equipment", name="x", day_total="8/1")


def test_card_rejects_unknown_cost_code_and_operator(card1):
    data = card1.model_dump(mode="json")
    data["rows"][0]["cells"]["99999.9"] = {"st": 1}
    with pytest.raises(ValidationError, match="unknown cost codes"):
        Timecard.model_validate(data)
    data = card1.model_dump(mode="json")
    data["rows"][1]["operator_id"] = "000000"
    with pytest.raises(ValidationError, match="not on card"):
        Timecard.model_validate(data)


def test_schema_accepts_inconsistent_hours(card1):
    """Business consistency is L1's job: a broken card must still load."""
    data = card1.model_dump(mode="json")
    data["rows"][0]["day_total"] = {"st": 99, "ot": 0, "dt": 0}
    Timecard.model_validate(data)


def test_window_wraps_midnight():
    r = ResourceRow(
        resource_id="1",
        resource_type="labor",
        name="x",
        start="22:00",
        end="06:30",
        day_total="8",
    )
    assert r.window_hours == 8.5


def test_flag_range_validated():
    base = dict(
        rule_id="R1",
        layer="L1",
        field="f",
        entity=EntityRef(card_id="c"),
        severity=Severity.HIGH,
        confidence=1.0,
        direction=Direction.OVER,
        rationale="r",
    )
    Flag(**base, expected_low=1, expected_high=2)
    with pytest.raises(ValidationError):
        Flag(**base, expected_low=3, expected_high=2)
    with pytest.raises(ValidationError):
        Flag(**{**base, "confidence": 1.5})


def test_flag_json_schema_exports():
    schema = Flag.model_json_schema()
    assert {"rule_id", "field", "entity", "severity", "confidence", "rationale"} <= set(
        schema["properties"]
    )


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("FRD, F350, 19", "pickup_truck"),
        ("CHEVY, COLORA", "pickup_truck"),
        ("FRD, F550, 19 (A", "medium_duty_truck"),
        ("FRD, F600, 23 (A", "medium_duty_truck"),
        ("SKYTRAK 10054,", "telehandler"),
        ("BOBCAT S510, S", "skid_steer"),
        ("JLG 400S, BOOM", "boom_lift"),
        ("MYSTERY RIG", "unknown"),
    ],
)
def test_equipment_category(name, category):
    assert infer_equipment_category(name) == category


def test_bad_file_becomes_parse_error_flag(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text(json.dumps({"card_id": "broken"}))
    out = load_card_or_flag(bad)
    assert isinstance(out, Flag)
    assert out.status.value == "parse_error" and out.layer == "L0"
    assert isinstance(load_card_or_flag(next(FIXTURE_DIR.glob("*.json"))), Timecard)
