"""Anomaly taxonomy: the machine-readable mirror of ``stats/taxonomy.md``.

Every ``Flag.anomaly_class`` emitted anywhere in the pipeline must be a key in
:data:`BY_KEY`. The seeder (``inject(card, anomaly_class, magnitude)``) and the
per-class evaluators both iterate over :data:`TAXONOMY`, so this module is the
single source of truth for *which* classes exist.

Scope of this file (subproblem 1a): identity, definition, detection layer,
detector id, unit of analysis, tail(s) and the card field a flag points at.
Severity, confidence and seeding perturbations are added in 1b-1d.

Design rules
------------
* One class has exactly one primary detector. Where a deterministic rule and a
  statistical score both look at the same quantity (equipment hours), they are
  separate classes with separate keys, so per-class precision/recall never
  mixes a rule's catches with a model's catches.
* An L2 class is one-tailed. The two tails of a metric are different classes
  (``unit_rate_high`` vs ``unit_rate_low``) because they carry different
  business meaning: over-billing vs corrupted future bids.
* L1 keys already used by ``rules.ANOMALY_CLASS`` are adopted verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from schema import Direction


class Layer(StrEnum):
    L1 = "L1"  # deterministic rule, no history needed
    L2 = "L2"  # statistical score against a historical baseline


class Unit(StrEnum):
    """The entity one flag of this class is about (one row in the eval set)."""

    CELL = "cell"  # one (resource, cost code) cell, or one row's totals
    WORKER_DAY = "worker_day"  # one labor row on one card
    WORKER_WEEK = "worker_week"  # one worker across a payroll week
    COST_CODE_DAY = "cost_code_day"  # one cost code column on one card
    EQUIPMENT_DAY = "equipment_day"  # one equipment row on one card


class ClassStatus(StrEnum):
    ACTIVE = "active"  # detector exists in the repo
    PLANNED = "planned"  # detector scheduled (R5-R8, score.py); key proposed
    PROVISIONAL = "provisional"  # definition depends on an unanswered data question


@dataclass(frozen=True)
class AnomalyClass:
    key: str
    name: str
    layer: Layer
    detector: str  # rule id ("R1") or L2 metric id ("L2.unit_rate")
    unit: Unit
    direction: Direction  # the tail; MISMATCH for two-source disagreements
    field: str  # Flag.field convention, dotted path into the card
    definition: str
    status: ClassStatus


TAXONOMY: tuple[AnomalyClass, ...] = (
    # ---- L1: deterministic (Max) ------------------------------------------
    AnomalyClass(
        key="arithmetic_break",
        name="Arithmetic break",
        layer=Layer.L1,
        detector="R1",
        unit=Unit.CELL,
        direction=Direction.MISMATCH,
        field="day_total",
        definition=(
            "A row's cost-code cells do not sum to its Total split, or the split does "
            "not sum to the logged daily total, in any of ST/OT/DT."
        ),
        status=ClassStatus.ACTIVE,
    ),
    AnomalyClass(
        key="time_window_violation",
        name="Time-window violation",
        layer=Layer.L1,
        detector="R2",
        unit=Unit.WORKER_DAY,
        direction=Direction.OVER,
        field="logged_total",
        definition=(
            "Logged daily hours exceed the Start/End window minus the break by more "
            "than the tolerance: hours were billed that the clock does not contain."
        ),
        status=ClassStatus.ACTIVE,
    ),
    AnomalyClass(
        key="illegal_ot_dt_split",
        name="Illegal OT/DT split",
        layer=Layer.L1,
        detector="R3",
        unit=Unit.WORKER_DAY,
        direction=Direction.MISMATCH,
        field="day_total",
        definition=(
            "The ST/OT/DT split is inconsistent with California daily rules "
            "(OT after 8 h, DT after 12 h)."
        ),
        status=ClassStatus.ACTIVE,
    ),
    AnomalyClass(
        key="weekly_total_break",
        name="Weekly total break",
        layer=Layer.L1,
        detector="R4",
        unit=Unit.WORKER_WEEK,
        direction=Direction.MISMATCH,
        field="week_total",
        definition=(
            "The weekly line is inconsistent with today's hours or with the same "
            "worker's other cards in the same payroll week."
        ),
        status=ClassStatus.ACTIVE,
    ),
    AnomalyClass(
        key="equipment_without_operator",
        name="Equipment without an operator",
        layer=Layer.L1,
        detector="R5",
        unit=Unit.EQUIPMENT_DAY,
        direction=Direction.OVER,
        field="cells",
        definition="Equipment hours are logged on a cost code where no labor is logged.",
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="equipment_overlog",
        name="Equipment over-log (hard cap)",
        layer=Layer.L1,
        detector="R6",
        unit=Unit.COST_CODE_DAY,
        direction=Direction.OVER,
        field="equipment_hours",
        definition=(
            "Equipment-hours on a cost code exceed a fixed per-category multiple of "
            "the labor-hours on that code. A cap, not a baseline."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="within_crew_divergence",
        name="Within-crew divergence",
        layer=Layer.L1,
        detector="R7",
        unit=Unit.WORKER_DAY,
        direction=Direction.OVER,
        field="cells",
        definition=(
            "On one card and one cost code, a worker's hours deviate from the rest of "
            "the crew beyond tolerance: the site's own logs disagree with each other."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="zero_quantity_hours",
        name="Hours on zero quantity",
        layer=Layer.L1,
        detector="R8",
        unit=Unit.COST_CODE_DAY,
        direction=Direction.OVER,
        field="quantity",
        definition=(
            "Labor hours are logged repeatedly against a cost code that reports zero "
            "installed quantity."
        ),
        status=ClassStatus.PLANNED,
    ),
    # ---- L2: statistical (Nalin) --------------------------------------------
    AnomalyClass(
        key="unit_rate_high",
        name="Unit rate high (over-billing risk)",
        layer=Layer.L2,
        detector="L2.unit_rate",
        unit=Unit.COST_CODE_DAY,
        direction=Direction.OVER,
        field="unit_rate",
        definition=(
            "Crew man-hours per unit of installed quantity are far above the cost "
            "code's historical baseline: more hours billed than the work explains. "
            "For LS or zero-quantity codes the metric falls back to man-hours per "
            "worker on the code, field 'cells'."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="unit_rate_low",
        name="Unit rate low (quote-corrupting under-log)",
        layer=Layer.L2,
        detector="L2.unit_rate",
        unit=Unit.COST_CODE_DAY,
        direction=Direction.UNDER,
        field="unit_rate",
        definition=(
            "Crew man-hours per unit are far below baseline. Hours were likely logged "
            "to another code or not at all, which corrupts the baselines future bids "
            "are quoted from. Same LS / zero-quantity fallback as unit_rate_high."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="ot_share_high",
        name="Overtime share high",
        layer=Layer.L2,
        detector="L2.ot_share",
        unit=Unit.WORKER_DAY,
        direction=Direction.OVER,
        field="day_total.ot",
        definition=(
            "The premium share (OT + DT) / (ST + OT + DT) of a worker-day is far above "
            "the cost code's history, even though the split itself may be legal."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="equipment_intensity_high",
        name="Equipment intensity high",
        layer=Layer.L2,
        detector="L2.equipment_intensity",
        unit=Unit.COST_CODE_DAY,
        direction=Direction.OVER,
        field="equipment_hours",
        definition=(
            "Equipment-hours per labor-hour on a cost code, by equipment category, is "
            "far above that code's historical baseline. Relative to history, unlike "
            "the fixed cap of equipment_overlog."
        ),
        status=ClassStatus.PLANNED,
    ),
    AnomalyClass(
        key="standby_padding_suspected",
        name="Suspected standby padding",
        layer=Layer.L2,
        detector="L2.standby",
        unit=Unit.EQUIPMENT_DAY,
        direction=Direction.OVER,
        field="cells",
        definition=(
            "Equipment is billed for hours the work did not need: high equipment "
            "intensity on a code with little or no installed quantity. Provisional "
            "until HeavyJob's standby-vs-operated field is confirmed; then it becomes "
            "a baseline on standby hours directly."
        ),
        status=ClassStatus.PROVISIONAL,
    ),
)

BY_KEY: dict[str, AnomalyClass] = {c.key: c for c in TAXONOMY}


def get_class(key: str) -> AnomalyClass:
    """Look up a class; raises ``KeyError`` with the valid keys listed."""
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown anomaly class {key!r}; valid: {sorted(BY_KEY)}") from None


def classes(layer: Layer | None = None) -> tuple[AnomalyClass, ...]:
    return tuple(c for c in TAXONOMY if layer is None or c.layer is layer)


def l2_class(detector: str, direction: Direction) -> str:
    """Map an L2 detector and the side of the baseline a value fell on to a class key.

    ``score.py`` computes a signed z; ``sign(z) > 0`` is ``Direction.OVER``. A
    detector with no class on that tail (e.g. OT share low) raises ``KeyError``,
    which tells the scorer that tail is not flagged.
    """
    for c in TAXONOMY:
        if c.layer is Layer.L2 and c.detector == detector and c.direction is direction:
            return c.key
    raise KeyError(f"no L2 class for {detector} on the {direction} tail")
