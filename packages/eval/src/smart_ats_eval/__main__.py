"""Print the Experiment 1 comparison table: python -m smart_ats_eval DATASET [--split] [--runs]."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from smart_ats_eval import dataset, harness
from smart_ats_eval.baseline import Bm25Baseline
from smart_ats_eval.scoring_v0 import ScoringV0
from smart_ats_scoring.llm import has_llm_key, llm_from_env, llm_provider
from smart_ats_scoring.pricing import price


def configs() -> list[harness.Config]:
    """Every Config compared on each run. A new one only needs adding here."""
    found: list[harness.Config] = [Bm25Baseline()]
    if has_llm_key():
        model = os.environ["LLM_REASONING_MODEL"]
        extraction_model = os.environ["LLM_EXTRACTION_MODEL"]
        for name in (model, extraction_model):
            if price(name) is None:  # before any call, so no spend goes unpriced
                sys.exit(f"No price for model {name} in smart_ats_scoring.pricing.PRICES.")
        extraction = llm_from_env(extraction_model)
        found.append(ScoringV0(extraction, llm_from_env(model), model))
    else:
        print("Scoring v0 skipped: it needs the API key of LLM_PROVIDER.", file=sys.stderr)
    return found


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
    data = dataset.load(args.dataset)
    # Gemini's free tier trains on prompts (FR-C1.5): refuse before any call, key or not.
    if llm_provider() == "gemini" and any(
        cv.source != "synthetic" for job in data.jobs for cv in job.cvs
    ):
        sys.exit("LLM_PROVIDER=gemini takes synthetic CVs only; this dataset has real ones.")
    print(harness.compare(data, configs(), args.split, args.runs))


if __name__ == "__main__":
    main()
