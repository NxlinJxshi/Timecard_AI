"""Export JSON Schemas: ``python -m schema [--check]``.

Writes ``schema/json/*.schema.json`` -- the files Kylan's constrained decoding
(VLM parser, LLM structured output) consumes. ``--check`` fails if they are stale,
which CI runs so the exported contract never drifts from the Pydantic models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from schema.schema import CostCodeDay, Entry, Flag, Timecard

OUT = Path(__file__).resolve().parent / "json"
MODELS = {"timecard": Timecard, "flag": Flag, "entry": Entry, "cost_code_day": CostCodeDay}


def render() -> dict[str, str]:
    return {
        f"{name}.schema.json": json.dumps(model.model_json_schema(), indent=2) + "\n"
        for name, model in MODELS.items()
    }


def main(argv: list[str]) -> int:
    files = render()
    if "--check" in argv:
        stale = [
            n for n, txt in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != txt
        ]
        if stale:
            print("stale JSON schemas, run `python -m schema`:", ", ".join(stale))
            return 1
        print("JSON schemas up to date")
        return 0
    OUT.mkdir(exist_ok=True)
    for name, txt in files.items():
        (OUT / name).write_text(txt)
        print("wrote", OUT / name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
