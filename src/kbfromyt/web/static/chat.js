"use strict";
const $ = id => document.getElementById(id);
let busy = false;
let ready = false;
let libraryBusy = false;
let currentConversation = null;
let savedCount = 0;
let viewTurns = [];
let libraryPoll = null;
let overviewCount = 0;
const welcomeTemplate = $("welcome").cloneNode(true);
try { currentConversation = localStorage.getItem("kb_current_chat"); } catch {}
const labels = {grounded:"Cited answer",partial:"Partial source support",no_support:"Insufficient retrieved evidence",verification_failed:"Verification failed",error:"Request failed"};
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
  $("import-playlist").disabled = value || libraryBusy;
  $("rebuild-library").disabled = value || libraryBusy;
  $("load-older").disabled = value;
  document.querySelectorAll(".conversation-button").forEach(button => { button.disabled = value; });
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
  if(reply.coverage?.evidence_passages || reply.retrieval?.length) {
    const trace=element("details",undefined,"search-trace");
    const c=reply.coverage;
    trace.append(element("summary",`Retrieved ${c.evidence_passages} passages from ${c.evidence_videos} of ${c.library_videos} videos`));
    trace.append(element("p","This describes the retrieved excerpts, not a review of every video."));
    const items=element("ul");for(const step of reply.retrieval||[])items.append(element("li",`${step.tool}: ${step.query||"Neighboring source context"} · ${step.chunk_ids.length} candidates`));
    trace.append(items);body.append(trace);
  }
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
  setBusy(busy);
}
$("composer").addEventListener("submit", async event => {
  event.preventDefault(); const message = $("question").value.trim();
  if (!message || busy || !ready) return;
  bubble("user", message); $("question").value = ""; setBusy(true);
  const pending = bubble("assistant"); pending.append(element("span","Searching your library and checking sources…","pending"));
  const controller = new AbortController(); const timeout = setTimeout(()=>controller.abort(),65000);
  try {
    const response = await fetch("/api/chat", {method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify({message,request_id:crypto.randomUUID(),conversation_id:currentConversation})});
    if (!response.ok) throw new Error();
    const reply = await response.json(); pending.parentElement.remove(); answer(reply);
    viewTurns.push({seq:null,question:message,answer:reply});
    if (reply.conversation_id) { selectConversation(reply.conversation_id); await loadConversations(); }
  } catch {
    pending.textContent = "The request failed or timed out. No source-grounded answer was displayed. Try again."; pending.classList.add("notice","error");
  } finally { clearTimeout(timeout); setBusy(false); $("question").focus(); }
});
$("question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {event.preventDefault(); $("composer").requestSubmit();} });
$("reset").addEventListener("click", async () => {
  if (busy) return; setBusy(true);
  try { const response=await fetch("/api/chat/reset",{method:"POST"});if(!response.ok)throw new Error(); selectConversation(null);viewTurns=[];clearMessages();await loadConversations();setBusy(false);$("question").focus(); }
  catch { $("readiness").textContent="Could not reset the chat. Please try again.";setBusy(false); }
});
document.addEventListener("click",event=>{const button=event.target.closest("[data-query]");if(button){$("question").value=button.dataset.query;$("question").focus();}});

function selectConversation(id) {
  currentConversation = id;
  try { if (id) localStorage.setItem("kb_current_chat",id); else localStorage.removeItem("kb_current_chat"); } catch {}
}
function clearMessages() {
  $("messages").replaceChildren(welcomeTemplate.cloneNode(true));
  $("load-older").hidden = true;
}
async function loadConversations(more=false) {
  try {
    const response=await fetch(`/api/conversations?offset=${more?savedCount:0}`);if(!response.ok)throw new Error();
    const data=await response.json();
    if(!more){$("conversation-list").replaceChildren();savedCount=0;}
    for(const conversation of data.conversations){
      const button=element("button",conversation.title,"conversation-button");button.type="button";
      button.title=new Date(conversation.updated*1000).toLocaleString();
      button.classList.toggle("selected",conversation.id===currentConversation);
      button.addEventListener("click",()=>openConversation(conversation.id));
      $("conversation-list").append(button);savedCount++;
    }
    if(!savedCount)$("conversation-list").append(element("p","Your conversations will be saved here."));
    $("more-conversations").hidden=!data.has_more;setBusy(busy);
  } catch { $("conversation-list").replaceChildren(element("p","Saved chats could not be loaded.")); }
}
async function openConversation(id,older=false) {
  if(busy)return;setBusy(true);
  try {
    const suffix=older&&viewTurns.length?`?before=${viewTurns[0].seq}`:"";
    const response=await fetch(`/api/conversations/${encodeURIComponent(id)}${suffix}`);if(!response.ok)throw new Error();
    const data=await response.json();selectConversation(id);
    viewTurns=older?[...data.turns,...viewTurns]:data.turns;
    clearMessages();
    for(const turn of viewTurns){bubble("user",turn.question);answer(turn.answer);}
    $("load-older").hidden=!data.has_older;
    if(older)$("messages").scrollTop=0;
    await loadConversations();
  } catch { $("readiness").textContent="Could not open this saved chat. Select another chat or start a new one."; }
  finally {setBusy(false);}
}
$("more-conversations").addEventListener("click",()=>loadConversations(true));
$("load-older").addEventListener("click",()=>openConversation(currentConversation,true));

async function loadLibrary() {
  clearTimeout(libraryPoll);
  try {
    const response=await fetch("/api/library");if(!response.ok)throw new Error();const data=await response.json();
    libraryBusy=Boolean(data.active_job);
    $("library-summary").textContent=`· ${data.videos.length} videos`;
    $("library-videos").replaceChildren(...data.videos.map(v=>element("li",`${v.title} · ${v.language.toUpperCase()} · ${v.chunks} chunks`)));
    $("playlist-list").replaceChildren();
    const selectedScope=$("overview-scope").value;$("overview-scope").replaceChildren();
    const allOption=element("option","Entire library");allOption.value="";$("overview-scope").append(allOption);
    for(const playlist of data.playlists){const p=element("p");const link=element("a",`Playlist · ${playlist.video_ids.length} imported videos ↗`);link.href=playlist.url;link.target="_blank";link.rel="noopener noreferrer";p.append(link);$("playlist-list").append(p);}
    for(const playlist of data.playlists){const option=element("option",`${playlist.id} · ${playlist.video_ids.length} videos`);option.value=playlist.id;$("overview-scope").append(option);}
    $("overview-scope").value=selectedScope;
    if(data.index?.count)$("index-summary").textContent=`${data.index.documents||data.index.count} source documents · ${data.index.count} embedding windows · ${data.index.token_limit||"—"} tokens per window`;
    const progress=$("library-progress");progress.replaceChildren();
    for(const [index,job] of data.jobs.entries()){
      const details=element("details",undefined,`job ${job.status}`);details.open=index===0;
      details.append(element("summary",`${job.kind==="import"?"Playlist import":"Clean and rebuild"} · ${job.status}`),element("p",job.message));
      if(job.total){const bar=element("progress");bar.max=job.total;bar.value=job.completed;details.append(bar,element("span",` ${job.completed}/${job.total} fetched · ${job.failed} failed`));}
      if(job.changed!==undefined)details.append(element("p",`${job.changed} videos updated`));
      if(job.results.length){const items=element("ul");for(const item of job.results)items.append(element("li",`${item.title||item.video_id}: ${item.status}${item.message?" — "+item.message:""}`));details.append(items);}
      progress.append(details);
    }
    if(libraryBusy){$("library-panel").open=true;libraryPoll=setTimeout(loadLibrary,1500);}
    await loadStatus();setBusy(busy);
  } catch { $("library-progress").textContent="Cannot load library status. Reload to try again."; }
}
async function libraryAction(path,body) {
  if(busy||libraryBusy)return;libraryBusy=true;setBusy(busy);
  try {
    const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
    if(!response.ok){const error=await response.json();throw new Error(typeof error.detail==="string"?error.detail:"Check the playlist URL, limit and caption languages.");}
    await loadLibrary();
  } catch(error) {libraryBusy=false;$("library-progress").textContent=error.message;setBusy(busy);}
}
$("playlist-form").addEventListener("submit",event=>{event.preventDefault();libraryAction("/api/library/import",{url:$("playlist-url").value.trim(),limit:Number($("playlist-limit").value),languages:$("playlist-languages").value.split(",").map(v=>v.trim()).filter(Boolean)});});
$("rebuild-library").addEventListener("click",()=>libraryAction("/api/library/rebuild"));
async function loadOverviews(more=false){
  const container=$("overview-videos");if(!more){container.replaceChildren();overviewCount=0;}
  try{
    const scope=$("overview-scope").value;const response=await fetch(`/api/library/overview?offset=${overviewCount}&limit=10${scope?"&playlist="+encodeURIComponent(scope):""}`);if(!response.ok)throw new Error();
    const data=await response.json();
    for(const video of data.videos){
      const card=element("details",undefined,"overview-card");card.append(element("summary",video.title));
      card.append(element("p",video.topics.join(" · "),"source-meta"));
      for(const passage of video.passages){
        const p=element("p");const link=element("a",`${passage.chapter_title} · ${timestamp(passage.start)} ↗`);link.href=passage.url;link.target="_blank";link.rel="noopener noreferrer";
        p.append(link,element("blockquote",passage.excerpt));card.append(p);
      }container.append(card);overviewCount++;
    }
    $("more-overviews").hidden=!data.has_more;
    if(!overviewCount)container.append(element("p",data.updating?"Overviews are being prepared…":"No source overviews are available yet. Use Clean and rebuild."));
  }catch{container.append(element("p","Could not load the source overviews."));}
}
$("overview-panel").addEventListener("toggle",()=>{if($("overview-panel").open)loadOverviews();});
$("overview-scope").addEventListener("change",()=>loadOverviews());
$("more-overviews").addEventListener("click",()=>loadOverviews(true));
async function start() {
  await loadConversations();await loadLibrary();
  if(currentConversation)await openConversation(currentConversation);
}
start();
