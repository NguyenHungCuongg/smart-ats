import json
from pathlib import Path
from typing import Any

import pytest

from smart_ats_eval import dataset


def valid_raw() -> dict[str, Any]:
    cvs = [
        {"id": f"cv{i}", "source": "synthetic", "text": f"CV {i}", "labels": {"r1": 3, "r2": 4}}
        for i in range(6)
    ]
    ids = [cv["id"] for cv in cvs]
    job = {
        "id": "job1",
        "split": "dev",
        "title": "Backend",
        "jd_text": "JD",
        "cvs": cvs,
        "top5": {"r1": ids[:5], "r2": ids[1:]},
    }
    return {"name": "t", "version": 1, "for_report": False, "raters": ["r1", "r2"], "jobs": [job]}


def write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_load_reads_labels_and_each_raters_top5(tmp_path: Path) -> None:
    loaded = dataset.load(write(tmp_path, valid_raw()))

    job = loaded.jobs[0]
    assert loaded.raters == ("r1", "r2")
    assert job.split == "dev"
    assert job.cvs[0].hr_score == 3.5
    assert job.top5["r2"] == ("cv1", "cv2", "cv3", "cv4", "cv5")


def test_load_rejects_a_label_outside_1_to_5(tmp_path: Path) -> None:
    raw = valid_raw()
    raw["jobs"][0]["cvs"][0]["labels"]["r1"] = 6

    with pytest.raises(ValueError, match="1-5"):
        dataset.load(write(tmp_path, raw))


def test_load_rejects_a_cv_missing_a_raters_label(tmp_path: Path) -> None:
    raw = valid_raw()
    del raw["jobs"][0]["cvs"][0]["labels"]["r2"]

    with pytest.raises(ValueError, match="one label per rater"):
        dataset.load(write(tmp_path, raw))


def test_load_rejects_a_top5_naming_a_cv_outside_the_job(tmp_path: Path) -> None:
    raw = valid_raw()
    raw["jobs"][0]["top5"]["r1"][0] = "cv-other-job"

    with pytest.raises(ValueError, match="top5"):
        dataset.load(write(tmp_path, raw))


def test_load_rejects_a_non_boolean_for_report(tmp_path: Path) -> None:
    raw = valid_raw()
    raw["for_report"] = "false"  # truthy: would silently drop the NOT FOR REPORT flag

    with pytest.raises(ValueError, match="for_report"):
        dataset.load(write(tmp_path, raw))


def test_load_rejects_an_unknown_split(tmp_path: Path) -> None:
    raw = valid_raw()
    raw["jobs"][0]["split"] = "train"

    with pytest.raises(ValueError, match="split"):
        dataset.load(write(tmp_path, raw))
