# Scoring combines deterministic coverage with an anchored LLM rubric

An Axis Score is not a free-form 0–100 number from the LLM, because free-form numbers drift between runs and cannot be defended. Must-have Coverage is computed deterministically: skills are normalized, then matched by exact or alias match and, failing that, by embedding similarity above a threshold. The LLM grades each axis on a 1–5 rubric with written anchors and must quote Evidence. The grade maps linearly to 0–100. Evidence that cannot be found in the source text is discarded, and the claim it supports is flagged.

## Consequences

- Every Score Result stores `model`, `prompt_version`, `rubric_version` and the weights snapshot of its Scoring Run, so any score can be reproduced or explained later.
- Calls run with `temperature=0` and a fixed seed where supported. Score stability (standard deviation across 5 repeats) is a reported metric, not an assumption.
