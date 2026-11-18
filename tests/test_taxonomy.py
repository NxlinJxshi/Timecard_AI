import re

import pytest

from rules import ANOMALY_CLASS
from schema import Direction
from stats.taxonomy import BY_KEY, TAXONOMY, Layer, classes, get_class, l2_class


def test_keys_unique_and_snake_case():
    keys = [c.key for c in TAXONOMY]
    assert len(keys) == len(set(keys))
    for k in keys:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", k), k


def test_every_rule_class_is_in_taxonomy_with_matching_detector():
    # Max's rules tag flags with these keys; the taxonomy must contain each one.
    for rule_id, key in ANOMALY_CLASS.items():
        c = get_class(key)
        assert c.layer is Layer.L1
        assert c.detector == rule_id


def test_l2_classes_are_one_tailed():
    for c in classes(Layer.L2):
        assert c.direction in (Direction.OVER, Direction.UNDER), c.key
        assert c.detector.startswith("L2.")


def test_l2_class_lookup_by_tail():
    assert l2_class("L2.unit_rate", Direction.OVER) == "unit_rate_high"
    assert l2_class("L2.unit_rate", Direction.UNDER) == "unit_rate_low"
    with pytest.raises(KeyError):
        l2_class("L2.ot_share", Direction.UNDER)  # low OT share is not flagged


def test_one_detector_tail_per_class():
    seen = {(c.detector, c.direction) for c in classes(Layer.L2)}
    assert len(seen) == len(classes(Layer.L2))


def test_unknown_key_lists_valid_keys():
    with pytest.raises(KeyError, match="valid"):
        get_class("not_a_class")
    assert len(BY_KEY) == len(TAXONOMY)
