"""Versioned eval dataset: Jobs, CV Documents, two raters' labels and Top 5. Format in README.md."""

import json
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

SPLITS = ("dev", "test")
SOURCES = ("real", "synthetic")


@dataclass(frozen=True)
class CvDocument:
    id: str
    source: str
    text: str
    labels: dict[str, int]
    free_tier_consent: bool = False
    """A real CV's owner agreed in writing to a free tier that trains on prompts (FR-C1.5)."""

    @property
    def hr_score(self) -> float:
        """Ground truth: the mean of the raters' 1-5 labels."""
        return statistics.fmean(self.labels.values())


@dataclass(frozen=True)
class Job:
    id: str
    split: str
    title: str
    jd_text: str
    cvs: tuple[CvDocument, ...]
    top5: dict[str, tuple[str, ...]]
    as_of: date
    """The dataset's: the day its CVs were collected."""


@dataclass(frozen=True)
class Dataset:
    name: str
    version: int
    for_report: bool
    raters: tuple[str, ...]
    jobs: tuple[Job, ...]


def load(path: Path) -> Dataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raters = tuple(raw["raters"])
    _check(len(set(raters)) == 2 == len(raters), "need exactly two distinct raters")
    _check(type(raw["for_report"]) is bool, "for_report must be true or false")
    try:
        as_of = date.fromisoformat(raw["as_of"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("as_of must be the day the CVs were collected, as YYYY-MM-DD") from None
    jobs = tuple(_job(job, raters, as_of) for job in raw["jobs"])
    _check(len({job.id for job in jobs}) == len(jobs), "duplicate Job id")
    return Dataset(raw["name"], raw["version"], raw["for_report"], raters, jobs)


def _job(raw: dict[str, Any], raters: tuple[str, ...], as_of: date) -> Job:
    where = f"Job {raw['id']}"
    _check(raw["split"] in SPLITS, f"{where}: split must be one of {SPLITS}")
    cvs = tuple(
        CvDocument(
            c["id"], c["source"], c["text"], dict(c["labels"]), c.get("free_tier_consent", False)
        )
        for c in raw["cvs"]
    )
    ids = {cv.id for cv in cvs}
    _check(len(ids) == len(cvs), f"{where}: duplicate CV id")
    for cv in cvs:
        _check(cv.source in SOURCES, f"{where}, CV {cv.id}: source must be one of {SOURCES}")
        _check(
            type(cv.free_tier_consent) is bool,
            f"{where}, CV {cv.id}: free_tier_consent must be true or false",
        )
        _check(set(cv.labels) == set(raters), f"{where}, CV {cv.id}: needs one label per rater")
        _check(
            all(type(label) is int and 1 <= label <= 5 for label in cv.labels.values()),
            f"{where}, CV {cv.id}: labels must be integers 1-5",
        )
    top5 = {rater: tuple(raw["top5"][rater]) for rater in raters}
    for rater, top in top5.items():
        _check(
            len(set(top)) == len(top) == 5 and set(top) <= ids,
            f"{where}: {rater}'s top5 must name 5 distinct CVs of this Job",
        )
    return Job(raw["id"], raw["split"], raw["title"], raw["jd_text"], cvs, top5, as_of)


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)
