"""R1–R4: clean on the real cards, and each rule fires on a targeted break."""

from __future__ import annotations

import pytest

from rules import RuleConfig, expected_daily_split, run_rules
from rules.__main__ import main as cli_main
from schema import Direction, FlagStatus, Timecard
from tests.conftest import with_row


def _ids(flags):
    return sorted(f.rule_id for f in flags)


def test_sample_cards_are_rule_clean(cards):
    weeks: dict[str | None, list[Timecard]] = {}
    for c in cards.values():
        weeks.setdefault(c.week_key, []).append(c)
    for c in cards.values():
        assert run_rules(c, week_cards=weeks[c.week_key]) == [], c.card_id


def test_cli_exit_code_clean():
    assert cli_main([]) == 0


# --- R1 --------------------------------------------------------------------


def test_r1_cell_does_not_match_total(card1):
    bad = with_row(card1, "906882", cells={"51234.5": "3/2.5", "51238.5": "6"})
    flags = run_rules(bad)
    r1 = [f for f in flags if f.rule_id == "R1"]
    assert len(r1) == 1
    f = r1[0]
    assert f.field == "day_total.st" and f.direction is Direction.OVER
    assert f.value == 9 and f.expected_high == 8
    assert "Alfred Broyles" in f.rationale and "+1 h" in f.rationale
    assert f.confidence == 1.0 and f.layer == "L1"


def test_r1_split_does_not_match_logged_total(card1):
    bad = with_row(card1, "905224", logged_total=11.5)
    flags = [f for f in run_rules(bad) if f.rule_id == "R1"]
    assert [f.field for f in flags] == ["logged_total"]
    assert flags[0].direction is Direction.UNDER


def test_r1_equipment_row(card1):
    bad = with_row(card1, "AWP7241", cells={"51234.5": "2", "51238.5": "4", "51056.5": "3"})
    flags = [f for f in run_rules(bad) if f.rule_id == "R1"]
    assert len(flags) == 1 and flags[0].entity.resource_id == "AWP7241"
    assert "equipment" in flags[0].rationale


# --- R2 --------------------------------------------------------------------


def test_r2_fires_on_plan_example(card1):
    # the plan's example: logged 9/2 inside a 6:30 AM-4:00 PM window. With the
    # 0.5 h break seen on the sample cards that window supports at most 9 h.
    bad = with_row(
        card1,
        "906896",
        end="16:00",
        logged_total=11,
        day_total="9/2",
        cells={"51234.5": "7/2", "73180.7000": "2"},
    )
    flags = run_rules(bad)
    r2 = [f for f in flags if f.rule_id == "R2"]
    assert len(r2) == 1
    assert r2[0].expected_high == 9 and r2[0].value == 11
    assert "6:30 AM–4:00 PM" in r2[0].rationale and "at most 9 h" in r2[0].rationale
    assert "R3" in _ids(flags)  # 9 h ST also breaks the daily split


def test_r2_respects_tolerance(card1):
    # window 11 h - 0.5 break = 10.5 allowed; 11 h is within the 0.5 h tolerance
    ok = with_row(
        card1, "906882", logged_total=11, day_total="8/3", cells={"51234.5": "2/3", "51238.5": "6"}
    )
    assert [f for f in run_rules(ok) if f.rule_id == "R2"] == []
    over = with_row(
        card1,
        "906882",
        logged_total=11.5,
        day_total="8/3.5",
        cells={"51234.5": "2/3.5", "51238.5": "6"},
    )
    assert [f.rule_id for f in run_rules(over)] == ["R2"]


# --- R3 --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "split"),
    [(6, "6"), (8, "8"), (10.5, "8/2.5"), (12, "8/4"), (13, "8/4/1"), (14.5, "8/4/2.5")],
)
def test_expected_daily_split(total, split):
    assert str(expected_daily_split(total)) == split


def test_r3_straight_time_over_8(card1):
    bad = with_row(card1, "907542", day_total="9/1.5", cells={"51234.5": "5/1.5", "51056.5": "4"})
    r3 = [f for f in run_rules(bad) if f.rule_id == "R3"]
    assert len(r3) == 1 and r3[0].field == "day_total.st"
    assert r3[0].status is FlagStatus.ANOMALY and r3[0].evidence["expected_split"] == "8/2.5"


def test_r3_missing_double_time(card4):
    bad = with_row(card4, "904952", day_total="8/5", cells={"51214.4": "8/4", "73020.7000": "/1"})
    r3 = [f for f in run_rules(bad) if f.rule_id == "R3"]
    assert len(r3) == 1 and r3[0].field == "day_total.dt"
    assert r3[0].direction is Direction.UNDER and r3[0].expected_low == 1


def test_r3_early_premium_is_softer(card1):
    # 10 h paid as 7/3: legal only via weekly-40 or 7th-day rules
    bad = with_row(card1, "906896", day_total="7/3", cells={"51234.5": "5/3", "73180.7000": "2"})
    (f,) = [f for f in run_rules(bad) if f.rule_id == "R3"]
    # weekly ST on this card is 40, so the weekly rule may explain it -> warning
    assert f.status is FlagStatus.WARNING and f.confidence < 1
    no_cap = with_row(bad, "906896", week_total="32/6.5")
    (g,) = [f for f in run_rules(no_cap) if f.rule_id == "R3"]
    assert g.status is FlagStatus.ANOMALY and g.severity.value == "medium"


# --- R4 --------------------------------------------------------------------


def test_r4_weekly_below_today(card4):
    bad = with_row(card4, "904952", week_total="32/14")
    (f,) = [f for f in run_rules(bad) if f.rule_id == "R4"]
    assert f.field == "week_total.dt" and f.direction is Direction.UNDER


def test_r4_weekly_st_over_40(card1):
    bad = with_row(card1, "906896", week_total="42/6.5")
    (f,) = [f for f in run_rules(bad) if f.rule_id == "R4"]
    assert f.field == "week_total.st" and f.expected_high == 40


def test_r4_cross_card_mismatch(cards):
    c3 = cards["card3-dylan-powell-wkB"]
    c4 = cards["card4-dylan-powell-wkB"]
    bad3 = with_row(c3, "906896", week_total="32/11")
    flags = [f for f in run_rules(bad3, week_cards=[bad3, c4]) if f.rule_id == "R4"]
    assert [f.direction for f in flags] == [Direction.MISMATCH]
    assert flags[0].evidence["other_card"] == c4.card_id


def test_r4_days_exceed_week(cards):
    c3 = cards["card3-dylan-powell-wkB"]
    c4 = cards["card4-dylan-powell-wkB"]
    # Tyler: 3 + 4 OT across the two days; a weekly OT of 6 is impossible
    bad3 = with_row(c3, "907635", week_total="24/6")
    bad4 = with_row(c4, "907635", week_total="24/6")
    flags = [f for f in run_rules(bad4, week_cards=[bad3, bad4]) if f.rule_id == "R4"]
    assert len(flags) == 1 and flags[0].field == "week_total.ot"
    assert flags[0].evidence["sum_of_days"] == 7


def test_r4_week_complete_requires_equality(cards):
    c1 = cards["card1-steven-powell-wkA"]
    c2 = cards["card2-steven-powell-wkA"]
    cfg = RuleConfig(week_complete=True)
    flags = [f for f in run_rules(c1, week_cards=[c1, c2], config=cfg) if f.rule_id == "R4"]
    # two visible days cannot be the whole 40 h week -> every worker is short
    assert flags and all(f.direction is Direction.OVER for f in flags)


def test_r4_running_semantics(cards):
    c1 = cards["card1-steven-powell-wkA"]
    cfg = RuleConfig(weekly_semantics="running")
    prior = with_row(c1, "906896", week_total="16/2")
    today_ok = with_row(c1, "906896", week_total="24/4")  # 16/2 + 8/2
    today_bad = with_row(c1, "906896", week_total="24/5")
    assert [
        f
        for f in run_rules(today_ok, prior_card=prior, config=cfg)
        if f.entity.resource_id == "906896"
    ] == []
    (f,) = [
        f
        for f in run_rules(today_bad, prior_card=prior, config=cfg)
        if f.entity.resource_id == "906896"
    ]
    assert f.field == "week_total.ot" and f.expected_low == 4
