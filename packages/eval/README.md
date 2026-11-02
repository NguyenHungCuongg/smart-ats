# smart-ats-eval

Offline harness for Experiment 1 (scoring quality) in [the experiment plan](../../docs/EVAL/experiment_plan.md) §2–§4. It runs every registered scoring Config over one split of a versioned dataset and prints one comparison table. It needs no API, database or UI.

```sh
uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json            # dev split, 1 run
uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json --split test --runs 2
uv run pytest packages/eval
```

The table has one row per Config of the plan's ablation (§4), in this order:

| Config        | Scores with                                                                                                                                                                                                                          | Measures                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------- |
| Baseline      | Okapi BM25 of the JD Document against each CV Document (`baseline.py`)                                                                                                                                                               | A keyword filter                       |
| Config A      | The cosine of the JD Document's and the CV Document's embeddings (`EMBEDDING_MODEL`), x 100 (`config_a.py`)                                                                                                                          | A ranker by meaning with no LLM        |
| Config B      | `LLM_REASONING_MODEL` scoring 0-100 freely, at temperature 0, on Config D's input: the criteria and the Blind Profile in the untrusted block. Its own prompt (`config_b.py`, `b-v1`); no rubric and no Evidence, so Grounding is `-` | What the anchored rubric adds          |
| Config C      | Scoring v1 with Must-have Coverage off: Technical Fit is the rubric alone, the prompt has no Coverage and nothing is embedded; the Experience timeline stays                                                                         | What the deterministic part adds       |
| Config D      | Scoring v1, the code the product scores with (`packages/scoring`: Must-have Coverage with semantic matching, Experience timeline, anchored rubric, grounding)                                                                        | The product                            |
| Config D-luna | Config D with `LLM_EXTRACTION_MODEL` scoring too; the embedding model stays                                                                                                                                                          | The trade-off between cost and quality |

Configs A-D call the provider's API, so they run only with the API key of `LLM_PROVIDER` and with `LLM_EXTRACTION_MODEL`, `LLM_REASONING_MODEL` and `EMBEDDING_MODEL` set, for example `uv run --env-file .env python -m smart_ats_eval ...`; without a key only the Baseline runs, with a note on stderr. Each JD and CV Document is parsed once per invocation, by `LLM_EXTRACTION_MODEL`, and Configs B-D all score that parse, so `--runs` repeats only the scoring. Every model must have a price in `smart_ats_scoring.pricing.PRICES`, and the embedding model a similarity threshold in `smart_ats_scoring.embedding.THRESHOLDS`, or the run stops before any call. The Scoring v0 row it replaces is reproduced by checking out the tag `scoring-v0`. Each run that calls the provider is recorded in [the experiment log](../../docs/EVAL/experiment_log.md).

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
  "as_of": "2026-10-13",
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

| Field                     | Rule                                                                                                                                                                                            |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `for_report`              | `true` only for a dataset that may be cited in the report                                                                                                                                       |
| `as_of`                   | The day the CVs were collected, as `YYYY-MM-DD`. Required: an open end in a work history ("nay", "present") runs to it, so the table gives the same numbers whatever day it is run              |
| `raters`                  | Exactly two distinct ids, both used in every `labels` and `top5`                                                                                                                                |
| `jobs[].split`            | `dev` or `test`. The split is per Job, so the raters' Top 5 for a Job stays within one split                                                                                                    |
| `cvs[].source`            | `real` (consented and anonymised before it enters the repo) or `synthetic`                                                                                                                      |
| `cvs[].free_tier_consent` | Optional, `false` by default. `true` only when a `real` CV's owner agreed in writing to be sent to a free tier that trains on prompts (Gemini, FR-C1.5); the agreement is kept outside the repo |
| `cvs[].labels`            | The 1–5 label each rater gives the (Job, CV Document) pair, as an integer                                                                                                                       |
| `top5`                    | Each rater's own ordered Top 5: five distinct CV ids of this Job, best first                                                                                                                    |
| `cvs[].id`                | Unique within its Job                                                                                                                                                                           |

The loader rejects a file that breaks any of these rules.

## Metrics

Each metric is computed per run and per Job, then averaged.

| Column       | Definition                                                                                                                                                                                                                                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Spearman rho | Between the Config's Total and the HR score (the mean of the two labels), with ties ranked by their average. A Job whose Totals or HR scores are all equal has no rho and is left out of the mean; `-` when no Job has one                                                                                                                  |
| Rho excluded | How many (run, Job) pairs were left out of Spearman rho for that reason                                                                                                                                                                                                                                                                     |
| NDCG@5       | Against each rater's Top 5, then averaged over raters. Relevance is 5 for the rater's first pick down to 1 for the fifth, and 0 outside it                                                                                                                                                                                                  |
| P@5          | Share of the Config's first five that are in the rater's Top 5, averaged over raters                                                                                                                                                                                                                                                        |
| Grounding    | Share of Evidence quotes the Config made that pass the grounding rule of `smart_ats_scoring.scoring` (`is_grounded`), the rule the product applies: found as whole words in the CV Document (a Gap may also use the JD Document), ignoring case, diacritics, punctuation and spacing; empty, stopword-only and too short quotes never count |
| Stability    | Sample standard deviation of each Application's Total across runs, averaged over Applications                                                                                                                                                                                                                                               |
| Cost/App     | Mean `cost_usd` per Application, over the Scores that report one. Configs B-D count the Application's CV parse, its share of the JD parse, its scoring and, when made, its embedding call; Config A its share of the Job's one embedding call. All are priced from `smart_ats_scoring.pricing.PRICES`                                       |

With `LLM_PROVIDER=gemini` (free testing, `.env.example`) the run exits if any CV Document is `real` without `free_tier_consent`: Gemini's free tier trains on prompts. A 429 from Gemini is retried for about a minute, which rides out its per-minute limit but not a spent daily one.

The header also shows the weighted Cohen's Kappa (quadratic) between the two raters over the split, and the split's real/synthetic count. A Config's ranking orders CV Documents by Total and breaks ties by a hash of the id, so ids that follow quality give no advantage. Targets are in the plan, not here.

## Adding a Config

Implement `harness.Config` and add an instance in `configs()` in `src/smart_ats_eval/__main__.py`. `score(job)` returns exactly one `harness.ScoreResult` per CV Document, carrying `total`, a `grounded` flag per Evidence quote (from the rule of `smart_ats_scoring.scoring`, as `ConfigD` takes them from its result; never a second rule) and `cost_usd` when it is known. Set `model`, `prompt_version` and `rubric_version` so the table records them. A Config that reads the parsed criteria and profile takes the shared `config_d.Parser`, so it scores the same parse as the others and the run parses each document once. Neither the metrics nor the table need changes. `baseline.py` (Okapi BM25 of the JD against the Job's CVs) is the smallest example.
