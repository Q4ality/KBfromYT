# Local RAG chat — versions 0.2–0.4

Status: implemented and tested against the live playlist and standard OpenAI.
Requested 2026-10-24. Human benchmark relevance/entailment review remains pending.
Setup: [CHAT.md](CHAT.md).
Implementation plan: [07-rag-chat.md](../plans/07-rag-chat.md).

## User experience

Open a local browser page, type a question, and receive an answer grounded in the
indexed YouTube transcripts. Start with the existing 20-video Russian playlist.
Answer in the question's language. Provide a message list, multiline composer,
Send button, loading indicator, New chat button and expandable source cards.
Each cited claim links to a numbered source card containing video title, original
transcript excerpt, start/end time and a timestamped YouTube link. Display the
auto-caption origin as source metadata. Source cards are attached to claims,
not merely an unrelated bibliography below the answer.

The application is a local, single-user service on `127.0.0.1`, with independent
browser sessions. No public hosting, authentication system or frontend build
pipeline is needed for this milestone. The browser must never receive API keys.

## Conversation memory

Interpret “three last messages from user/solution” as the **last three complete
user/assistant exchanges**: up to six historical messages, plus the new question.
Make the exchange count configurable, default three. Retain these pairs in server
memory per session, restoring them from saved history when needed. Failed/cancelled requests
do not create completed pairs. Completed no-support responses do count as pairs.
The page can show its whole current conversation while the model sees only the
rolling memory window. Older messages remain visible but are excluded from the
next request. Saved conversations survive reload/restart; cross-device history is out of scope.

Version 0.3 saves conversation transcripts locally and reopens them from Saved chats.
Transient memory expires, but
only the last three accepted pairs are restored for model input. New chat preserves
earlier saved conversations. See [CHAT.md](CHAT.md) for storage and browser scope.

History resolves references such as “what did he say next?”; it is not source
evidence. Factual answers must retrieve current source passages again. Never turn
an earlier model answer into a citation. No persistent summaries or hosted
conversation chain may silently retain older turns beyond this window.

## Provider and retrieval

Use the user's configured OpenAI endpoint with server-side credentials. The
default generation/planning model: `gpt-6-luna`, reasoning `low`, configurable.
Use Responses API, function tools and structured final output. Account/model
availability was verified on standard OpenAI; custom endpoint compatibility requires testing;
a Codex model listing does not establish API access for this application.

Embeddings and retrieval remain local: use the existing multilingual MiniLM model,
SQLite and Qdrant index. Only the selected transcript excerpts, bounded recent
conversation, current question and tool metadata are sent to the configured
endpoint. A custom endpoint may have its own retention behavior; `store=False`
must not be described as a general no-retention guarantee.

The agent can call read-only transcript search, broad overview search and bounded
context expansion. It cannot browse the web, run shell commands, ingest videos or
change data. Mandatory fresh retrieval precedes each factual answer; allow one
query refinement if needed. The server, rather than the model, enforces limits.

## Answer and citation states

| State | Required behavior |
| --- | --- |
| `grounded` | Render only source-supported claims, with valid claim-level citations. |
| `partial` | Show **“Only part of this question is supported by the indexed videos.”** Answer supported parts and list unanswered parts. |
| `no_support` | Show **“The retrieved passages did not provide sufficient supporting citations. I cannot give a source-grounded answer from these results. Relevant evidence may exist elsewhere in the library.”** Do not invent an answer from model memory. |
| `verification_failed` | Show **“The answer could not be verified against the retrieved sources.”** Suppress the draft factual answer. |
| `error` | Describe an API, index or retrieval failure; do not claim the knowledge base contains no evidence. |

For Russian no-support answers the fixed wording is:
**«В найденных фрагментах недостаточно подтверждающих цитат для ответа. Это не означает, что нужных сведений нет в других частях библиотеки.»**
The server sets the status and notice after validation; the model cannot remove
them. The notice appears prominently in the answer bubble and remains present
when an answer is copied. A color alone or a warning hidden in source details is
insufficient. Partial answers must not contain unsupported factual claims.

A retrieved passage or a valid citation ID alone does not prove support. Validate
IDs, original excerpts, source bounds and current retrieval provenance in code;
assess claim/passage entailment separately. Human evaluation remains necessary.

Version 0.4 reports actual retrieved-passage/video coverage with expandable search
traces. Broad questions may summarize the authors' supported, attributed positions
without demanding an independent verdict about the underlying event. Topic/overview
metadata stays separate from original passages used for claim citations.

## Completion criteria

The local UI answers a real playlist question with working timestamp citations,
resolves a follow-up using bounded memory, excludes the fourth-oldest exchange,
and visibly abstains on a question without support. Test partial support, model
hallucinated IDs, irrelevant retrieval, endpoint failures, session isolation and
agent loop exhaustion. Existing CLI ingestion/search remains usable. Detailed
phase gates and verification commands are in the implementation plan.

## Verified OpenAI documentation

Sources checked 2026-10-24; these document API capabilities, not this user's access.

- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
