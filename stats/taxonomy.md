# Anomaly taxonomy

Owner: Nalin · Status: draft for the Week 1 freeze · Code mirror: `stats/taxonomy.py`

The taxonomy is the project's shared contract. Every `Flag.anomaly_class` is a key
below. Max's seeder implements one perturbation per class. Kylan's evaluators
report precision and recall per class. The tests in `tests/test_taxonomy.py` keep
this file, the code mirror and `rules.ANOMALY_CLASS` in step.

Sections: 1 Class registry (this draft) · 2 Severity rubric · 3 Confidence rubric
· 4 Seeding perturbations. Sections 2–4 come next.

## 1. Class registry

### Design rules

1. **One class, one primary detector.** When a rule and a statistical score look at
   the same quantity, they get separate keys. `equipment_overlog` is a fixed cap
   (L1) and `equipment_intensity_high` is relative to history (L2). Merging them
   would mix a rule's catches with a model's catches in one recall number.
2. **L2 classes are one-tailed.** The two tails of a metric mean different things.
   A high unit rate is an over-billing risk. A low unit rate means hours went
   missing, which corrupts the baselines future bids are quoted from.
3. **Existing L1 keys are kept verbatim.** The four keys in `rules.ANOMALY_CLASS`
   are adopted unchanged. Keys for R5–R8 are proposed here for Max to adopt.

### Registry

| Key | Layer | Detector | Unit | Tail | Status |
| --- | --- | --- | --- | --- | --- |
| `arithmetic_break` | L1 | R1 | cell | mismatch | active |
| `time_window_violation` | L1 | R2 | worker-day | over | active |
| `illegal_ot_dt_split` | L1 | R3 | worker-day | mismatch | active |
| `weekly_total_break` | L1 | R4 | worker-week | mismatch | active |
| `equipment_without_operator` | L1 | R5 | equipment-day | over | planned |
| `equipment_overlog` | L1 | R6 | cost-code-day | over | planned |
| `within_crew_divergence` | L1 | R7 | worker-day | over | planned |
| `zero_quantity_hours` | L1 | R8 | cost-code-day | over | planned |
| `unit_rate_high` | L2 | L2.unit_rate | cost-code-day | over | planned |
| `unit_rate_low` | L2 | L2.unit_rate | cost-code-day | under | planned |
| `ot_share_high` | L2 | L2.ot_share | worker-day | over | planned |
| `equipment_intensity_high` | L2 | L2.equipment_intensity | cost-code-day | over | planned |
| `standby_padding_suspected` | L2 | L2.standby | equipment-day | over | provisional |

Definitions for every class are in `stats/taxonomy.py`. The L2 metrics are
defined formally below, because the statistics depend on them.

### L2 metric definitions

Notation, for card d and cost code c:

- `h_i = st_i + ot_i + dt_i` is worker i's hours in the cell for code c.
- `M = Σ_i h_i` is crew man-hours on the code (`CostCodeDay.crew_man_hours`).
- `Q` is installed quantity, with unit `u`.
- `E = Σ_k e_k` is equipment-hours on the code, summed over equipment rows k.

**Unit rate** (`L2.unit_rate`) is man-hours per unit of quantity:

```
r = M / Q            defined when u ≠ LS and Q > 0
r' = M / n_workers   fallback for LS or Q = 0 (man-hours per worker on the code)
```

The score is computed on log r against the baseline for code c. The fallback r'
is a different metric with its own baseline, so `r` and `r'` are never pooled
together.

**OT share** (`L2.ot_share`) is the premium share of a worker-day:

```
s = (ot + dt) / (st + ot + dt)    in [0, 1]
```

The lognormal model does not fit this metric. `s` is bounded in [0, 1] and is
exactly 0 on most normal days, so its distribution has a point mass at zero. The
modeling memo (deliverable 2) must choose its model separately. Candidates are a
two-part model (P(s > 0), then logit(s) given s > 0) or an empirical quantile of
s. This is an open item, not a settled choice.

**Equipment intensity** (`L2.equipment_intensity`) is equipment-hours per
labor-hour, computed per equipment category g from `schema.equipment`:

```
q_g = E_g / M        defined when M > 0
```

When M = 0 and E > 0 the ratio is undefined. That case is `equipment_without_operator`
(R5), not an L2 score, so the two classes never fire on the same entity.

**Standby padding** (`L2.standby`) stays provisional. Until HeavyJob's
standby-vs-operated field is confirmed, the proxy is high `q_g` on a code whose
quantity is zero or near its historical low. After confirmation it becomes a
baseline on standby hours directly.

### Open items for the freeze

- Max: adopt the R5–R8 keys above, or propose others.
- Kylan: confirm that per-class evaluation uses `anomaly_class` as the label.
- Nalin: choose the OT-share model in the modeling memo.

## 2. Severity rubric

Next (subproblem 1b).

## 3. Confidence rubric

Next (subproblem 1c).

## 4. Seeding perturbations

Next (subproblem 1d).
