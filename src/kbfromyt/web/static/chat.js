"use strict";
const $ = id => document.getElementById(id);
let busy = false;
let ready = false;
let libraryBusy = false;
let importCooldownUntil = 0;
let currentConversation = null;
let savedCount = 0;
let viewTurns = [];
let libraryPoll = null;
let overviewCount = 0;
let ownerReady = false;
let ownerMarker = null;
let scopeValid = false;
let currentScope = {kind:"library",playlist_id:null,video_ids:[]};
let scopeLibrary = {videos:[],playlists:[]};
let pendingRequest = null;
let recoveryTimer = null;
let recoveryBusy = false;
let resendAllowed = false;
try { pendingRequest = JSON.parse(sessionStorage.getItem("kb_pending_request") || "null"); } catch {}
if(pendingRequest && !/^[A-Za-z0-9_-]{8,80}$/.test(pendingRequest.payload?.request_id||""))pendingRequest=null;
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
  $("send").disabled = value || !ready || !ownerReady || !scopeValid || Boolean(pendingRequest);
  $("reset").disabled = value || Boolean(pendingRequest);
  $("question").disabled = value || Boolean(pendingRequest);
  $("chat-scope").disabled = value || Boolean(pendingRequest);
  $("chat-videos").disabled = value || Boolean(pendingRequest);
  $("recover-request").disabled=value||recoveryBusy;
  $("new-attempt").disabled=value||recoveryBusy;
  $("composer").setAttribute("aria-busy", String(value));
  $("import-playlist").disabled = value || libraryBusy || Date.now()<importCooldownUntil*1000;
  document.querySelectorAll("[data-import-retry]").forEach(button=>{
    button.disabled=value||libraryBusy||Date.now()<Number(button.dataset.retryNotBefore||0)*1000;
  });
  $("rebuild-library").disabled = value || libraryBusy;
  $("load-older").disabled = value;
  document.querySelectorAll(".conversation-button").forEach(button => { button.disabled = value || Boolean(pendingRequest); });
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
    trace.append(element("summary",`Retrieved ${c.evidence_passages} passages from ${c.evidence_videos} of ${c.scope_videos??c.library_videos} selected videos (${c.library_videos} in library)`));
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
function savePending() {
  try { if(pendingRequest)sessionStorage.setItem("kb_pending_request",JSON.stringify(pendingRequest));else sessionStorage.removeItem("kb_pending_request"); }
  catch { $("readiness").textContent="Browser storage is unavailable. Keep this page open to recover a lost response."; }
}
function recoveryNotice(message, allowNew=false) {
  $("request-recovery").hidden=false;$("recovery-message").textContent=message;
  $("new-attempt").hidden=!allowNew;setBusy(busy);
}
async function finishPending(reply) {
  clearTimeout(recoveryTimer);pendingRequest=null;savePending();
  $("request-recovery").hidden=true;resendAllowed=false;setBusy(false);
  if(reply.conversation_id)await openConversation(reply.conversation_id);
  else if(!viewTurns.some(turn=>turn.answer.reply_id===reply.reply_id)){answer(reply);viewTurns.push({seq:null,question:"",answer:reply});}
  await loadConversations();$("question").focus();
}
async function recoverPending() {
  clearTimeout(recoveryTimer);
  if(!pendingRequest||recoveryBusy||busy)return;
  recoveryBusy=true;setBusy(false);
  try {
    await loadConversations();
    if(!ownerReady)throw new Error();
    if(pendingRequest.owner_marker!==ownerMarker){
      recoveryNotice("This browser identity changed. The previous request cannot be recovered here; a new attempt may be charged.",true);return;
    }
    const response=await fetch(`/api/requests/${encodeURIComponent(pendingRequest.payload.request_id)}`);
    if(response.status===404){
      resendAllowed=true;$("recover-request").textContent="Resend same request";
      recoveryNotice("No saved request was found. Resending keeps the same request ID.");return;
    }
    if(!response.ok)throw new Error();const record=await response.json();
    resendAllowed=false;$("recover-request").textContent="Recover answer";
    if(record.state==="completed"&&record.answer){await finishPending(record.answer);return;}
    if(record.state==="queued"||record.state==="running"){
      recoveryNotice("Your original request is still in progress. Waiting for its result…");
      recoveryTimer=setTimeout(recoverPending,1500);return;
    }
    pendingRequest.recovered_conversation=record.conversation_id;savePending();
    recoveryNotice(record.notice||"The attempt ended without a recoverable answer. A new attempt may be charged.",true);
  }catch {recoveryNotice("Cannot check the original request. Recover again when the server is reachable.");}
  finally {recoveryBusy=false;setBusy(busy);}
}
async function sendPending() {
  if(!pendingRequest||busy)return;setBusy(true);resendAllowed=false;
  await loadConversations();
  if(!ownerReady||pendingRequest.owner_marker!==ownerMarker){
    setBusy(false);recoveryNotice("This browser identity is unavailable or changed. The previous request may have incurred provider work; a new attempt may be charged.",true);return;
  }
  $("recover-request").textContent="Recover answer";
  recoveryNotice("Searching the selected sources and checking citations…");
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),65000);
  try {
    const response=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify(pendingRequest.payload)});
    if(!response.ok)throw new Error();const reply=await response.json();
    if(reply.error_code?.startsWith("request_")){
      setBusy(false);recoveryNotice(reply.notice,true);return;
    }
    if(reply.status==="error"&&reply.usage?.provider_requests){setBusy(false);await recoverPending();return;}
    await finishPending(reply);
  }catch {setBusy(false);recoveryNotice("The connection was lost. Checking whether the original answer was saved…");await recoverPending();}
  finally {clearTimeout(timeout);setBusy(false);}
}
$("recover-request").addEventListener("click",()=>resendAllowed?sendPending():recoverPending());
$("new-attempt").addEventListener("click",async ()=>{
  if(!pendingRequest||busy)return;clearTimeout(recoveryTimer);
  const old=pendingRequest;pendingRequest=null;savePending();$("request-recovery").hidden=true;
  if(old.owner_marker!==ownerMarker){await newConversation();}
  else if(old.recovered_conversation)selectConversation(old.recovered_conversation);
  currentScope=old.payload.scope;renderChatScope();$("question").value=old.payload.message;
  setBusy(false);$("question").focus();
});
$("composer").addEventListener("submit",async event=>{
  event.preventDefault();const message=$("question").value.trim();
  if(!message||busy||!ready||!ownerReady||!scopeValid||pendingRequest)return;
  pendingRequest={owner_marker:ownerMarker,payload:{message,request_id:crypto.randomUUID(),conversation_id:currentConversation,scope:currentScope}};
  savePending();bubble("user",message);$("question").value="";await sendPending();
});
$("question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {event.preventDefault(); $("composer").requestSubmit();} });
async function newConversation() {
  if (busy||pendingRequest) return false; setBusy(true);
  try { const response=await fetch("/api/chat/reset",{method:"POST"});if(!response.ok)throw new Error(); selectConversation(null);viewTurns=[];clearMessages();await loadConversations();setBusy(false);$("question").focus();return true; }
  catch { $("readiness").textContent="Could not reset the chat. Please try again.";setBusy(false);return false; }
}
$("reset").addEventListener("click",newConversation);
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
    ownerReady=true;ownerMarker=data.owner_marker;
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
  } catch { ownerReady=false;$("conversation-list").replaceChildren(element("p","Saved chats could not be loaded. Reload before submitting a question."));setBusy(busy); }
}
async function openConversation(id,older=false) {
  if(busy)return;setBusy(true);
  try {
    const suffix=older&&viewTurns.length?`?before=${viewTurns[0].seq}`:"";
    const response=await fetch(`/api/conversations/${encodeURIComponent(id)}${suffix}`);if(!response.ok)throw new Error();
    const data=await response.json();selectConversation(id);
    currentScope=data.scope||{kind:"library",playlist_id:null,video_ids:[]};renderChatScope();
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
    importCooldownUntil=data.import_retry_not_before||0;
    scopeLibrary=data;renderChatScope();
    $("library-summary").textContent=`· ${data.videos.length} videos`;
    $("library-videos").replaceChildren(...data.videos.map(v=>element("li",`${v.title} · ${v.language.toUpperCase()} · ${v.chunks} chunks`)));
    $("playlist-list").replaceChildren();
    const selectedScope=$("overview-scope").value;$("overview-scope").replaceChildren();
    const allOption=element("option","Entire library");allOption.value="";$("overview-scope").append(allOption);
    for(const playlist of data.playlists){const p=element("p");const link=element("a",`Playlist · ${playlist.video_ids.length} imported videos ↗`);link.href=playlist.url;link.target="_blank";link.rel="noopener noreferrer";p.append(link);$("playlist-list").append(p);}
    for(const playlist of data.playlists){const option=element("option",`${playlist.title||playlist.id} · ${playlist.video_ids.length} videos`);option.value=playlist.id;$("overview-scope").append(option);}
    $("overview-scope").value=selectedScope;
    if(data.index?.count)$("index-summary").textContent=`${data.index.documents||data.index.count} source documents · ${data.index.count} embedding windows · ${data.index.token_limit||"—"} tokens per window`;
    const progress=$("library-progress");progress.replaceChildren();
    for(const [index,job] of data.jobs.entries()){
      const details=element("details",undefined,`job ${job.status}`);details.open=index===0;
      details.append(element("summary",`${job.kind==="import"?"Playlist import":"Clean and rebuild"} · ${job.status}`),element("p",job.message));
      if(job.error_code==="youtube_blocked")details.append(element("p","This affects new caption downloads. Rebuilding saved videos does not restore YouTube access."));
      if(job.created){
        const active=["queued","listing","downloading","processing","indexing"].includes(job.status);
        const seconds=Math.max(0,Math.floor((active?Date.now()/1000:job.finished||job.updated)-job.created));
        details.append(element("p",`Elapsed ${Math.floor(seconds/60)}m ${seconds%60}s · Last progress ${new Date(job.updated*1000).toLocaleTimeString()}`));
      }
      if(job.total){const bar=element("progress");bar.max=job.total;bar.value=job.completed;details.append(bar,element("span",` ${job.completed}/${job.total} checked · ${job.indexed??(job.results||[]).filter(r=>r.status==="indexed").length} indexed · ${job.failed} failed · ${job.skipped||0} not attempted`));}
      if(job.index_total){
        const bar=element("progress");bar.max=job.index_total;bar.value=job.index_completed;
        const unit=job.index_stage==="preparing"?"documents":"embedding windows";
        details.append(bar,element("span",` ${job.index_completed.toLocaleString()}/${job.index_total.toLocaleString()} ${unit} · ${Math.floor(job.index_completed/job.index_total*100)}%`));
      }
      if(job.retry_not_before&&Date.now()<job.retry_not_before*1000){
        details.append(element("p",`Downloads paused until at least ${new Date(job.retry_not_before*1000).toLocaleTimeString()}. This is local backoff; YouTube may require longer.`));
      }
      if(job.changed!==undefined)details.append(element("p",`${job.changed} videos updated`));
      if((job.results||[]).length){const items=element("ul");for(const item of job.results)items.append(element("li",`${item.title||item.video_id}: ${item.status.replaceAll("_"," ")}${item.message?" — "+item.message:""}`));details.append(items);}
      if(job.request&&["failed","partial","blocked"].includes(job.status)){
        const retry=element("button","Retry import","secondary");retry.type="button";
        retry.dataset.importRetry="true";retry.dataset.retryNotBefore=String(data.import_retry_not_before||0);
        retry.addEventListener("click",()=>libraryAction("/api/library/import",job.request));details.append(retry);
      }
      progress.append(details);
    }
    if(libraryBusy){$("library-panel").open=true;libraryPoll=setTimeout(loadLibrary,1500);}
    else if(Date.now()<importCooldownUntil*1000){libraryPoll=setTimeout(loadLibrary,Math.min(30000,importCooldownUntil*1000-Date.now()));}
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
function renderChatScope() {
  const select=$("chat-scope");select.replaceChildren();
  for(const [value,label] of [["library","Entire library"],["videos","Selected videos"]]){
    const option=element("option",label);option.value=value;select.append(option);
  }
  for(const playlist of scopeLibrary.playlists){
    const option=element("option",`Playlist · ${playlist.title||playlist.id}`);option.value=`playlist:${playlist.id}`;select.append(option);
  }
  const value=currentScope.kind==="playlist"?`playlist:${currentScope.playlist_id}`:currentScope.kind;
  if(!Array.from(select.options).some(option=>option.value===value)){
    const option=element("option","Unavailable playlist");option.value=value;select.append(option);
  }
  select.value=value;$("chat-video-label").hidden=currentScope.kind!=="videos";
  const videos=$("chat-videos");videos.replaceChildren();
  const chosen=new Set(currentScope.video_ids||[]);
  for(const video of scopeLibrary.videos){const option=element("option",video.title);option.value=video.id;option.selected=chosen.has(video.id);videos.append(option);}
  for(const id of chosen)if(!scopeLibrary.videos.some(video=>video.id===id)){
    const option=element("option",`Unavailable video · ${id}`);option.value=id;option.selected=true;videos.append(option);
  }
  const selected=currentScope.kind==="library"?scopeLibrary.videos.map(video=>video.id):currentScope.kind==="videos"?[...chosen]:(scopeLibrary.playlists.find(playlist=>playlist.id===currentScope.playlist_id)?.video_ids||[]);
  scopeValid=selected.length>0&&selected.every(id=>scopeLibrary.videos.some(video=>video.id===id));
  $("chat-scope-count").textContent=scopeValid?`${new Set(selected).size} selected videos · Changing sources starts a new chat` : "Choose available sources before asking a question";
  setBusy(busy);
}
async function changeChatScope() {
  if(busy||pendingRequest){renderChatScope();return;}
  const value=$("chat-scope").value;
  const next=value.startsWith("playlist:")?{kind:"playlist",playlist_id:value.slice(9),video_ids:[]}:
    {kind:value,playlist_id:null,video_ids:value==="videos"?Array.from($("chat-videos").selectedOptions,option=>option.value).sort():[]};
  if(await newConversation()){currentScope=next;renderChatScope();}else renderChatScope();
}
$("chat-scope").addEventListener("change",changeChatScope);
$("chat-videos").addEventListener("change",changeChatScope);
async function start() {
  await loadConversations();await loadLibrary();
  if(currentConversation)await openConversation(currentConversation);
  if(pendingRequest){currentScope=pendingRequest.payload.scope;renderChatScope();await recoverPending();}
}
start();
