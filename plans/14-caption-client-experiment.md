# One-video caption client experiment

Requested 2026-10-25 after the SDK caption endpoint returned HTTP 429.
Status: experiment complete; subtitle acquisition remains externally blocked.

## Scope

- [x] Configure a supported JavaScript runtime and the companion version required
  by the installed yt-dlp; test only `tmwZmypDZX8`, one Russian caption track.
- [x] If the supported HTTP client is missing, install it and make one comparison.
- [x] Compare YouTube's own transcript UI in an anonymous in-app browser session.
- [x] Preserve the existing library; no full-playlist retries, media downloads,
  account cookies, proxy changes, OpenAI calls or index maintenance.
- [x] Save sanitized evidence and verify package consistency/offline regressions.

## Runtime and reproduction

Installed in the local `.venv-live` for this experiment:

- Existing `yt-dlp==2026.10.21` and Node `v24.22.1`.
- Added `yt-dlp-ejs==0.8.0` (exact requirement declared by installed yt-dlp).
- Added the documented `yt-dlp[curl-cffi]==2026.10.21` optional dependency:
  `curl-cffi==0.16.3`, `cffi==2.1.1`, `pycparser==3.12`.

Node was explicitly enabled with `js_runtimes={"node": {"path": ...}}`.
EJS used the installed Python package, with no remote component downloads.
The probe enabled only `ru-orig` JSON3 subtitles with `skip_download=True`,
`noplaylist=True`, socket timeout 15 seconds and zero automatic retries.
No Proof-of-Origin provider was installed or tested. A missing token has not
been established as the cause of this 429.

These are experimental local dependencies, not a new application caption backend.
The production importer remains unchanged. Normal bootstrap requirements were
not expanded because the experiment did not restore caption access.

## Results

1. Node/EJS: player JavaScript challenge solved successfully; the caption request
   still returned HTTP 429 with an HTML error mentioning "automated queries".
   yt-dlp warned that HTTP impersonation support was unavailable.
2. Node/EJS plus curl-cffi: challenge solved, curl_cffi handler available and
   subtitle impersonation requested. The same endpoint returned the same 429.
   The missing-impersonation warning disappeared; caption acquisition still failed.
3. Anonymous in-app browser: the video page loaded and its description offered
   Show transcript. Opening that panel left it on loading; the browser's transcript
   export reported no available transcript. This does not establish the result in
   the user's separate Chrome/Edge profile or on another connection.

Evidence is ignored under `data/live/ytdlp-caption-probe-7888d5ec/diagnosis.json`,
`data/live/ytdlp-caption-probe-089c5432/diagnosis.json`,
`data/live/youtube-browser-caption-probe.jpg` and
`data/environments/.venv-live/caption-probe-runtime.json`.
Signed URLs, request cookies, IP addresses and API keys were omitted.

147 offline tests passed; pip check reported no broken requirements. The real
application reports ready=true, semantic enabled and the existing 20 videos.
No subtitle content was acquired or imported. The experiment identifies failures
in both tested downloader configurations, but cannot reveal YouTube's internal
blocking rule, duration, or prove that every request path or network will fail.

## Next discriminating check

Check Show transcript in the user's ordinary Chrome/Edge session. If it works,
investigate an explicit browser transcript import. If it also fails, compare a
single request after a quiet period or through another user-selected connection.
Subtitle-file import or local transcription of available audio remains a separate
fallback; account cookies and paid proxy services require a deliberate choice.

References: [EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS),
[HTTP client dependencies](https://github.com/yt-dlp/yt-dlp#impersonation),
[PO Token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).
