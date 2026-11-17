# eval/ — evaluation datasets and harness (Kylan, with Max's seeder)

Not a Python package (name would shadow the `eval` builtin on import).

- Parsing ground truth: `fixtures/cards/*.json` (eval #1, cell-level F1)
- Seeded anomaly sets: produced by `seed.py` (Week 2) per taxonomy class
- LangSmith dataset exports go here.
