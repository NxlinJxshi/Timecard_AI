"""CLI: ``python -m rules [card.json ...] [--json]``.

With no paths, runs every fixture card. Cards sharing a ``week_key`` are passed to
each other as R4 week context. Exit code 1 if any flag fires (handy in CI).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from rules.rules import run_rules
from schema.io import load_cards


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rules")
    ap.add_argument("paths", nargs="*", help="card JSON files (default: all fixtures)")
    ap.add_argument("--json", action="store_true", help="emit flags as JSON lines")
    args = ap.parse_args(argv)

    cards = load_cards(args.paths or None)
    by_week = defaultdict(list)
    for c in cards:
        by_week[c.week_key].append(c)

    total = 0
    for card in cards:
        context = by_week[card.week_key] if card.week_key else []
        flags = run_rules(card, week_cards=context)
        total += len(flags)
        if args.json:
            for f in flags:
                print(f.model_dump_json())
            continue
        print(f"{card.card_id}: {len(flags)} flag(s)")
        for f in flags:
            print(f"  [{f.rule_id} {f.severity.value} {f.status.value}] {f.rationale}")
    if not args.json:
        print(f"\n{len(cards)} card(s), {total} flag(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
