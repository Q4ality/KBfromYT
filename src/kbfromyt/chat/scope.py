from __future__ import annotations

from kbfromyt.chat.contracts import SourceScope


def resolve_scope(scope: SourceScope, known: set[str], playlists: list[dict]) -> list[str]:
    if scope.kind == "library":
        selected = sorted(known)
    elif scope.kind == "videos":
        selected = scope.video_ids
    else:
        playlist = next((p for p in playlists if p["id"] == scope.playlist_id), None)
        if playlist is None:
            raise ValueError("The selected playlist is unavailable. Choose another chat scope.")
        selected = playlist["video_ids"]
    if not selected or set(selected) - known:
        raise ValueError(
            "The selected sources are empty or unavailable. Choose another chat scope."
        )
    return sorted(set(selected))
