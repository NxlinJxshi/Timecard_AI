# agent/ — L3 LangGraph agent + serving (Kylan)

Graph nodes import their contracts from the data layer:

```python
from schema import Timecard, Flag  # graph state: card, flags, report
from rules import run_rules  # "rules" node: run_rules(card, week_cards=...)
```

Constrained decoding: JSON Schemas for `Timecard` (VLM parser) and `Flag`
(LLM structured output) live in `schema/json/`; regenerate with `python -m schema`.
