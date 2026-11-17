"""Canonical data contract for ConstructIQ (L0 output, imported by L1/L2/L3).

Design rules
------------
* The schema validates *structure and types*, never business consistency.
  A card whose cells do not add up must still load: catching that is the job of
  the rule engine (L1), and the seeding harness needs to build broken cards.
* Every model is immutable (``frozen=True``) and rejects unknown fields
  (``extra="forbid"``). Use ``model_copy(update=...)`` to derive a variant.
* Hours cells are transcribed exactly as HCSS shows them ("8/2.5", "/1", "//1")
  and parsed into an :class:`Hours` split (straight / overtime / double-time).

Model map
---------
Timecard            one HCSS crew card (foreman x job x shift x day), as transcribed
  CostCode          a column header: code, description, quantity + unit
  ResourceRow       one labor or equipment row with its per-cost-code cells
Entry               flattened (resource x cost code) record -- one row per non-zero cell
CostCodeDay         per-card aggregate per cost code (man-hours, headcount, unit rate)
Flag                the shared finding model emitted by rules, the scorer and the LLM
"""

from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "0.1.0"

#: Units for which a man-hours-per-unit rate is not meaningful.
RATELESS_UNITS: frozenset[str] = frozenset({"LS"})

_EPS = 1e-9


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResourceType(StrEnum):
    LABOR = "labor"
    EQUIPMENT = "equipment"


class Severity(StrEnum):
    """Ordered roughly by billing-dollar impact (rubric owned by the taxonomy)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Direction(StrEnum):
    OVER = "over"  # logged value above what is supported/expected
    UNDER = "under"  # logged value below what is supported/expected
    MISMATCH = "mismatch"  # two sources disagree, no natural "too high" side
    NONE = "none"


class FlagStatus(StrEnum):
    ANOMALY = "anomaly"  # value deviates; act on it
    WARNING = "warning"  # borderline, or a legitimate explanation is plausible
    INSUFFICIENT_DATA = "insufficient_data"  # cannot judge (e.g. history below N)
    PARSE_ERROR = "parse_error"  # card failed validation; never drop silently


# ---------------------------------------------------------------------------
# Hours split
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"^\s*([0-9.]*)\s*(?:/\s*([0-9.]*)\s*(?:/\s*([0-9.]*)\s*)?)?$")


def parse_split(text: str) -> dict[str, float]:
    """Parse an HCSS hours cell into ``{"st", "ot", "dt"}``.

    ``"8/4/1"`` -> 8 ST, 4 OT, 1 DT · ``"5/2.5"`` -> 5 ST, 2.5 OT ·
    ``"/1"`` -> 1 OT · ``"//1"`` -> 1 DT · ``"8"`` -> 8 ST · ``""`` -> 0.
    """
    m = _SPLIT_RE.match(text)
    if not m:
        raise ValueError(f"not an HCSS hours split: {text!r}")
    parts = [float(p) if p else 0.0 for p in m.groups(default="")]
    return {"st": parts[0], "ot": parts[1], "dt": parts[2]}


def _num(x: float) -> str:
    return f"{x:g}"


class Hours(_Model):
    """Straight / overtime / double-time hours. Accepts ``"8/2.5"`` or a number."""

    st: float = Field(0.0, ge=0)
    ot: float = Field(0.0, ge=0)
    dt: float = Field(0.0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("hours cannot be a boolean")
        if isinstance(v, (int, float)):
            return {"st": float(v)}
        if isinstance(v, str):
            return parse_split(v)
        return v

    @property
    def total(self) -> float:
        return self.st + self.ot + self.dt

    @property
    def is_zero(self) -> bool:
        return self.total < _EPS

    def __add__(self, other: Hours) -> Hours:
        return Hours(st=self.st + other.st, ot=self.ot + other.ot, dt=self.dt + other.dt)

    def get(self, bucket: str) -> float:
        return {"st": self.st, "ot": self.ot, "dt": self.dt}[bucket]

    def to_hcss(self) -> str:
        """Render back in HCSS notation (inverse of :func:`parse_split`)."""
        st, ot, dt = (_num(x) if x > _EPS else "" for x in (self.st, self.ot, self.dt))
        if dt:
            return f"{st}/{ot}/{dt}"
        if ot:
            return f"{st}/{ot}"
        return st or "0"

    def __str__(self) -> str:
        return self.to_hcss()


BUCKETS: tuple[str, ...] = ("st", "ot", "dt")


# ---------------------------------------------------------------------------
# Card structure (what is physically on the timecard)
# ---------------------------------------------------------------------------


class CostCode(_Model):
    code: str = Field(pattern=r"^\d{5}\.\d+$", examples=["51234.5", "73020.7000"])
    description: str
    description_truncated: bool = False  # card UI cut the text off with "..."
    quantity: float = Field(ge=0)
    unit: str = Field(pattern=r"^[A-Z]{1,4}$", examples=["EA", "LS", "DA", "LD"])
    badges: tuple[str, ...] = ()  # raw UI badges, e.g. the green "N" (meaning TBD)

    @property
    def family(self) -> str:
        """Code family used for pooling, e.g. 51214.4 -> '51214'."""
        return self.code.split(".")[0]

    @property
    def division(self) -> str:
        """Coarsest pooling level, e.g. 51214.4 -> '51'."""
        return self.code[:2]


class ResourceRow(_Model):
    """One labor or equipment row on the card.

    Labor rows carry the Start/End window, the logged daily total (bold number in
    the Start/End column), the daily split (Total column, first line) and the
    weekly split (Total column, second line). Equipment rows carry only hours.
    """

    resource_id: str
    resource_type: ResourceType
    name: str  # employee name, or equipment make/model/year text
    name_truncated: bool = False
    resource_class: str | None = None  # labor craft/class code, e.g. "SLLS-L1"
    class_description: str | None = None  # e.g. "S CA Laborer Lea..."
    class_description_truncated: bool = False
    operator_id: str | None = None  # equipment drawn nested under an employee row
    badges: tuple[str, ...] = ()  # raw UI badges, e.g. the grey "A" (meaning TBD)
    start: time | None = None
    end: time | None = None
    logged_total: float | None = Field(None, ge=0)
    day_total: Hours
    week_total: Hours | None = None
    cells: dict[str, Hours] = Field(default_factory=dict)  # cost code -> hours

    @model_validator(mode="after")
    def _shape(self) -> ResourceRow:
        if self.resource_type is ResourceType.EQUIPMENT:
            if self.start or self.end or self.week_total is not None:
                raise ValueError(f"{self.resource_id}: equipment rows have no window/weekly")
            if self.resource_class or self.class_description:
                raise ValueError(f"{self.resource_id}: equipment rows have no labor class")
            for code, h in {"<total>": self.day_total, **self.cells}.items():
                if h.ot > _EPS or h.dt > _EPS:
                    raise ValueError(f"{self.resource_id}/{code}: equipment hours have no OT/DT")
        else:
            if self.operator_id is not None:
                raise ValueError(f"{self.resource_id}: operator_id is for equipment rows only")
            if (self.start is None) != (self.end is None):
                raise ValueError(f"{self.resource_id}: start and end must both be given")
        return self

    @property
    def is_labor(self) -> bool:
        return self.resource_type is ResourceType.LABOR

    @property
    def window_hours(self) -> float | None:
        """End minus start in hours; an end before the start means past midnight."""
        if self.start is None or self.end is None:
            return None
        d = Date(2000, 1, 1)
        s, e = datetime.combine(d, self.start), datetime.combine(d, self.end)
        if e <= s:
            e += timedelta(days=1)
        return (e - s).total_seconds() / 3600.0

    def cell_sum(self) -> Hours:
        total = Hours()
        for h in self.cells.values():
            total = total + h
        return total


class Timecard(_Model):
    schema_version: str = SCHEMA_VERSION
    card_id: str
    source: str | None = None  # image filename or API record id
    job_number: str
    job_name: str
    foreman_id: str
    foreman_name: str
    shift: int = 1
    date: Date | None = None  # not visible on the sample screenshots
    week_key: str | None = None  # groups cards of one payroll week; may be inferred
    cost_codes: tuple[CostCode, ...]
    rows: tuple[ResourceRow, ...]
    notes: tuple[str, ...] = ()  # transcription notes / known ambiguities

    @model_validator(mode="after")
    def _refs(self) -> Timecard:
        codes = [c.code for c in self.cost_codes]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate cost code columns")
        ids = [r.resource_id for r in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate resource rows")
        labor_ids = {r.resource_id for r in self.rows if r.is_labor}
        for r in self.rows:
            unknown = set(r.cells) - set(codes)
            if unknown:
                raise ValueError(f"{r.resource_id}: cells for unknown cost codes {sorted(unknown)}")
            if r.operator_id is not None and r.operator_id not in labor_ids:
                raise ValueError(f"{r.resource_id}: operator {r.operator_id} not on card")
        return self

    # -- lookups -----------------------------------------------------------

    def row(self, resource_id: str) -> ResourceRow:
        for r in self.rows:
            if r.resource_id == resource_id:
                return r
        raise KeyError(resource_id)

    def cost_code(self, code: str) -> CostCode:
        for c in self.cost_codes:
            if c.code == code:
                return c
        raise KeyError(code)

    @property
    def labor_rows(self) -> tuple[ResourceRow, ...]:
        return tuple(r for r in self.rows if r.is_labor)

    @property
    def equipment_rows(self) -> tuple[ResourceRow, ...]:
        return tuple(r for r in self.rows if not r.is_labor)

    # -- derived views -----------------------------------------------------

    def entries(self) -> list[Entry]:
        """Flatten to one :class:`Entry` per non-zero (resource, cost code) cell."""
        from schema.equipment import infer_equipment_category

        out: list[Entry] = []
        for r in self.rows:
            for c in self.cost_codes:
                h = r.cells.get(c.code)
                if h is None or h.is_zero:
                    continue
                out.append(
                    Entry(
                        card_id=self.card_id,
                        date=self.date,
                        week_key=self.week_key,
                        job_number=self.job_number,
                        foreman_id=self.foreman_id,
                        shift=self.shift,
                        cost_code=c.code,
                        cost_code_description=c.description,
                        quantity=c.quantity,
                        unit=c.unit,
                        resource_id=r.resource_id,
                        resource_type=r.resource_type,
                        resource_class=r.resource_class,
                        equipment_category=(
                            None if r.is_labor else infer_equipment_category(r.name)
                        ),
                        operator_id=r.operator_id,
                        st=h.st,
                        ot=h.ot,
                        dt=h.dt,
                        start=r.start,
                        end=r.end,
                        logged_total=r.logged_total,
                        day_st=r.day_total.st,
                        day_ot=r.day_total.ot,
                        day_dt=r.day_total.dt,
                        week_st=r.week_total.st if r.week_total else None,
                        week_ot=r.week_total.ot if r.week_total else None,
                        week_dt=r.week_total.dt if r.week_total else None,
                    )
                )
        return out

    def cost_code_days(self) -> list[CostCodeDay]:
        """Aggregate per cost code. Man-hours include ST + OT + DT."""
        out: list[CostCodeDay] = []
        for c in self.cost_codes:
            lab = [r.cells[c.code] for r in self.labor_rows if c.code in r.cells]
            eqp = [r.cells[c.code] for r in self.equipment_rows if c.code in r.cells]
            lab = [h for h in lab if not h.is_zero]
            eqp = [h for h in eqp if not h.is_zero]
            st, ot, dt = (sum(h.get(b) for h in lab) for b in BUCKETS)
            man_hours = st + ot + dt
            rateable = c.unit not in RATELESS_UNITS and c.quantity > _EPS
            out.append(
                CostCodeDay(
                    card_id=self.card_id,
                    date=self.date,
                    week_key=self.week_key,
                    job_number=self.job_number,
                    foreman_id=self.foreman_id,
                    cost_code=c.code,
                    cost_code_description=c.description,
                    quantity=c.quantity,
                    unit=c.unit,
                    labor_st=st,
                    labor_ot=ot,
                    labor_dt=dt,
                    crew_man_hours=man_hours,
                    equipment_hours=sum(h.total for h in eqp),
                    headcount=len(lab),
                    equipment_count=len(eqp),
                    unit_rate=(man_hours / c.quantity) if rateable else None,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Derived records (pandas-friendly, flat)
# ---------------------------------------------------------------------------


class Entry(_Model):
    """One (resource, cost code) cell with its card, window and running totals."""

    card_id: str
    date: Date | None
    week_key: str | None
    job_number: str
    foreman_id: str
    shift: int
    cost_code: str
    cost_code_description: str
    quantity: float
    unit: str
    resource_id: str
    resource_type: ResourceType
    resource_class: str | None
    equipment_category: str | None
    operator_id: str | None
    st: float
    ot: float
    dt: float
    start: time | None
    end: time | None
    logged_total: float | None
    day_st: float
    day_ot: float
    day_dt: float
    week_st: float | None
    week_ot: float | None
    week_dt: float | None

    @property
    def hours(self) -> float:
        return self.st + self.ot + self.dt


class CostCodeDay(_Model):
    """Crew aggregate for one cost code on one card.

    ``unit_rate`` = crew man-hours / quantity; ``None`` for LS units or zero
    quantity (L2 then falls back to an hours-based metric).
    """

    card_id: str
    date: Date | None
    week_key: str | None
    job_number: str
    foreman_id: str
    cost_code: str
    cost_code_description: str
    quantity: float
    unit: str
    labor_st: float
    labor_ot: float
    labor_dt: float
    crew_man_hours: float
    equipment_hours: float
    headcount: int
    equipment_count: int
    unit_rate: float | None


# ---------------------------------------------------------------------------
# Flag -- the one finding model every layer emits
# ---------------------------------------------------------------------------


class EntityRef(_Model):
    card_id: str
    resource_id: str | None = None
    cost_code: str | None = None
    date: Date | None = None


class Flag(_Model):
    """A single finding, as a PE reads it.

    ``field`` uses dotted paths into the card, e.g. ``day_total.ot``,
    ``week_total.st``, ``cells[51234.5].st``, ``logged_total``, ``unit_rate``.
    ``evidence`` holds every number the rationale cites, so an L3 explanation
    can quote them without doing arithmetic.
    """

    rule_id: str = Field(examples=["R1", "R3", "L2.unit_rate"])
    layer: Literal["L0", "L1", "L2", "L3"]
    anomaly_class: str | None = None  # key into the taxonomy (taxonomy.md)
    status: FlagStatus = FlagStatus.ANOMALY
    field: str
    entity: EntityRef
    value: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    direction: Direction
    rationale: str = Field(min_length=1)
    evidence: dict[str, float | str | None] = Field(default_factory=dict)

    @field_validator("expected_high")
    @classmethod
    def _range(cls, hi: float | None, info: Any) -> float | None:
        lo = info.data.get("expected_low")
        if lo is not None and hi is not None and lo > hi + _EPS:
            raise ValueError(f"expected_low {lo} > expected_high {hi}")
        return hi
