"use strict";
const $ = id => document.getElementById(id);
let busy = false;
let ready = false;
const labels = {grounded:"Cited answer",partial:"Partial source support",no_support:"No supporting citations",verification_failed:"Verification failed",error:"Request failed"};
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function scrollChat() { $("messages").scrollTop = $("messages").scrollHeight; }
function setBusy(value) {
  busy = value;
  $("send").disabled = value || !ready;
  $("reset").disabled = value;
  $("question").disabled = value;
  $("composer").setAttribute("aria-busy", String(value));
}
function bubble(who, text) {
  $("welcome")?.remove();
  const box = element("article", undefined, `message ${who}`);
  box.append(element("div", who === "user" ? "You" : "KBfromYT", "who"));
  const body = element("div", text, "body");
  box.append(body); $("messages").append(box); scrollChat();
  return body;
}
function timestamp(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2,"0")}`;
}
function answer(reply) {
  const body = bubble("assistant");
  if (reply.notice) body.append(element("div", reply.notice, `notice ${reply.status}`));
  const cards = new Map(reply.citations.map((c,i) => [c.id, {source:c, number:i+1}]));
  for (const claim of reply.claims) {
    const p = element("p", claim.text + " ", "claim");
    for (const id of claim.citations) {
      const card = cards.get(id); if (!card) continue;
      const link = element("a", String(card.number), "cite");
      link.href = `#source-${reply.reply_id}-${id}`;
      link.setAttribute("aria-label", `Source ${card.number}`);
      link.addEventListener("click", event => {
        event.preventDefault();
        const target = document.getElementById(`source-${reply.reply_id}-${id}`);
        target.open = true; target.scrollIntoView({block:"nearest",behavior:"smooth"});
      }); p.append(link);
    } body.append(p);
  }
  for (const part of reply.unanswered) body.append(element("p", `Unanswered / Не подтверждено: ${part}`, "unanswered"));
  for (const {source:c, number} of cards.values()) {
    const details = element("details", undefined, "source-card");
    details.id = `source-${reply.reply_id}-${c.id}`;
    details.append(element("summary", `${number}. ${c.video_title} · ${timestamp(c.start)}–${timestamp(c.end)}`));
    const content = element("div", undefined, "source-content");
    content.append(element("div", `${c.language.toUpperCase()} · ${c.transcript_source === "auto" ? "Auto-generated captions" : c.transcript_source + " captions"} · ${c.chapter_title}`, "source-meta"));
    for (const quote of c.supporting_quotes) content.append(element("blockquote", quote));
    const video = element("a", `Open video at ${timestamp(c.start)} ↗`);
    video.href = c.url; video.target = "_blank"; video.rel = "noopener noreferrer";
    content.append(video);
    const full = element("details"); full.append(element("summary", "Full source passage"),element("p",c.excerpt,"full-source"));
    content.append(full); details.append(content); body.append(details);
  }
  const footer = element("div", undefined, "reply-footer");
  const copy = element("button", "Copy answer", "copy"); copy.type = "button";
  const copied = [reply.notice,...reply.claims.map(c => c.text + " " + c.citations.map(id => `[${cards.get(id)?.number}]`).join(" ")),...reply.unanswered.map(p => `Unanswered: ${p}`),...reply.citations.map(c=>`[${cards.get(c.id)?.number}] ${c.video_title}: ${c.url}`)].filter(Boolean).join("\n\n");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(copied); copy.textContent = "Copied"; }
    catch { copy.textContent = "Select text to copy"; }
  });
  footer.append(copy,element("span",`${labels[reply.status]} · ${(reply.usage.latency_ms/1000).toFixed(1)}s · ${reply.usage.memory_turns} recent exchanges`));
  body.append(footer); scrollChat();
}
async function loadStatus() {
  try {
    const response = await fetch("/api/status"); if (!response.ok) throw new Error();
    const status = await response.json(); ready = status.ready;
    $("video-count").textContent = status.videos;
    $("model-name").textContent = status.model;
    $("memory-label").textContent = `Remembers the last ${status.memory_turns} exchanges`;
    $("readiness").textContent = status.message || `${status.videos} videos connected · Ready for questions`;
    $("readiness").classList.toggle("problem", !status.ready);
  } catch { ready = false; $("readiness").textContent = "Cannot connect to the local chat server."; $("readiness").classList.add("problem"); }
  setBusy(false);
}
$("composer").addEventListener("submit", async event => {
  event.preventDefault(); const message = $("question").value.trim();
  if (!message || busy || !ready) return;
  bubble("user", message); $("question").value = ""; setBusy(true);
  const pending = bubble("assistant"); pending.append(element("span","Searching your library and checking sources…","pending"));
  const controller = new AbortController(); const timeout = setTimeout(()=>controller.abort(),65000);
  try {
    const response = await fetch("/api/chat", {method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify({message,request_id:crypto.randomUUID()})});
    if (!response.ok) throw new Error();
    const reply = await response.json(); pending.parentElement.remove(); answer(reply);
  } catch {
    pending.textContent = "The request failed or timed out. No source-grounded answer was displayed. Try again."; pending.classList.add("notice","error");
  } finally { clearTimeout(timeout); setBusy(false); $("question").focus(); }
});
$("question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {event.preventDefault(); $("composer").requestSubmit();} });
$("reset").addEventListener("click", async () => {
  if (busy) return; setBusy(true);
  try { const response=await fetch("/api/chat/reset",{method:"POST"});if(!response.ok)throw new Error(); location.reload(); }
  catch { $("readiness").textContent="Could not reset the chat. Please try again.";setBusy(false); }
});
document.querySelectorAll("[data-query]").forEach(button=>button.addEventListener("click",()=>{$("question").value=button.dataset.query;$("question").focus();}));
loadStatus();
