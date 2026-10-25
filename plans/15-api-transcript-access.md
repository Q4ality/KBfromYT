# API-only transcript access

Requested 2026-10-25: research documentation and obtain transcripts through APIs
instead of browser automation or manual copy/paste.

## Verified documentation

- Google `captions.list` returns track metadata, not transcript text, and requires
  OAuth. `captions.download` explicitly requires permission to edit the video.
  A viewer's API key alone cannot download this third-party channel's captions.
- The unofficial YouTube.js client documents `VideoInfo.getTranscript()`. Its
  implementation requests the transcript continuation advertised in engagement
  panels, using the client's generated/retrieved InnerTube session context.
- Supadata documents `GET https://api.supadata.ai/v1/transcript`, authenticated by
  an `x-api-key` header. `text=false` returns text, offset and duration; timing is
  in milliseconds. `mode=native` limits acquisition to existing transcripts and
  disables its automatic AI-transcription fallback. `lang=ru` requests Russian,
  but the actual returned language must still be validated.
- At review time its public pricing page offers 100 free monthly credits without
  a credit card; an existing transcript costs one credit. These are provider
  claims, not a guarantee that this particular video will succeed.

## Actual API-only test

- [x] Tested YouTube.js 18.3.0 in an isolated ignored folder with Node 24.22.1.
  Downloaded the official npm standalone bundle, verified its SHA-512 integrity,
  and executed the documented API calls through direct Node HTTP fetch. The
  bundle's filename does not mean a browser was used; no browser automation ran.
- [x] Session bootstrap `/sw.js_data`, `/youtubei/v1/config`, `/player` and `/next`
  each returned HTTP 200. `getTranscript()` reached `/youtubei/v1/get_transcript`
  and returned HTTP 400 `FAILED_PRECONDITION`, zero transcript segments.
- [x] No browser profile/account cookies, media downloads, paid services, OpenAI
  requests or application source/index mutations were used. The dependency was
  not added to application requirements.
- [x] Safe evidence: ignored `data/live/youtubejs-api-probe/diagnosis.json` and
  `package-origin.json`. API/session parameters and cookies are not logged.

## Next integration candidate

Use a managed transcript API as an explicit optional acquisition provider while
keeping processing, storage, embeddings and RAG unchanged. A Supadata trial should
request only this video with `lang=ru`, `text=false`, `mode=native`, validate all
timestamps and returned language, then save source segments before any import.
Support bounded async job polling if the API returns HTTP 202. Never silently
enable generation, translate captions, retry a charged request, or substitute a
generated summary for original transcript evidence.

- [ ] User supplies a provider API key in ignored root `.env` as
  `SUPADATA_API_KEY` (never in chat); no account was created or key assumed.
- [ ] Test one actual native Russian transcript response; success remains unverified.
- [ ] Only after that result, choose and implement the production provider adapter.

Sources:
- https://developers.google.com/youtube/data/reference/rest/v3/captions/list
- https://developers.google.com/youtube/data/reference/rest/v3/captions/download
- https://ytjs.dev/api/youtubei.js/namespaces/YT/classes/VideoInfo#gettranscript
- https://github.com/LuanRT/YouTube.js
- https://docs.supadata.ai/get-transcript
- https://supadata.ai/pricing
