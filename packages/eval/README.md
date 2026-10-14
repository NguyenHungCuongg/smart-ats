# smart-ats-eval

Offline harness for Experiment 1 (scoring quality) in [the experiment plan](../../docs/EVAL/experiment_plan.md) §2–§4. It runs every registered scoring Config over one split of a versioned dataset and prints one comparison table. It needs no API, database or UI.

```sh
uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json            # dev split, 1 run
uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json --split test --runs 2
uv run pytest packages/eval
```

The table always has the Baseline row. The Scoring v0 row (the core of `packages/scoring`: Must-have Coverage, anchored rubric, grounding) calls the OpenAI API, so it runs only with `OPENAI_API_KEY`, `LLM_EXTRACTION_MODEL` and `LLM_REASONING_MODEL` set, for example `uv run --env-file .env python -m smart_ats_eval ...`; without a key it is skipped with a note on stderr. Each JD and CV Document is parsed once per invocation, so `--runs` repeats only the scoring. It reports no cost yet.

The default split is `dev`. Use `test` only for the frozen run the plan describes. Stability needs `--runs 2` or more; the plan (§4) sets the run count for the report.

## Datasets

`datasets/scratch-v1.json` is placeholder data: 2 Jobs × 6 fictional CV Documents, labelled by the team. It contains no real personal data and has `"for_report": false`, so the table carries a `NOT FOR REPORT` line. Each Job includes a keyword-stuffed CV and a CV that has the right skills in different words, which a lexical Baseline should misrank.

The real dataset (Data 04) uses the same format. Add it as a new file and change no code.

### Versioning

A file is named `<name>-v<version>.json`, and that name and version also go inside the file. Once a version has been run for the report, never edit it. Any change goes into a new version.

### Format

```json
{
  "name": "scratch",
  "version": 1,
  "for_report": false,
  "note": "free text: provenance, caveats",
  "raters": ["r1", "r2"],
  "jobs": [
    {
      "id": "backend-junior",
      "split": "dev",
      "title": "Backend Developer (Junior)",
      "jd_text": "JD Document text",
      "cvs": [
        {
          "id": "be-01",
          "source": "synthetic",
          "text": "CV Document text",
          "labels": { "r1": 5, "r2": 4 }
        }
      ],
      "top5": { "r1": ["be-01", "..."], "r2": ["be-01", "..."] }
    }
  ]
}
```

| Field          | Rule                                                                                         |
| -------------- | -------------------------------------------------------------------------------------------- |
| `for_report`   | `true` only for a dataset that may be cited in the report                                    |
| `raters`       | Exactly two distinct ids, both used in every `labels` and `top5`                             |
| `jobs[].split` | `dev` or `test`. The split is per Job, so the raters' Top 5 for a Job stays within one split |
| `cvs[].source` | `real` (consented and anonymised before it enters the repo) or `synthetic`                   |
| `cvs[].labels` | The 1–5 label each rater gives the (Job, CV Document) pair, as an integer                    |
| `top5`         | Each rater's own ordered Top 5: five distinct CV ids of this Job, best first                 |
| `cvs[].id`     | Unique within its Job                                                                        |

The loader rejects a file that breaks any of these rules.

## Metrics

Each metric is computed per run and per Job, then averaged.

| Column       | Definition                                                                                                                                      |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Spearman rho | Between the Config's Total and the HR score (the mean of the two labels), with ties ranked by their average. `nan` when either side is constant |
| NDCG@5       | Against each rater's Top 5, then averaged over raters. Relevance is 5 for the rater's first pick down to 1 for the fifth, and 0 outside it      |
| P@5          | Share of the Config's first five that are in the rater's Top 5, averaged over raters                                                            |
| Grounding    | Share of Evidence quotes found verbatim in the CV Document or JD Document, treating any run of whitespace as one space                          |
| Stability    | Sample standard deviation of each Application's Total across runs, averaged over Applications                                                   |
| Cost/App     | Mean `cost_usd` per Application, over the Scores that report one                                                                                |

The header also shows the weighted Cohen's Kappa (quadratic) between the two raters over the split, and the split's real/synthetic count. A Config's ranking orders CV Documents by Total and breaks ties by a hash of the id, so ids that follow quality give no advantage. Targets are in the plan, not here.

## Adding a Config

Implement `harness.Config` and add an instance in `configs()` in `src/smart_ats_eval/__main__.py`. `score(job)` returns exactly one `harness.ScoreResult` per CV Document, carrying `total`, any `evidence` quotes and `cost_usd` when it is known. Set `model`, `prompt_version` and `rubric_version` so the table records them. Neither the metrics nor the table need changes. `baseline.py` (Okapi BM25 of the JD against the Job's CVs) is the smallest example.
