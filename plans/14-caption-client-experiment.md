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

The user subsequently confirmed that actual timestamped transcript lines are
visible via **В этом видео → Расшифровка видео**. Browser transcript availability
is therefore confirmed for their working session. The anonymous in-app browser
result must not be generalized to that session or interpreted as missing captions.

A direct repeat through the player's **В этом видео** button selected the correct
transcript tab, but the connected anonymous in-app session remained on loading.
Only the Codex in-app browser and MCP Apps are available in the tool inventory;
the user's working browser/session has not yet been identified or connected.
Screenshot: ignored `data/live/transcript-panel-direct-tab.jpg`.

One anonymous API experiment followed the `getTranscriptEndpoint` advertised in
the public page, using its fresh parameters and web client context. Watch-page
lookup succeeded (200); `/youtubei/v1/get_transcript` returned **400
FAILED_PRECONDITION**, "Precondition check failed." It returned zero segments.
This is distinct from the 429 at `/api/timedtext`; it does not establish which
session/attestation precondition failed. Safe report:
`data/live/transcript-panel-probe/diagnosis.json` (ignored).

Next: identify/access the session where the user sees timestamped lines and test
browser-assisted extraction there. Do not infer an IP ban, change networks, or
claim transcript absence from the anonymous session result. User-supplied subtitle
or transcript import remains an alternative. No user account cookies were exported
or used, and no new source was written to the library in this follow-up.

References: [EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS),
[HTTP client dependencies](https://github.com/yt-dlp/yt-dlp#impersonation),
[PO Token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).
