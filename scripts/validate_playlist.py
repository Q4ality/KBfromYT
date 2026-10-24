"""Resume a live caption import from a saved yt-dlp playlist manifest.

Run with the project virtual environment. Reports and source data stay local.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from kbfromyt.ingest import fetch_video
from kbfromyt.store import Store


def run(manifest: Path, database: Path, report: Path, languages: list[str]) -> dict:
    playlist = json.loads(manifest.read_text(encoding="utf-8-sig"))
    entries = playlist.get("entries") or []
    if not entries:
        raise ValueError("playlist manifest contains no entries")
    result = {
        "playlist_id": playlist.get("id"),
        "playlist_title": playlist.get("title"),
        "channel": playlist.get("channel"),
        "started_at": datetime.now(UTC).isoformat(),
        "languages": languages,
        "expected_entries": len(entries),
        "database": str(database),
        "results": [],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    with Store(database) as store:
        existing = {p.video.video_id: p for p in store.videos()}
        for position, entry in enumerate(entries, 1):
            vid = (entry or {}).get("id")
            row = {"position": position, "video_id": vid, "title": (entry or {}).get("title")}
            print(f"[{position}/{len(entries)}] {vid}: {row['title']}", flush=True)
            try:
                if not vid:
                    raise ValueError("unavailable playlist entry has no video ID")
                previous = existing.get(vid)
                video = previous.video if previous else fetch_video(vid, languages)
                changed = store.import_video(video)
                row.update(
                    {
                        "status": "imported" if changed else "unchanged",
                        "source": video.transcript_source,
                        "language": video.language,
                        "segments": len(video.segments),
                        "duration": video.duration,
                    }
                )
            except Exception as exc:
                row.update({"status": "failed", "error": str(exc)})
            result["results"].append(row)
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {row['status']}: {row.get('error', row.get('language'))}", flush=True)
        processed = store.videos()
        result["summary"] = {
            "imported_or_unchanged": sum(r["status"] != "failed" for r in result["results"]),
            "failed": sum(r["status"] == "failed" for r in result["results"]),
            "stored_videos": len(processed),
            "chapters": sum(len(p.chapters) for p in processed),
            "chunks": sum(len(p.chunks) for p in processed),
            "segments": sum(len(p.segments) for p in processed),
            "duration_hours": sum(p.video.duration for p in processed) / 3600,
            "idempotent_reimports": all(not store.import_video(p.video) for p in processed),
        }
    result["completed_at"] = datetime.now(UTC).isoformat()
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/live/playlist.json"))
    parser.add_argument("--db", type=Path, default=Path("data/live/kb.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("data/live/ingestion-report.json"))
    parser.add_argument("--languages", nargs="+", default=["ru", "en"])
    args = parser.parse_args()
    outcome = run(args.manifest, args.db, args.report, args.languages)
    raise SystemExit(int(outcome["summary"]["failed"] > 0))
