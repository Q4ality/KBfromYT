import json
from pathlib import Path

from scripts.validate_playlist import run


def test_live_runner_records_failure_and_resumes(tmp_path, video, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "test",
                "title": "Test playlist",
                "entries": [
                    {"id": video.video_id, "title": video.title},
                    {"id": "UNAVAILABLE", "title": "Unavailable item"},
                    None,
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fetch(vid, languages):
        calls.append(vid)
        if vid == "UNAVAILABLE":
            raise RuntimeError("captions unavailable")
        return video

    monkeypatch.setattr("scripts.validate_playlist.fetch_video", fetch)
    database, report = tmp_path / "live.sqlite3", tmp_path / "report.json"
    result = run(manifest, database, report, ["ru", "en"])
    assert result["expected_entries"] == 3
    assert result["summary"]["imported_or_unchanged"] == 1
    assert result["summary"]["failed"] == 2
    assert result["summary"]["idempotent_reimports"]
    assert "captions unavailable" in json.loads(report.read_text())["results"][1]["error"]
    calls.clear()
    resumed = run(manifest, database, report, ["ru", "en"])
    assert calls == ["UNAVAILABLE"]
    assert resumed["results"][0]["status"] == "unchanged"


def test_live_runner_rejects_empty_manifest(tmp_path):
    import pytest

    manifest = tmp_path / "empty.json"
    manifest.write_text('{"entries": []}')
    with pytest.raises(ValueError, match="no entries"):
        run(manifest, tmp_path / "db.sqlite3", Path(tmp_path / "report.json"), ["ru"])
