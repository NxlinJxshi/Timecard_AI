# ConstructIQ

Construction timesheet anomaly detection for HCSS HeavyJob timecards.

```
Timecard → L0 Parse → L1 Rules → L2 Statistical baselines → L3 LLM agent → flag report
           (Max)      (Max)      (Nalin)                     (Kylan)
```

## Layout

| Path | What | Owner |
| --- | --- | --- |
| `schema/` | Pydantic v2 data contract (`Timecard`, `Entry`, `CostCodeDay`, `Flag`), loaders, JSON Schema export | Max |
| `rules/` | L1 deterministic rules, `run_rules(card) -> list[Flag]` | Max |
| `fixtures/cards/` | hand-transcribed ground truth for the 4 sample cards | Max |
| `stats/` | L2 baselines and scoring | Nalin |
| `agent/` | L3 LangGraph agent, serving | Kylan |
| `eval/` | eval datasets and harness | Kylan |
| `tests/` | pytest suite | all |

## Quick start

```bash
pip install -e ".[dev]"
pre-commit install
pytest                     # full suite
python -m rules            # run R1–R4 on every fixture card (exit 1 if anything fires)
python -m schema           # regenerate schema/json/*.schema.json
```

```python
from schema.io import load_cards
from rules import run_rules

cards = load_cards()
week = [c for c in cards if c.week_key == "wkA"]
flags = run_rules(week[0], week_cards=week)
days = week[0].cost_code_days()  # man-hours, headcount, unit rate per code
```

## Schema (v0.1.0, proposed for the Friday W1 freeze)

- **`Timecard`** — one crew card as it appears on screen: job, foreman, shift,
  `cost_codes` (code, description, quantity + unit, badges) and `rows`.
- **`ResourceRow`** — a labor or equipment row. Labor: class code, start/end window,
  `logged_total` (bold number in Start/End), `day_total` (Total line 1) and
  `week_total` (Total line 2). Equipment: hours only, plus `operator_id` when the
  row is drawn nested under an employee. `cells` maps cost code → hours.
- **`Hours`** — ST/OT/DT split. Accepts HCSS notation: `"8/4/1"`, `"5/2.5"`,
  `"/1"` (1 OT), `"//1"` (1 DT), `"8"`, or an object `{"st","ot","dt"}`.
- **`Entry`** — flat row per non-zero (resource × cost code) cell, with window,
  daily and weekly totals. Pandas-ready.
- **`CostCodeDay`** — per-code aggregate: labor ST/OT/DT, `crew_man_hours`
  (ST+OT+DT), `equipment_hours`, `headcount`, `unit_rate` = man-hours ÷ quantity
  (`None` for LS or zero quantity).
- **`Flag`** — `rule_id`, `layer`, `anomaly_class`, `status`
  (anomaly | warning | insufficient_data | parse_error), `field`, `entity`,
  `value`, `expected_low/high`, `severity`, `confidence`, `direction`,
  `rationale`, `evidence`.

Principles: models are immutable and reject unknown fields; the schema checks
structure, never arithmetic (a broken card must still load so L1 can flag it and
the seeder can build it); a card that fails validation becomes an L0
`parse_error` flag via `schema.io.load_card_or_flag`, never a silent drop.

## Rules R1–R4

| Rule | Check | Fires when |
| --- | --- | --- |
| R1 sum closure | cells → Total split → logged total, per bucket, labor and equipment | any mismatch |
| R2 window | logged total ≤ (end − start − break) + tolerance | over by more than 0.5 h |
| R3 OT/DT legality | California daily rule: ST ≤ 8, OT 8–12, DT past 12 | ST > 8 or DT short → high; premium paid early → medium, or a warning when weekly ST is already 40 |
| R4 weekly | weekly ≥ today; weekly ST ≤ 40; across same-week cards, same weekly line and days ≤ week | any violation |

### Rule assumptions

1. **Break = 0.5 h.** Not on the card. 14 of 16 labor rows show exactly
   window − 0.5 h; Dylan Powell shows a 1.0 h gap on both his days, which R2
   tolerates.
2. **Weekly line = full-week total.** On the samples two different days of the
   same week show identical weekly values, so it cannot be a running total.
   R4 defaults to `weekly_semantics="week_total"`; `"running"` (prior + today)
   is implemented for sources that report week-to-date, pending confirmation of
   what the HeavyJob API returns.
3. **R3 checks daily rules only.** The weekly 40 h rule and the seventh-day rule
   are not visible on one undated card, so premium hours paid early are a softer
   flag rather than an illegal split.
4. **`week_key` is inferred** for the samples (no dates on screen): cards 1–2 are
   week A, cards 3–4 week B, because shared workers show identical weekly totals
   within each pair and different totals across pairs.

## Fixtures

`fixtures/cards/*.json` transcribe `image1.png`–`image4.png` from the project
cell for cell. Text the UI truncated with "..." is stored as shown with a
`*_truncated: true` marker. Derived values (equipment category, unit rates) are
computed in code and are not stored in the fixtures. All four cards pass R1–R4.
