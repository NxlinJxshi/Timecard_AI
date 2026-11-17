"""Load cards from JSON. A card that fails validation becomes an L0 parse-error
flag rather than being dropped (see :func:`load_card_or_flag`)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from schema.schema import Direction, EntityRef, Flag, FlagStatus, Severity, Timecard

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cards"


def load_card(path: str | Path) -> Timecard:
    return Timecard.model_validate_json(Path(path).read_text())


def load_cards(paths: Iterable[str | Path] | None = None) -> list[Timecard]:
    """Load the given card files, or every fixture card when ``paths`` is None."""
    if paths is None:
        paths = sorted(FIXTURE_DIR.glob("*.json"))
    return [load_card(p) for p in paths]


def load_card_or_flag(path: str | Path) -> Timecard | Flag:
    path = Path(path)
    try:
        return load_card(path)
    except (ValidationError, json.JSONDecodeError) as exc:
        n = exc.error_count() if isinstance(exc, ValidationError) else 1
        first = str(exc).splitlines()[0:3]
        return Flag(
            rule_id="L0.parse",
            layer="L0",
            status=FlagStatus.PARSE_ERROR,
            field="card",
            entity=EntityRef(card_id=path.stem),
            severity=Severity.HIGH,
            confidence=1.0,
            direction=Direction.NONE,
            rationale=f"Card {path.name} failed schema validation ({n} error(s)): "
            + " | ".join(first),
            evidence={"source": str(path), "errors": n},
        )
