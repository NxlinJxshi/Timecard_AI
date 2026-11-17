"""L1 deterministic rule engine.

``run_rules(card) -> list[Flag]``. Each rule is pure arithmetic on one card (plus,
for R4, optional same-week context), needs no history, and emits a ``Flag`` with a
filled rationale and every number it used in ``evidence``.

R1  sum closure        cost-code cells add up to the Total column; split adds up to
                       the logged daily total (labor and equipment rows)
R2  window consistency logged daily total <= (end - start - break) + tolerance
R3  OT/DT legality     daily split is consistent with California daily rules
                       (OT past 8 h, DT past 12 h)
R4  weekly accumulation weekly line is consistent with today's hours and, when
                       other cards from the same week are supplied, with them

Assumptions (see README "Rule assumptions"):
* Break length is not on the card. Default 0.5 h, matching 14 of 16 labor rows in
  the samples (the other two have 1.0 h, which R2 tolerates).
* R3 checks the *daily* rules only. The CA weekly rule (OT past 40 h) and the
  seventh-consecutive-day rule can legitimately move hours into OT/DT earlier; the
  card shows no dates, so premium paid earlier than the daily rule requires is a
  WARNING-level flag, not an illegal-split flag.
* In the sample screenshots the "Weekly Hours" line is the full-week total, not a
  running total as of the card's day (two days of the same week show identical
  values). R4 therefore defaults to ``weekly_semantics="week_total"``; switch to
  ``"running"`` for sources where it is a to-date total (e.g. the HeavyJob API,
  to be confirmed).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from typing import Literal

from schema import (
    BUCKETS,
    Direction,
    EntityRef,
    Flag,
    FlagStatus,
    Hours,
    ResourceRow,
    Severity,
    Timecard,
)

EPS = 1e-6

#: Provisional mapping to Nalin's taxonomy keys; renamed at the Friday freeze.
ANOMALY_CLASS = {
    "R1": "arithmetic_break",
    "R2": "time_window_violation",
    "R3": "illegal_ot_dt_split",
    "R4": "weekly_total_break",
}


@dataclass(frozen=True)
class RuleConfig:
    break_hours: float = 0.5
    window_tolerance: float = 0.5
    daily_ot_after: float = 8.0
    daily_dt_after: float = 12.0
    weekly_st_cap: float = 40.0
    weekly_semantics: Literal["week_total", "running"] = "week_total"
    week_complete: bool = False  # True when week_cards holds every day of the week


DEFAULT_CONFIG = RuleConfig()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _h(x: float) -> str:
    return f"{x:g} h"


def _t(t: time | None) -> str:
    if t is None:
        return "?"
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _who(row: ResourceRow) -> str:
    return f"{row.name} ({row.resource_id})"


def _flag(
    card: Timecard,
    rule_id: str,
    row: ResourceRow | None,
    field: str,
    *,
    value: float | None,
    low: float | None = None,
    high: float | None = None,
    direction: Direction,
    rationale: str,
    evidence: dict[str, float | str | None],
    severity: Severity = Severity.HIGH,
    confidence: float = 1.0,
    status: FlagStatus = FlagStatus.ANOMALY,
    cost_code: str | None = None,
) -> Flag:
    return Flag(
        rule_id=rule_id,
        layer="L1",
        anomaly_class=ANOMALY_CLASS.get(rule_id),
        status=status,
        field=field,
        entity=EntityRef(
            card_id=card.card_id,
            resource_id=row.resource_id if row else None,
            cost_code=cost_code,
            date=card.date,
        ),
        value=value,
        expected_low=low,
        expected_high=high,
        severity=severity,
        confidence=confidence,
        direction=direction,
        rationale=rationale,
        evidence=evidence,
    )


def _dir(value: float, expected: float) -> Direction:
    return Direction.OVER if value > expected else Direction.UNDER


# ---------------------------------------------------------------------------
# R1 sum closure
# ---------------------------------------------------------------------------


def r1_sum_closure(card: Timecard, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Flag]:
    flags: list[Flag] = []
    for row in card.rows:
        cells = row.cell_sum()
        for b in BUCKETS:
            got, shown = cells.get(b), row.day_total.get(b)
            if abs(got - shown) > EPS:
                label = b.upper() if row.is_labor else "equipment"
                flags.append(
                    _flag(
                        card,
                        "R1",
                        row,
                        f"day_total.{b}",
                        value=got,
                        low=shown,
                        high=shown,
                        direction=_dir(got, shown),
                        rationale=(
                            f"{_who(row)}: cost-code cells sum to {_h(got)} {label} "
                            f"but the Total column shows {_h(shown)} "
                            f"(difference {got - shown:+g} h)."
                        ),
                        evidence={"cell_sum": got, "total_column": shown, "bucket": b},
                    )
                )
        if row.logged_total is not None and abs(row.day_total.total - row.logged_total) > EPS:
            split = row.day_total.total
            flags.append(
                _flag(
                    card,
                    "R1",
                    row,
                    "logged_total",
                    value=split,
                    low=row.logged_total,
                    high=row.logged_total,
                    direction=_dir(split, row.logged_total),
                    rationale=(
                        f"{_who(row)}: Total split {row.day_total} adds to {_h(split)} "
                        f"but the logged daily total is {_h(row.logged_total)}."
                    ),
                    evidence={
                        "split": str(row.day_total),
                        "split_sum": split,
                        "logged_total": row.logged_total,
                    },
                )
            )
    return flags


# ---------------------------------------------------------------------------
# R2 window consistency
# ---------------------------------------------------------------------------


def r2_window(card: Timecard, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Flag]:
    flags: list[Flag] = []
    for row in card.labor_rows:
        window = row.window_hours
        if window is None:
            continue
        logged = row.logged_total if row.logged_total is not None else row.day_total.total
        allowed = window - cfg.break_hours
        if logged > allowed + cfg.window_tolerance + EPS:
            flags.append(
                _flag(
                    card,
                    "R2",
                    row,
                    "logged_total",
                    value=logged,
                    low=0.0,
                    high=allowed,
                    direction=Direction.OVER,
                    rationale=(
                        f"{_who(row)} logged {row.day_total} ({_h(logged)}) but the "
                        f"{_t(row.start)}–{_t(row.end)} window supports at most "
                        f"{_h(allowed)} after a {_h(cfg.break_hours)} break "
                        f"({logged - allowed:+g} h over; tolerance {_h(cfg.window_tolerance)})."
                    ),
                    evidence={
                        "start": _t(row.start),
                        "end": _t(row.end),
                        "window_hours": window,
                        "break_hours": cfg.break_hours,
                        "allowed_hours": allowed,
                        "logged_hours": logged,
                        "tolerance": cfg.window_tolerance,
                    },
                )
            )
    return flags


# ---------------------------------------------------------------------------
# R3 OT/DT legality (California daily rules)
# ---------------------------------------------------------------------------


def expected_daily_split(total: float, cfg: RuleConfig = DEFAULT_CONFIG) -> Hours:
    st = min(total, cfg.daily_ot_after)
    dt = max(total - cfg.daily_dt_after, 0.0)
    return Hours(st=st, ot=total - st - dt, dt=dt)


def r3_ot_dt(card: Timecard, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Flag]:
    flags: list[Flag] = []
    for row in card.labor_rows:
        got = row.day_total
        total = got.total
        exp = expected_daily_split(total, cfg)
        ev: dict[str, float | str | None] = {
            "logged_split": str(got),
            "daily_total": total,
            "expected_split": str(exp),
            "ot_after": cfg.daily_ot_after,
            "dt_after": cfg.daily_dt_after,
        }
        if got.st > cfg.daily_ot_after + EPS:
            flags.append(
                _flag(
                    card,
                    "R3",
                    row,
                    "day_total.st",
                    value=got.st,
                    low=0.0,
                    high=cfg.daily_ot_after,
                    direction=Direction.OVER,
                    evidence=ev,
                    rationale=(
                        f"{_who(row)} logged {got} for {_h(total)}: {_h(got.st)} straight "
                        f"time exceeds the {_h(cfg.daily_ot_after)} daily limit. Under CA "
                        f"daily rules the split should be {exp}."
                    ),
                )
            )
        if got.dt + EPS < exp.dt:
            flags.append(
                _flag(
                    card,
                    "R3",
                    row,
                    "day_total.dt",
                    value=got.dt,
                    low=exp.dt,
                    high=exp.dt,
                    direction=Direction.UNDER,
                    evidence=ev,
                    rationale=(
                        f"{_who(row)} logged {got} for {_h(total)}: hours past "
                        f"{_h(cfg.daily_dt_after)} must be double time ({_h(exp.dt)}), "
                        f"but only {_h(got.dt)} DT is logged. Expected split {exp}."
                    ),
                )
            )
        illegal = got.st > cfg.daily_ot_after + EPS or got.dt + EPS < exp.dt
        differs = any(abs(got.get(b) - exp.get(b)) > EPS for b in BUCKETS)
        if differs and not illegal:
            # Premium paid earlier than the daily rule requires. Legitimate on a
            # 7th consecutive day or once 40 weekly ST hours are reached.
            weekly_cap_hit = (
                row.week_total is not None and row.week_total.st >= cfg.weekly_st_cap - EPS
            )
            ev["weekly_st"] = row.week_total.st if row.week_total else None
            field = "day_total.dt" if got.dt > exp.dt + EPS else "day_total.ot"
            value = got.dt if field.endswith("dt") else got.ot
            expected = exp.dt if field.endswith("dt") else exp.ot
            flags.append(
                _flag(
                    card,
                    "R3",
                    row,
                    field,
                    value=value,
                    low=expected,
                    high=expected,
                    direction=Direction.OVER,
                    evidence=ev,
                    status=FlagStatus.WARNING if weekly_cap_hit else FlagStatus.ANOMALY,
                    severity=Severity.LOW if weekly_cap_hit else Severity.MEDIUM,
                    confidence=0.4 if weekly_cap_hit else 0.7,
                    rationale=(
                        f"{_who(row)} logged {got} for {_h(total)}; CA daily rules give "
                        f"{exp}. Premium hours above the daily requirement are only "
                        f"justified by the weekly 40 h rule or a 7th consecutive day"
                        + (
                            f" (weekly ST is already {_h(row.week_total.st)}, so the "
                            f"weekly rule may apply)."
                            if weekly_cap_hit and row.week_total
                            else "; the card shows no date to confirm either."
                        )
                    ),
                )
            )
    return flags


# ---------------------------------------------------------------------------
# R4 weekly accumulation
# ---------------------------------------------------------------------------


def r4_weekly(
    card: Timecard,
    cfg: RuleConfig = DEFAULT_CONFIG,
    week_cards: Sequence[Timecard] = (),
    prior_card: Timecard | None = None,
) -> list[Flag]:
    flags: list[Flag] = []
    others = [
        c
        for c in {c.card_id: c for c in week_cards}.values()
        if c.card_id != card.card_id
        and (card.week_key is None or c.week_key is None or c.week_key == card.week_key)
    ]

    for row in card.labor_rows:
        wk = row.week_total
        if wk is None:
            continue

        # (a) the week must contain today
        for b in BUCKETS:
            if wk.get(b) + EPS < row.day_total.get(b):
                flags.append(
                    _flag(
                        card,
                        "R4",
                        row,
                        f"week_total.{b}",
                        value=wk.get(b),
                        low=row.day_total.get(b),
                        direction=Direction.UNDER,
                        rationale=(
                            f"{_who(row)}: weekly {b.upper()} is {_h(wk.get(b))} but today "
                            f"alone logs {_h(row.day_total.get(b))} {b.upper()}."
                        ),
                        evidence={"weekly": str(wk), "today": str(row.day_total), "bucket": b},
                    )
                )

        # (b) CA weekly cap on straight time
        if wk.st > cfg.weekly_st_cap + EPS:
            flags.append(
                _flag(
                    card,
                    "R4",
                    row,
                    "week_total.st",
                    value=wk.st,
                    low=0.0,
                    high=cfg.weekly_st_cap,
                    direction=Direction.OVER,
                    rationale=(
                        f"{_who(row)}: {_h(wk.st)} weekly straight time exceeds the "
                        f"{_h(cfg.weekly_st_cap)} weekly limit; hours past 40 are overtime."
                    ),
                    evidence={"weekly": str(wk), "weekly_st_cap": cfg.weekly_st_cap},
                )
            )

        if cfg.weekly_semantics == "week_total":
            # (c) every card of the same week shows the same weekly line
            known = row.day_total
            seen_on = [card.card_id]
            for other in others:
                try:
                    orow = other.row(row.resource_id)
                except KeyError:
                    continue
                known = known + orow.day_total
                seen_on.append(other.card_id)
                if orow.week_total is not None and orow.week_total != wk:
                    flags.append(
                        _flag(
                            card,
                            "R4",
                            row,
                            "week_total",
                            value=wk.total,
                            low=orow.week_total.total,
                            high=orow.week_total.total,
                            direction=Direction.MISMATCH,
                            rationale=(
                                f"{_who(row)}: weekly line is {wk} here but {orow.week_total} "
                                f"on {other.card_id} (same week)."
                            ),
                            evidence={
                                "weekly_here": str(wk),
                                "weekly_other": str(orow.week_total),
                                "other_card": other.card_id,
                            },
                        )
                    )
            # (d) days we can see cannot add up to more than the week
            if len(seen_on) > 1:
                for b in BUCKETS:
                    k, w = known.get(b), wk.get(b)
                    over = k > w + EPS
                    short = cfg.week_complete and k + EPS < w
                    if over or short:
                        flags.append(
                            _flag(
                                card,
                                "R4",
                                row,
                                f"week_total.{b}",
                                value=w,
                                low=k,
                                high=k if cfg.week_complete else None,
                                direction=Direction.UNDER if over else Direction.OVER,
                                rationale=(
                                    f"{_who(row)}: the {len(seen_on)} cards of this week "
                                    f"sum to {_h(k)} {b.upper()}, but the weekly line "
                                    f"shows {_h(w)}."
                                ),
                                evidence={
                                    "cards": ", ".join(seen_on),
                                    "sum_of_days": k,
                                    "weekly": w,
                                    "bucket": b,
                                },
                            )
                        )
        elif prior_card is not None:
            # running semantics: today's weekly = prior weekly + today
            try:
                prow = prior_card.row(row.resource_id)
            except KeyError:
                prow = None
            if prow is not None and prow.week_total is not None:
                exp = prow.week_total + row.day_total
                for b in BUCKETS:
                    if abs(wk.get(b) - exp.get(b)) > EPS:
                        flags.append(
                            _flag(
                                card,
                                "R4",
                                row,
                                f"week_total.{b}",
                                value=wk.get(b),
                                low=exp.get(b),
                                high=exp.get(b),
                                direction=_dir(wk.get(b), exp.get(b)),
                                rationale=(
                                    f"{_who(row)}: week-to-date {b.upper()} should be "
                                    f"{_h(prow.week_total.get(b))} (prior) + "
                                    f"{_h(row.day_total.get(b))} (today) = "
                                    f"{_h(exp.get(b))}, but the card shows {_h(wk.get(b))}."
                                ),
                                evidence={
                                    "prior_card": prior_card.card_id,
                                    "prior_weekly": prow.week_total.get(b),
                                    "today": row.day_total.get(b),
                                    "weekly": wk.get(b),
                                    "bucket": b,
                                },
                            )
                        )
    return flags


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_rules(
    card: Timecard,
    *,
    week_cards: Sequence[Timecard] = (),
    prior_card: Timecard | None = None,
    config: RuleConfig = DEFAULT_CONFIG,
) -> list[Flag]:
    """Run R1–R4 on one card. ``week_cards`` / ``prior_card`` only feed R4."""
    return [
        *r1_sum_closure(card, config),
        *r2_window(card, config),
        *r3_ot_dt(card, config),
        *r4_weekly(card, config, week_cards=week_cards, prior_card=prior_card),
    ]
