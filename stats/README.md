# stats/ — L2 statistical baselines (Nalin)

Planned: `taxonomy.md` (Fri W1), `synth.py` (Fri W1), `baselines.py` (Tue W2),
`score.py` (Thu W2), `query_baseline` / `explain_score` tools (Mon W3).

Inputs from the data layer:

```python
from schema.io import load_cards
from schema import Flag

cards = load_cards()  # the 4 ground-truth cards
days = [d for c in cards for d in c.cost_code_days()]  # unit_rate etc.
entries = [e for c in cards for e in c.entries()]  # one row per cell
```

`score()` should return `list[Flag]` with `layer="L2"`, `status="insufficient_data"`
when history is below `n_min`, and the statistics it used in `evidence`.
Note: `CostCodeDay.crew_man_hours` counts ST + OT + DT.
