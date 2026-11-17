"""Infer a coarse equipment category from the make/model text on the card.

This is a *derived* field, kept out of the ground-truth fixtures on purpose: the
card only shows strings like "BOBCAT S510, S...". R6 (equipment over-log, Week 2)
sets its threshold per category, so the mapping lives here where it can be
reviewed and extended. Unknown text maps to ``"unknown"``, never a guess.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bSKYTRAK\b|\bTELEHANDLER\b", "telehandler"),
    (r"\bJLG\b.*\bBOOM\b|\bBOOM\b", "boom_lift"),
    (r"\bBOBCAT\b|\bSKID\s*STEER\b", "skid_steer"),
    (r"\bF[- ]?(150|250|350)\b|\bCOLORA", "pickup_truck"),
    (r"\bF[- ]?(450|550|600|650|750)\b", "medium_duty_truck"),
)


def infer_equipment_category(name: str) -> str:
    text = name.upper()
    for pattern, category in _PATTERNS:
        if re.search(pattern, text):
            return category
    return "unknown"
