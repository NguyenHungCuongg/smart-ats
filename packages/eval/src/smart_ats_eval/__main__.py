"""Print the Experiment 1 comparison table: python -m smart_ats_eval DATASET [--split] [--runs]."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from smart_ats_eval import dataset, harness
from smart_ats_eval.baseline import Bm25Baseline

# Every Config compared on each run. A new one (e.g. scoring v0) only needs adding here.
CONFIGS: list[harness.Config] = [Bm25Baseline()]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m smart_ats_eval")
    parser.add_argument("dataset", type=Path, help="dataset JSON file")
    parser.add_argument("--split", choices=dataset.SPLITS, default="dev")
    parser.add_argument(
        "--runs", type=int, default=1, help="runs per Config; stability needs 2 or more"
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    print(harness.compare(dataset.load(args.dataset), CONFIGS, args.split, args.runs))


if __name__ == "__main__":
    main()
