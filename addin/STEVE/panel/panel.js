/* Plain browser UI. Fusion is the only production bridge; previews are explicitly marked. */
"use strict";
const $ = (id) => document.getElementById(id);
const preview = new URLSearchParams(location.search).get("preview");
let state = {connection:"starting",account:null,accountChecked:false,models:[],model:"",messages:[],busy:false,loginPending:false,status:"Checking your account",error:""};
let messageViews = new Map();
let turnViews = new Map();
let renderedControls = "";
let renderFrame = null;
let renderedModels = "";
let renderedEfforts = "";
let dismissedError = "";
let dismissedUpdate = "";
let submitting = false;
let renderedThread = null;
let renderedTranscriptPage = "latest";
let renderedProvider = null;
let renderedHistory = "";
let draftImages = [];
let draftImageRevision = 0;
let nextDraftImage = 0;
let clipboardRequest = null;
const imageCache = new Map();
const ICONS = {
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7"/></svg>',
  cross: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  warn: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4m0 3.5v.5M3.5 19h17L12 4z"/></svg>',
  spinner: '<span class="spinner" aria-hidden="true"></span>',
};
const STEP_PHASES = {completed:"Completed", failed:"Failed", unconfirmed:"Completion unconfirmed"};

function escapeHTML(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function markdown(text) {
  return SteveMarkdown.render(text);
}

async function bridge(action,payload={}) {
  if(preview){previewAction(action,payload);return {ok:true};}
  if(!window.adsk?.fusionSendData) throw new Error("Open STEVE inside Fusion to connect.");
  const result = await window.adsk.fusionSendData(action,JSON.stringify(payload));
  if(result){const parsed=typeof result==="string"?JSON.parse(result):result;if(parsed.ok===false)throw new Error(parsed.error||"Fusion could not process that action.");return parsed;}
}
function act(action,payload={}) {
  return bridge(action,payload).catch((error)=>{state.error=error.message;dismissedError="";submitting=false;render();});
}

function openImage(url, name) {
  if (!SteveImages.storedImageURL(url)) return;
  $("expanded-image").src = url;
  $("expanded-image").alt = name;
  $("image-viewer").showModal();
}
function renderDraftImages() {
  $("image-drafts").hidden = !draftImages.length;
  $("image-drafts").replaceChildren(...draftImages.map(item => {
    const chip = document.createElement("div");chip.className="image-chip";
    const thumbnail = document.createElement("button");thumbnail.type="button";thumbnail.className="image-thumbnail";
    thumbnail.title=item.name;thumbnail.disabled=!item.url;
    if(item.url){const img=document.createElement("img");img.src=item.url;img.alt=item.name;thumbnail.append(img);thumbnail.onclick=()=>openImage(item.url,item.name);}
    else thumbnail.textContent="Preparing…";
    const remove=document.createElement("button");remove.type="button";remove.className="remove-image";remove.textContent="×";
    remove.setAttribute("aria-label",`Remove ${item.name}`);
    remove.onclick=()=>{draftImages=draftImages.filter(other=>other!==item);draftImageRevision++;renderDraftImages();render();};
    chip.append(thumbnail,remove);return chip;
  }));
  $("image-hint").hidden=!draftImages.length;
  $("image-hint").textContent=draftImages.some(item=>!item.url)?"Preparing images…":
    `${draftImages.length}/4 images attached${draftImages.some(item=>item.compressed)?" · Resized for chat":""}`;
}
async function attachImages(files) {
  if(!state.account || state.connection!=="ready")return;
  const available=4-draftImages.length;
  if(files.length>available){state.error="Attach at most four images per message.";dismissedError="";render();return;}
  const items=files.map(file=>({id:++nextDraftImage,name:file.name||"Pasted image",file}));
  draftImages.push(...items);draftImageRevision++;renderDraftImages();render();
  await Promise.all(items.map(async item=>{
    try{const prepared=await SteveImages.prepare(item.file);Object.assign(item,prepared);delete item.file;}
    catch(error){draftImages=draftImages.filter(other=>other!==item);state.error=error.message;dismissedError="";}
    draftImageRevision++;renderDraftImages();render();
  }));
}
function pasteClipboardImage() {
  if (clipboardRequest || submitting || !state.account || state.connection !== "ready") return;
  if (draftImages.length >= 4) {state.error="Attach at most four images per message.";dismissedError="";render();return;}
  const request = {id:`paste-${Date.now()}-${++nextDraftImage}`, threadId:state.threadId};
  clipboardRequest=request;
  request.timer=setTimeout(()=>finishClipboardImage({requestId:request.id,error:"Image paste timed out. Copy the screenshot and paste again."}),15000);
  render();
  bridge("clipboardImage",{requestId:request.id}).catch(error=>finishClipboardImage({requestId:request.id,error:error.message}));
}
async function finishClipboardImage(result) {
  const request=clipboardRequest;
  if (!request || request.receiving || result.requestId!==request.id) return;
  request.receiving=true;
  clearTimeout(request.timer);
  try {
    if (state.threadId!==request.threadId || !state.account || state.connection!=="ready") return;
    if (result.error) throw new Error(result.error);
    if (!result.image) throw new Error("No image is available on the clipboard. Copy the screenshot itself, then paste.");
    await attachImages([SteveImages.clipboardFile(result.image)]);
  } catch(error) {state.error=error.message;dismissedError="";}
  finally {if(clipboardRequest===request)clipboardRequest=null;render();}
}
function renderMessageImages(article, body, images) {
  if(!images.length)return;
  const gallery=document.createElement("div");gallery.className="message-images";
  article.insertBefore(gallery,body);
  images.forEach(reference=>{
    const card=document.createElement("div");card.className=reference.generated?"concept-image":"reference-image";
    const button=document.createElement("button");button.type="button";button.className="saved-image";
    button.textContent=reference.name||"Reference image";button.disabled=true;
    card.append(button);gallery.append(card);
    if(reference.generated){
      const caption=document.createElement("div");caption.className="concept-caption";
      caption.innerHTML='<span class="dream-tag">✧ Dream</span><span class="concept-note">Visual reference · not verified geometry</span>';
      const actions=document.createElement("div");actions.className="concept-actions";
      for(const [label, action] of [["Refine","refine"],["Use as reference","reference"],["Save","save"]]){
        const control=document.createElement("button");control.type="button";control.className="chip-button";
        control.textContent=label;
        if(action==="save"){
          control.title="Save the original image to Downloads";
          control.onclick=async()=>{
            control.disabled=true;
            try{await bridge("saveConcept",{id:reference.id});control.textContent="Saved to Downloads";}
            catch(error){state.error=error.message;dismissedError="";render();}
            finally{control.disabled=false;}
          };
        }else{
          control.className+=" concept-draft-action";
          control.dataset.action=action;
          control.title=action==="refine"?"Ask STEVE for a new version of this concept":"Attach this concept to your next message";
          control.disabled=!canUseConcept(action);
          control.onclick=()=>useConcept(reference,action);
        }
        actions.append(control);
      }
      card.append(caption,actions);
    }
    if(!reference.id)return;
    if(!imageCache.has(reference.id)) imageCache.set(reference.id,
      bridge("imageAssets",{ids:[reference.id]}).then(result=>result?.images?.[reference.id]).catch(()=>null));
    imageCache.get(reference.id).then(url=>{
      if(!SteveImages.storedImageURL(url)){button.textContent="Image preview unavailable";return;}
      const img=document.createElement("img");img.src=url;img.alt=reference.name||"Reference image";img.loading="lazy";
      button.replaceChildren(img);button.disabled=false;button.title="View image";
      button.onclick=()=>openImage(url,reference.name||"Reference image");
    });
  });
  return gallery;
}
function canUseConcept(action) {
  const model=state.models?.find(model=>model.id===state.model);
  return !!state.account && state.connection==="ready" && !state.busy && !state.jobBusy &&
    !state.updateInstalling && !state.updateInstallReady && !submitting && !clipboardRequest &&
    model?.supportsImages!==false && (action!=="refine" || (state.provider||"chatgpt")==="chatgpt");
}
async function useConcept(reference, action) {
  if(!canUseConcept(action))return;
  if($("message").value.trim() || draftImages.length){state.error="Send or clear your draft before choosing a concept.";dismissedError="";render();return;}
  const provider=state.provider, threadId=state.threadId, revision=draftImageRevision;
  try{
    const url=await (imageCache.get(reference.id) || bridge("imageAssets",{ids:[reference.id]}).then(result=>result?.images?.[reference.id]));
    const prepared=await SteveImages.prepare(SteveImages.storedFile(url,reference.name));
    if(state.provider!==provider || state.threadId!==threadId || !canUseConcept(action) ||
       revision!==draftImageRevision || $("message").value.trim() || draftImages.length)return;
    draftImages=[{id:++nextDraftImage,...prepared}];draftImageRevision++;
    $("message").value=action==="refine"?"Refine this concept: ":"Use this concept as a visual reference. ";
    renderDraftImages();resize();$("message").focus();
  }catch(error){state.error=error.message;dismissedError="";}
  render();
}
function dreamDraft() {
  if(!canUseConcept("refine"))return;
  const text=$("message").value.trim();
  const prompt=text?"Generate a concept image for: " + text:"Generate a concept image for ";
  if(prompt.length>32000){state.error="Shorten your draft before using Dream.";dismissedError="";render();return;}
  $("message").value=prompt;resize();$("message").focus();render();
}
async function reuseMessage(message) {
  if($("message").value.trim() || draftImages.length){state.error="Send or clear your current draft before reusing this message.";dismissedError="";render();return;}
  const provider=state.provider, threadId=state.threadId;
  try {
    const references=message.images||[];
    const result=references.length?await bridge("imageAssets",{ids:references.map(image=>image.id)}):{images:{}};
    if(state.provider!==provider || state.threadId!==threadId)return;
    if(references.some(image=>!SteveImages.imageURL(result?.images?.[image.id])))throw new Error("The saved image is unavailable. Paste it again.");
    // A user may begin another draft while the native bridge is returning.
    if($("message").value.trim() || draftImages.length)return;
    draftImages=references.map(image=>({id:++nextDraftImage,name:image.name,url:result.images[image.id]}));
    $("message").value=message.text;draftImageRevision++;renderDraftImages();resize();$("message").focus();
  } catch(error){state.error=error.message;dismissedError="";}
  render();
}
// Reconcile the safe Markdown tree without detaching existing paragraphs, code
// blocks or text. Appending a token should not restart animations or selection.
function patchChildren(parent, next) {
  const desired = Array.from(next.childNodes);
  desired.forEach((node, index) => {
    const current = parent.childNodes[index];
    if (!current) { parent.appendChild(node); return; }
    if (current.nodeType !== node.nodeType || current.nodeName !== node.nodeName) {
      parent.replaceChild(node, current); return;
    }
    if (node.nodeType === 3) {
      if (current.data !== node.data) {
        if (node.data.startsWith(current.data)) current.appendData(node.data.slice(current.data.length));
        else current.replaceData(0, current.length, node.data);
      }
    } else {
      if (node.attributes) {
        for (const {name, value} of Array.from(node.attributes)) if (current.getAttribute(name) !== value) current.setAttribute(name, value);
        for (const {name} of Array.from(current.attributes)) if (!node.hasAttribute(name)) current.removeAttribute(name);
      }
      patchChildren(current, node);
    }
  });
  while (parent.childNodes.length > desired.length) parent.lastChild.remove();
}

// Collapsible sections remember whether the person overrode the automatic open state.
function trackToggle(view) {
  view.auto = null; view.manual = false;
  view.details.addEventListener("toggle", () => { view.manual = view.details.open !== view.auto; });
}
function setOpen(view, open) {
  if (view.auto === open) return;
  view.auto = open;
  if (!view.manual && view.details.open !== open) view.details.open = open;
}

// One step per Python script STEVE submits to Fusion.
function createStep() {
  const details = document.createElement("details");
  details.className = "step code-card";
  details.innerHTML = '<summary><span class="step-icon" aria-hidden="true"></span><span class="step-title"></span><span class="step-meta code-meta"></span></summary>' +
    '<div class="step-body"><div class="code-tools"><span class="code-lang">Python</span><button type="button" class="copy-code">Copy</button></div>' +
    '<pre tabindex="0" aria-label="Submitted Fusion Python"><code></code></pre><div class="step-error" hidden></div></div>';
  const q = selector => details.querySelector(selector);
  const view = {details, icon: q(".step-icon"), title: q(".step-title"), meta: q(".step-meta"), pre: q("pre"), code: q("code"), error: q(".step-error"), source: null, status: null};
  trackToggle(view);
  return view;
}
function stepPhase(status) {
  if (status !== "running") return STEP_PHASES[status] || STEP_PHASES.unconfirmed;
  return state.status === "Stopping" ? "Stopping" : state.waitingForFusion ? "Waiting for Fusion" : "Running in Fusion";
}
function updateStep(view, message) {
  const status = message.toolStatus || "unconfirmed";
  const lines = (message.code || "").split("\n").length;
  const error = typeof message.error === "string" ? message.error : "";
  const meta = status === "failed" && error ? `Failed · ${error}` : `${stepPhase(status)} · ${lines} ${lines === 1 ? "line" : "lines"}`;
  const title = message.title || "Fusion Python";
  const signature = JSON.stringify([message.code, title, meta, status, error, !!message.historical]);
  if (view.signature === signature) return false;
  view.signature = signature;
  if (view.status !== status) {
    view.status = status;
    view.details.dataset.status = status;
    view.icon.innerHTML = status === "running" ? ICONS.spinner : status === "completed" ? ICONS.check : status === "failed" ? ICONS.cross : ICONS.warn;
  }
  if (view.title.textContent !== title) view.title.textContent = title;
  if (view.meta.textContent !== meta) view.meta.textContent = meta;
  if (view.source !== message.code) {
    view.source = message.code;
    view.code.innerHTML = SteveMarkdown.highlight(message.code || "", "python");
    view.pre.scrollTop = 0;
  }
  if (view.error.textContent !== error) view.error.textContent = error;
  view.error.hidden = !error;
  setOpen(view, status === "running" && !message.historical);
  return true;
}

// Consecutive steps form one activity block that stays open while STEVE works and folds up when it is done.
function createActivity() {
  const details = document.createElement("details");
  details.className = "activity";
  details.innerHTML = '<summary><span class="activity-icon" aria-hidden="true"></span><span class="activity-title"></span><span class="activity-meta"></span><span class="chevron" aria-hidden="true"></span></summary><div class="steps"></div>';
  const q = selector => details.querySelector(selector);
  const view = {details, icon: q(".activity-icon"), title: q(".activity-title"), meta: q(".activity-meta"), steps: q(".steps"), stepViews: new Map(), state: null};
  trackToggle(view);
  return view;
}
function updateActivity(view, block, live) {
  let changed = false, slot = 0;
  block.steps.forEach(({message, key}) => {
    let step = view.stepViews.get(key);
    if (!step) { step = createStep(); view.stepViews.set(key, step); changed = true; }
    if (view.steps.childNodes[slot] !== step.details) { view.steps.insertBefore(step.details, view.steps.childNodes[slot] || null); changed = true; }
    slot++;
    changed = updateStep(step, message) || changed;
  });
  while (view.steps.childNodes.length > slot) { view.steps.lastChild.remove(); changed = true; }
  for (const key of Array.from(view.stepViews.keys())) if (!block.steps.some(step => step.key === key)) view.stepViews.delete(key);
  const statuses = block.steps.map(step => step.message.toolStatus || "unconfirmed");
  const running = block.steps.find(step => step.message.toolStatus === "running");
  const failed = statuses.filter(status => status === "failed").length;
  const unconfirmed = statuses.filter(status => status === "unconfirmed").length;
  const count = block.steps.length;
  const historical = block.steps.every(step => step.message.historical);
  const steps = `${count} ${count === 1 ? "step" : "steps"}`;
  let name, title, meta;
  if (running || live) {
    // The open step row carries its own title; the summary only says that work is in progress.
    name = "live"; title = running ? (state.status === "Stopping" ? "Stopping" : state.waitingForFusion ? "Waiting for Fusion" : "Working in Fusion") : "Working in Fusion"; meta = steps;
  } else {
    title = `Ran ${steps} in Fusion`;
    name = failed ? "failed" : unconfirmed ? "unconfirmed" : "done";
    meta = failed ? `${failed} failed` : unconfirmed ? `${unconfirmed} unconfirmed` : "";
  }
  const signature = JSON.stringify([name, title, meta, live, historical]);
  if (view.signature !== signature) {
    view.signature = signature; changed = true;
    if (view.state !== name) {
      view.state = name;
      view.details.dataset.state = name;
      view.icon.innerHTML = name === "live" ? ICONS.spinner : name === "failed" ? ICONS.cross : name === "unconfirmed" ? ICONS.warn : ICONS.check;
    }
    if (view.title.textContent !== title) view.title.textContent = title;
    if (view.meta.textContent !== meta) view.meta.textContent = meta;
    setOpen(view, live && !historical);
  }
  return changed;
}

function ensureMessageView(key, message) {
  let view = messageViews.get(key);
  if (view) return view;
  const article = document.createElement("article");
  article.className = `message ${message.role === "user" ? "user" : "assistant"}${message.concept ? " concept" : ""}`;
  const body = document.createElement("div"); body.className = "message-body"; article.append(body);
  view = {article, body, text: null, images: null, gallery: null};
  messageViews.set(key, view);
  return view;
}
function userHTML(message) {
  return `${message.text ? `<p>${escapeHTML(message.text)}</p>` : ""}` +
    `${message.selectionCount ? `<small class="message-note">${Number(message.selectionCount)} selected at send</small>` : ""}` +
    `${message.delivery === "pending" ? '<small class="message-note">Sending…</small>' : message.delivery === "failed" ?
      '<small class="message-note delivery-failed">Delivery unconfirmed</small><button class="text-button reuse-message" type="button">Reuse message</button>' : ""}`;
}
function updateMessageView(view, message) {
  let changed = false;
  const images = JSON.stringify(message.images || []);
  if (view.images !== images) {
    view.gallery?.remove();
    view.gallery = renderMessageImages(view.article, view.body, message.images || []);
    view.images = images; changed = true;
  }
  view.gallery?.querySelectorAll(".concept-draft-action").forEach(button => {
    const disabled = !canUseConcept(button.dataset.action); if (button.disabled !== disabled) button.disabled = disabled;
  });
  if (message.conceptStatus && view.article.dataset.conceptStatus !== message.conceptStatus) { view.article.dataset.conceptStatus = message.conceptStatus; changed = true; }
  const signature = JSON.stringify([message.text, message.delivery, message.selectionCount]);
  if (view.text !== signature) {
    const template = document.createElement("template");
    template.innerHTML = message.role === "user" ? userHTML(message) : markdown(message.text);
    patchChildren(view.body, template.content);
    const reuse = view.body.querySelector(".reuse-message"); if (reuse) reuse.onclick = () => reuseMessage(message);
    view.text = signature; changed = true;
  }
  return changed;
}

// Messages are grouped into turns: the request, then STEVE's steps and replies.
function planTurns() {
  const turns = [];
  state.messages.forEach((message, index) => {
    const key = `${state.threadId || ""}:${message.role}:${message.id ?? ((state.messageOffset || 0) + index)}`;
    if (message.role === "user") { turns.push({key, user: {message, key}, blocks: []}); return; }
    if (!turns.length) turns.push({key: `${state.threadId || ""}:lead`, user: null, blocks: []});
    const turn = turns[turns.length - 1];
    if (message.role === "tool") {
      const last = turn.blocks[turn.blocks.length - 1];
      if (last && last.type === "activity") last.steps.push({message, key});
      else turn.blocks.push({type: "activity", key: "activity:" + key, steps: [{message, key}]});
    } else turn.blocks.push({type: "message", key, message});
  });
  return turns;
}
function renderMessages() {
  const conversation = $("conversation");
  let changed = false;
  const turns = planTurns();
  const usedViews = new Set(), usedTurns = new Set();
  const place = (parent, node, index) => {
    if (parent.childNodes[index] !== node) { parent.insertBefore(node, parent.childNodes[index] || null); changed = true; }
  };
  turns.forEach((turn, t) => {
    let turnView = turnViews.get(turn.key);
    if (!turnView) {
      const section = document.createElement("section"); section.className = "turn";
      const head = document.createElement("div"); head.className = "turn-head"; head.innerHTML = '<img src="mark.svg" alt=""> STEVE';
      turnView = {section, head}; turnViews.set(turn.key, turnView); changed = true;
    }
    usedTurns.add(turn.key);
    place(conversation, turnView.section, t);
    let slot = 0;
    if (turn.user) {
      const view = ensureMessageView(turn.user.key, turn.user.message); usedViews.add(turn.user.key);
      place(turnView.section, view.article, slot++);
      changed = updateMessageView(view, turn.user.message) || changed;
    }
    if (turn.blocks.length) place(turnView.section, turnView.head, slot++);
    turn.blocks.forEach((block, b) => {
      const live = !state.showingOlderMessages && !!state.busy && t === turns.length - 1 && b === turn.blocks.length - 1;
      if (block.type === "activity") {
        let view = messageViews.get(block.key);
        if (!view) { view = createActivity(); messageViews.set(block.key, view); changed = true; }
        usedViews.add(block.key);
        place(turnView.section, view.details, slot++);
        changed = updateActivity(view, block, live) || changed;
      } else {
        const view = ensureMessageView(block.key, block.message); usedViews.add(block.key);
        place(turnView.section, view.article, slot++);
        changed = updateMessageView(view, block.message) || changed;
      }
    });
    while (turnView.section.childNodes.length > slot) { turnView.section.lastChild.remove(); changed = true; }
  });
  while (conversation.childNodes.length > turns.length) { conversation.lastChild.remove(); changed = true; }
  for (const key of Array.from(messageViews.keys())) if (!usedViews.has(key)) messageViews.delete(key);
  for (const key of Array.from(turnViews.keys())) if (!usedTurns.has(key)) turnViews.delete(key);
  return changed;
}

function scheduleRender() {
  if (renderFrame !== null) return;
  renderFrame = requestAnimationFrame(() => { renderFrame = null; render(); });
}

function render() {
  const scroll = $("scroll-area");
  // Read before changing content, and finish scrolling in this same frame.
  const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
  const wasEmpty = messageViews.size === 0;
  const threadChanged = renderedThread !== (state.threadId || null);
  const transcriptPage = state.showingOlderMessages ? String(state.messageOffset || 0) : "latest";
  const pageChanged = transcriptPage !== renderedTranscriptPage;
  renderedTranscriptPage = transcriptPage;
  const provider=state.provider||"chatgpt";
  if(renderedProvider && renderedProvider!==provider){
    if(clipboardRequest)clearTimeout(clipboardRequest.timer);
    draftImages=[];draftImageRevision++;imageCache.clear();clipboardRequest=null;
    $("message").value="";renderDraftImages();
  }
  renderedProvider=provider;
  if(threadChanged && renderedThread)imageCache.clear();
  renderedThread = state.threadId || null;
  const controls = JSON.stringify({...state, messages: undefined,
    hasMessages: state.messages.length > 0, runningStep: state.messages.some(m => m.role === "tool" && m.toolStatus === "running"),
    draft: $("message").value, draftImageRevision, submitting, clipboardPending:!!clipboardRequest, dismissedError});
  if (controls !== renderedControls) {
    renderControls();
    renderedControls = controls;
  }
  if (renderMessages()) {
    if (!state.messages.length) scroll.scrollTop = 0;
    else if (pageChanged && state.showingOlderMessages) scroll.scrollTop = 0;
    else if (pageChanged) scroll.scrollTop = scroll.scrollHeight;
    else if (nearBottom || wasEmpty || threadChanged) scroll.scrollTop = scroll.scrollHeight;
  }
}

function renderControls() {
  $("transcript-pages").hidden = !state.olderMessagesCount && !state.showingOlderMessages;
  $("transcript-older").hidden = !state.olderMessagesCount;
  $("transcript-latest").hidden = !state.showingOlderMessages;
  renderJob();
  const connected=state.connection==="ready" && !state.codexRestarting;
  const local=state.provider==="ollama";
  const claude=state.provider==="claude";
  const openrouter=state.provider==="openrouter";
  const signed=!!state.account && (!(local || claude) || state.models.length>0);
  const hasMessages=state.messages.length>0 && signed;
  $("app").classList.toggle("signed-out",!signed);
  $("welcome").hidden=hasMessages || !!state.runtimeIssue;
  $("runtime-setup").hidden=!state.runtimeIssue;
  $("conversation").hidden=!hasMessages;
  $("sign-in-card").hidden=signed;
  $("login").disabled=!connected || !state.accountChecked || state.loginPending;
  const grok=state.provider==="grok";
  const providerName=local?"Ollama":grok?"Grok / X":claude?"Claude":openrouter?"OpenRouter":"ChatGPT";
  for(const id of ["provider","welcome-provider"]){$(id).value=state.provider||"chatgpt";$(id).disabled=!!state.busy || !!state.jobBusy || !!state.loginPending || state.connection==="starting";}
  $("login").textContent=claude?(!state.accountChecked?"Checking Claude Code…":"Check connection"):local?(!state.accountChecked?"Checking Ollama…":"Refresh models"):state.loginPending?"Signing in…":!state.accountChecked?"Checking your account…":grok?"Sign in with X / Grok ↗":openrouter?"Sign in with OpenRouter ↗":"Sign in with ChatGPT ↗";
  $("sign-in-heading").textContent=local?"Your tools. Your local model.":"Your tools. Your AI.";
  $("sign-in-description").textContent=claude?(state.localStatus||"Sign in to Claude Code outside Fusion, then check the connection here."):local?(state.localStatus||"Start Ollama and choose a downloaded model. No sign-in needed."):"Connect your account and bring your thinking partner into Fusion.";
  $("sign-in-note").textContent=claude?"Experimental · Uses the account signed into Claude Code and its subscription limits. Web search is unavailable.":local?"Runs on this computer. Choose a model with tool support and at least 8K context. Web search is unavailable.":grok?"Uses your xAI account’s Grok access. Link your X account at grok.com if needed.":openrouter?"Experimental · Pay per use with your OpenRouter credits. Tool-calling quality varies by model. Web search is unavailable.":"Uses your subscription's Codex access";
  $("claude-controls").hidden=!claude;
  $("claude-version").textContent=state.providerVersion?`Claude Code ${state.providerVersion}`:"Claude Code · Version unavailable";
  $("claude-links").hidden=!claude;
  $("openrouter-links").hidden=!openrouter;
  $("openrouter-controls").hidden=!openrouter || !signed;
  $("openrouter-refresh").disabled=state.busy || !!state.jobBusy || !connected;
  $("claude-refresh").disabled=state.busy || !connected;
  $("local-controls").hidden=!local;
  $("local-links").hidden=!local;
  $("local-status").textContent=state.localStatus||"Checking local Ollama…";
  $("local-refresh").disabled=state.busy || !connected;
  syncOllamaServer();
  $("login-wait").hidden=!state.loginPending;
  $("grok-login-note").hidden=!grok || signed || !state.loginPending || !!state.device;
  $("device-login").hidden=local || claude || openrouter || state.loginPending;
  $("device-login").disabled=!connected || !state.accountChecked;
  $("cancel-login").hidden=!state.loginPending;
  $("refresh-account").hidden=!state.loginPending;
  $("device-info").hidden=!state.device;
  $("device-code").textContent=state.device?.code||"";
  const restartingForUpdate=!!state.updateInstalling || !!state.updateInstallReady;
  $("dream-entry").hidden=!signed || (state.provider||"chatgpt")!=="chatgpt";
  $("dream").disabled=!canUseConcept("refine");
  $("composer-plus").disabled=!signed || !connected || restartingForUpdate;
  $("message").disabled=!signed || !connected || restartingForUpdate;
  $("message").placeholder=signed?(state.busy?"Add a correction or steer STEVE…":"What are you working on?"):local?"Connect a local model to begin":"Sign in to start a conversation";
  const jobCommand = /^\/jobs(?:\s|$)/.test($("message").value.trim());
  $("send").disabled=!signed || !connected || (!$("message").value.trim() && !draftImages.length) || draftImages.some(item=>!item.url) || !!clipboardRequest || submitting || (state.busy && !state.canSteer && !jobCommand) || !!state.jobBusy;
  const selectedModel=state.models.find(m=>m.id===state.model) || state.models.find(m=>m.isDefault);
  $("attach-images").disabled=!signed || !connected || draftImages.length>=4 || ((local || openrouter) && selectedModel?.supportsImages===false);
  if(restartingForUpdate){$("send").disabled=true;$("attach-images").disabled=true;}
  $("send").hidden=false;
  $("send").title=jobCommand?"Manage job":state.busy?"Steer current response":"Send message";
  $("send").setAttribute("aria-label",$("send").title);
  $("stop").hidden=!state.busy && !state.jobBusy;
  $("stop").disabled=state.status==="Opening conversation";
  $("new-chat").disabled=state.busy || !!state.jobBusy || !hasMessages;
  $("model").disabled=!signed || state.busy || !!state.jobBusy;
  $("effort").disabled=!signed || state.busy || !!state.jobBusy || !(state.effortOptions||[]).length;
  $("logout").hidden=local || claude || !signed;
  $("logout").disabled=state.busy || !!state.jobBusy;
  $("chatgpt-refresh").hidden=local || grok || claude || openrouter;
  $("chatgpt-refresh").disabled=state.busy || !!state.jobBusy || !connected;
  $("codex-version").textContent=state.codexVersion?`Codex ${state.codexVersion}`:"Codex runtime";
  $("codex-update-status").textContent=state.codexPendingVersion?`Codex ${state.codexPendingVersion} is ready. Restart STEVE to use it and refresh models.`:state.codexUpdateStatus||"Checks OpenAI for updates automatically.";
  $("check-codex-updates").disabled=!!state.codexUpdateChecking || !!state.codexUpdating;
  $("check-codex-updates").textContent=state.codexUpdateChecking?"Checking…":"Check Codex updates";
  $("update-codex").hidden=!state.codexUpdateInfo || !!state.codexPendingVersion;
  $("update-codex").disabled=!!state.codexUpdating;
  $("update-codex").textContent=state.codexUpdating?"Updating Codex…":state.codexUpdateInfo?`Update Codex to ${state.codexUpdateInfo.version}`:"Update Codex";
  $("bundled-codex").hidden=!state.codexManaged && !state.codexPendingVersion && !state.runtimeIssue;
  $("bundled-codex").disabled=!!state.codexUpdating;
  $("restart-steve").disabled=!!state.busy || !!state.jobBusy || !!state.loginPending || !!state.codexUpdating || !!state.codexRestarting || state.connection==="starting";
  $("restart-steve").textContent=state.codexRestarting?"Restarting STEVE…":"Restart STEVE";
  $("restart-steve").title=state.busy || state.jobBusy?"Finish or pause the current task before restarting":"Restart STEVE's conversation engine and reopen this chat";
  $("debug-logging").checked=!!state.debugLogging;
  $("dfm-enabled").checked=!!state.dfmEnabled;
  $("dfm-enabled").disabled=!!state.busy || !!state.jobBusy || state.job?.status==="active";
  $("dfm-chip").hidden=!signed || !state.dfmEnabled;
  $("rmfg-settings").hidden=!state.dfmEnabled;
  $("rmfg-status").textContent=state.rmfgError || ({connected:"Connected to RMFG",authorizing:"Approve the connection in your browser.",reconnect:"Reconnect RMFG to continue.",unchecked:"Check your saved connection or connect RMFG."}[state.rmfgState] || "Not connected");
  $("rmfg-code").hidden=!state.rmfgCode;
  $("rmfg-code").textContent=state.rmfgCode ? "Browser approval code: "+state.rmfgCode : "";
  $("rmfg-connect").hidden=state.rmfgState==="connected" || !!state.rmfgBusy;
  $("rmfg-enable-checkout").hidden=state.rmfgState!=="connected" || !!state.rmfgCheckoutEnabled;
  $("rmfg-enable-checkout").disabled=!!state.rmfgBusy;
  $("rmfg-checkout").hidden=!state.rmfgCheckout || state.rmfgCheckout.threadId!==state.threadId;
  $("rmfg-open-checkout").disabled=!!state.rmfgCheckoutOpening;
  $("rmfg-refresh").disabled=!!state.rmfgBusy;
  $("rmfg-cancel").hidden=state.rmfgState!=="authorizing" || !state.rmfgBusy;
  $("rmfg-disconnect").hidden=state.rmfgState!=="connected";
  $("rmfg-disconnect").disabled=!!state.rmfgBusy;
  $("open-logs").title=state.debugLogPath || "Open local debug logs";
  $("release-notice").hidden=!state.releaseNotes || !state.releaseNotesUnread;
  $("release-notice-title").textContent=state.releaseNotes?`New in STEVE ${state.releaseNotes.version}`:"";
  $("installed-release-notes").hidden=!state.releaseNotes;
  const update=state.updateInfo;
  $("installed-version").textContent=state.version?`STEVE ${state.version}`:"STEVE";
  $("app-version").textContent=state.version?`v${state.version}`:"";
  $("updates-badge").hidden=!update && !state.codexUpdateInfo && !state.codexPendingVersion;
  $("settings-dot").hidden=$("updates-badge").hidden;
  $("updates-badge").textContent=state.codexPendingVersion?"Restart ready":"Available";
  $("update-status").textContent=state.updateInstallFailure||state.updateStatus||"Checks for new releases automatically.";
  $("check-updates").disabled=!!state.updateChecking;
  $("check-updates").textContent=state.updateChecking?"Checking…":"Check for updates";
  $("menu-update").hidden=!update;
  $("update-banner").hidden=!update || dismissedUpdate===update.version;
  $("update-title").textContent=update?`STEVE ${update.version} is available`:"";
  const download=state.updateDownload;
  const downloading=download?.state==="downloading";
  const downloaded=download?.state==="ready" && download.version===update?.version;
  const updateBlocker=state.job?.status==="active"?"Pause or finish the current job before updating STEVE. Fusion can stay open.":
    state.jobBusy?"Wait for the job operation to finish before updating STEVE. Fusion can stay open.":
    state.busy?"STEVE is still working. Let the current task finish before updating. Fusion can stay open.":
    state.loginPending?"Finish or cancel sign-in before updating STEVE.":
    state.codexUpdating?"Wait for the Codex update to finish before updating STEVE.":"";
  for(const id of ["update-steve-now","menu-update-now"]){$(id).hidden=!update || !!state.updateInstallReady;$(id).disabled=downloading || !!state.autoInstallVersion || !!state.updateInstalling || !!updateBlocker;$(id).title=updateBlocker;$(id).textContent=state.autoInstallVersion?"Downloading update…":state.updateInstalling?"Preparing update…":"Update & restart STEVE";}
  const downloadLabel=downloading?`Downloading${download.percent==null?"…":` ${download.percent}%`}`:downloaded?"Open Downloads":"Download only";
  for(const id of ["download-update","menu-download"]){$(id).textContent=downloadLabel;$(id).disabled=downloading;}
  $("menu-download").hidden=!update;
  const downloadNote=state.updateInstallFailure|| (state.updateInstallReady?state.updateStatus:state.updateInstalling?"Preparing to restart STEVE… Fusion and your documents will stay open.":state.updateStatus?.startsWith("Couldn’t prepare installation")?state.updateStatus:download?.state==="error"?download.message:state.autoInstallVersion?"Downloading and verifying the update. Fusion stays open.":updateBlocker?updateBlocker:downloaded?"Update downloaded and verified. Update & restart STEVE when you’re ready; Fusion stays open.":"Managed installations download updates automatically. You choose when to restart STEVE.");
  $("download-status").hidden=!download;
  $("download-status").textContent=downloadNote;
  $("update-hint").textContent=downloadNote;
  $("account-email").textContent=local?"Local Ollama":state.account?.email || (signed?`${providerName} account`:"Not signed in");
  const ollamaAddress=state.ollamaAddress||"127.0.0.1:11434";
  $("account-plan").textContent=local?`${ollamaAddress} · ${state.ollamaApiKeySet?"API key saved":"No sign-in needed"}`:signed?`${state.account.planType||providerName} · Connected`:`Use your ${providerName} account`;
  // Settings rows summarize each page so the list doubles as a status check.
  $("row-account-value").textContent=local?`Ollama · ${ollamaAddress}`:`${providerName} · ${signed?(state.account?.email||"Connected"):"Not signed in"}`;
  const rmfgSummary={connected:"RMFG connected",authorizing:"RMFG connecting",reconnect:"RMFG needs reconnect"}[state.rmfgState]||"RMFG not connected";
  $("row-manufacturing-value").textContent=`DFM ${state.dfmEnabled?"on":"off"}${state.dfmEnabled?` · ${rmfgSummary}`:""}`;
  $("rmfg-badge").hidden=!state.dfmEnabled || state.rmfgState!=="reconnect";
  $("row-updates-value").textContent=update?`STEVE ${update.version} is available`:state.codexPendingVersion?`Codex ${state.codexPendingVersion} ready · restart to use it`:`${state.version?`STEVE ${state.version}`:"STEVE"}${state.codexVersion?` · Codex ${state.codexVersion}`:""}`;
  $("row-diagnostics-value").textContent=`Debug logging ${state.debugLogging?"on":"off"}`;
  $("settings-version").textContent=`${state.version?`STEVE v${state.version}`:"STEVE"}${state.codexVersion?` · Codex ${state.codexVersion}`:""}`;
  // One status line: the footer names what STEVE is doing and which tool it is using.
  const tools=state.busy && signed && state.connection==="ready" ? state.activeTools||[] : [];
  const tool=tools[0];
  const toolLabel=tool?`${tool.name==="fusion_api_help"?"Reading docs · ":""}${tool.title}${tools.length>1?` · +${tools.length-1} more`:""}`:"";
  const statusText=clipboardRequest?"Reading clipboard image…":state.waitingForFusion?state.waitingReason:tool?`${state.status} · ${toolLabel}`:state.status;
  if($("status").textContent!==statusText) $("status").textContent=statusText;
  $("status").title=tools.map(t=>`${t.name}: ${t.title}`).join("\n");
  $("task-target").hidden=!signed || !state.busy || !state.taskDocument;
  $("task-target-label").textContent=state.taskDocument?(state.taskDocument.name||"No document"):"";
  $("task-target-meta").textContent=state.taskDocument?(state.waitingForFusion?"Waiting":"Pinned"):"";
  $("task-target").title="This task keeps its original document and selection. It waits when another document or command is active.";
  $("preference-notice").hidden=!signed || !state.preferenceNotice;
  $("preference-notice").textContent=state.preferenceNotice||"";
  $("status-dot").className="status-dot"+(state.busy?(state.waitingForFusion?" waiting":" busy"):signed&&connected?" ready":"");
  $("error").hidden=!state.error || state.error===dismissedError;
  $("error-text").textContent=state.error;
  $("reconnect-row").hidden=state.connection!=="disconnected";
  const modelsJSON=JSON.stringify([state.provider,state.models]);
  if(modelsJSON!==renderedModels){
    $("model").replaceChildren(new Option(local?"Local default":openrouter?"Most popular":"Account default",""));
    const groups=new Map();
    state.models.forEach((model)=>{
      const option=new Option(model.name,model.id);
      if(!model.group){$("model").add(option);return;}
      if(!groups.has(model.group)){const group=document.createElement("optgroup");group.label=model.group;groups.set(model.group,group);$("model").append(group);}
      groups.get(model.group).append(option);
    });
    renderedModels=modelsJSON;
  }
  $("model").value=state.model;
  $("model").title=selectedModel?.name?`Model · ${selectedModel.name}`:"Model";
  const efforts=state.effortOptions||[];
  const effortsJSON=JSON.stringify([efforts,state.defaultEffort]);
  if(effortsJSON!==renderedEfforts){
    const labels={none:"None",minimal:"Minimal",low:"Low",medium:"Medium",high:"High",xhigh:"Extra high",max:"Max",ultra:"Ultra"};
    $("effort").replaceChildren(new Option(state.defaultEffort?`Default (${labels[state.defaultEffort]||state.defaultEffort})`:"Default",""));
    efforts.forEach((effort)=>{const option=new Option(labels[effort.id]||effort.id,effort.id);option.title=effort.description;$("effort").add(option);});
    renderedEfforts=effortsJSON;
  }
  $("effort").value=state.effort||"";
  // The transcript already shows progress for a running step or a concept placeholder.
  const runningStep=state.messages.some(m=>m.role==="tool" && m.toolStatus==="running");
  const conceptPending=state.messages[state.messages.length-1]?.conceptStatus==="running";
  $("thinking").hidden=!state.busy || !signed || state.status==="Writing" || state.waitingForFusion || runningStep || conceptPending;
  $("thinking-label").textContent=tool?toolLabel:state.status;
  $("history-button").disabled=!signed || !connected || state.busy;
  if(!signed)showHistory(false);
  renderHistory();
}

// Settings is a short list of categories; each row opens its own page and Back returns to the list.
const SETTINGS_PAGES={account:"AI provider",manufacturing:"Manufacturing",updates:"Updates",diagnostics:"Diagnostics"};
let settingsPage="root";
function focusFirst(container) {
  if(!container?.querySelectorAll)return;
  Array.from(container.querySelectorAll("select:not(:disabled), input:not(:disabled), button:not(:disabled), [tabindex]")).find(element=>element.getClientRects().length)?.focus();
}
function showSettingsPage(page, focus = false) {
  settingsPage=SETTINGS_PAGES[page]?page:"root";
  $("app-menu").dataset.page=settingsPage;
  $("settings-root").hidden=settingsPage!=="root";
  for(const id of Object.keys(SETTINGS_PAGES))$("settings-"+id).hidden=id!==settingsPage;
  $("settings-back").hidden=settingsPage==="root";
  $("settings-title").textContent=settingsPage==="root"?"Settings":SETTINGS_PAGES[settingsPage];
  const body=$("app-menu").querySelector?.(".panel-body");
  if(body)body.scrollTop=0;
  if(focus)focusFirst(settingsPage==="root"?$("settings-root"):$("settings-"+settingsPage));
}
function settingsBack(focus = true) {
  const page=settingsPage;
  showSettingsPage("root",false);
  if(focus)($("settings-root").querySelector?.(`[data-page="${page}"]`)||$("settings-root")).focus?.();
}
function showSettings(open, focus = false, page = "root") {
  if(open)showHistory(false);
  $("app-menu").hidden=!open;
  $("app-menu-button").setAttribute("aria-expanded",String(open));
  if(open)showSettingsPage(page,focus);
  else if(focus)$("app-menu-button").focus();
}
function showHistory(open) {
  $("history-panel").hidden=!open;
  $("history-button").setAttribute("aria-expanded",String(open));
  if(open){showSettings(false);$("history-search").focus();}
}
function showPlusMenu(open, focus = false) {
  $("plus-menu").hidden=!open;
  $("composer-plus").setAttribute("aria-expanded",String(open));
  if(focus){
    if(open)Array.from($("plus-menu").querySelectorAll("button:not(:disabled)")).find(element=>element.getClientRects().length)?.focus();
    else $("composer-plus").focus();
  }
}
function renderHistory() {
  const query=$("history-search").value.trim().toLocaleLowerCase();
  const history=state.history||[];
  const signature=JSON.stringify([history,query,state.threadId,state.historyLoading,state.busy,state.historyCursor]);
  if(signature===renderedHistory)return;
  renderedHistory=signature;
  const entries=history.filter(entry=>entry.title.toLocaleLowerCase().includes(query));
  $("history-list").replaceChildren(...entries.map(entry=>{
    const button=document.createElement("button");button.className="history-entry";
    button.disabled=state.busy||state.historyLoading;
    button.setAttribute("aria-current",String(entry.id===state.threadId));
    const title=document.createElement("strong");title.textContent=entry.title;
    const date=document.createElement("small");date.textContent=entry.updatedAt?new Date(entry.updatedAt*1000).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"Saved conversation";
    button.append(title,date);
    button.onclick=()=>{showHistory(false);act("openHistory",{threadId:entry.id});};
    return button;
  }));
  $("history-empty").hidden=entries.length>0;
  $("history-empty").textContent=state.historyLoading?"Loading conversations…":query?"No matching conversations in the loaded history.":"Your conversations will appear here after your first message.";
  $("history-more").hidden=!state.historyCursor;
  $("history-more").disabled=state.historyLoading||state.busy;
}

window.fusionJavaScriptHandler={handle(action,data){
  if(action==="gallery"){
    try{SteveGallery.receive(JSON.parse(data));}catch(error){return "FAILED";}
  }
  if(action==="clipboardImage"){
    try{finishClipboardImage(JSON.parse(data));}catch(error){return "FAILED";}
  }
  if(action==="state"){
    try{state=JSON.parse(data);scheduleRender();}catch(error){return "FAILED";}
  }
  return "OK";
}};

function renderJob() {
  const job = state.job;
  const labels = {active:"Working", paused:"Paused", blocked:"Blocked", budgetLimited:"Token limit reached", usageLimited:"Usage limit reached", complete:"Complete"};
  const label = job ? labels[job.status] || job.status : "No job yet";
  $("job-strip").hidden = !job;
  $("job-strip-title").textContent = job?.objective || "";
  $("job-strip-status").textContent = label;
  $("job-button-label").textContent = job ? "Manage job" : "Start a job";
  $("job-summary").textContent = job ? `${label} · ${job.objective}` : state.jobNotice || "Set an objective with a clear stopping point.";
  $("job-usage").textContent = job ? `${Number(job.tokensUsed || 0).toLocaleString()}${job.tokenBudget == null ? "" : ` / ${Number(job.tokenBudget).toLocaleString()}`} tokens · ${Math.floor((job.timeUsedSeconds || 0) / 60)} min` : "";
  $("job-target-note").textContent = job && state.jobHasTarget ? "Resuming keeps this job’s original document and selection." : "Starting or resuming uses the active Fusion document. Open the intended document first.";
  const unavailable = !state.account || state.connection !== "ready" || !!state.jobBusy;
  $("job-button").disabled = unavailable;
  $("job-pause").hidden = !job || job.status !== "active";
  $("job-pause").disabled = unavailable;
  $("job-resume").hidden = !job || job.status === "active" || job.status === "complete";
  $("job-resume").disabled = unavailable || !!state.jobResumePending;
  $("job-resume").title = state.busy ? "Continue this job after the current work finishes, without interrupting it." : "";
  $("job-wait-note").hidden = !job || job.status === "active" || job.status === "complete" || !state.busy;
  $("job-wait-note").textContent = state.jobResumePending ? "Resume requested. The job will continue on its original document after the current work finishes." : "You can resume now. The current work will finish before the job continues.";
  $("job-resume").textContent = state.jobResumePending ? "Resume requested" : job?.status === "budgetLimited" ? "Resume with budget below" : "Resume";
  $("job-clear").hidden = !job;
  $("job-clear").disabled = unavailable;
  $("job-save").disabled = unavailable || !!state.busy;
  $("job-save").textContent = job ? "Save and start" : "Start job";
}

function syncOllamaServer() {
  const locked=!!state.busy || !!state.jobBusy || state.job?.status==="active" || state.connection==="starting" || !!state.codexRestarting;
  $("ollama-server").disabled=locked;
  $("ollama-server-welcome").disabled=locked;
  $("ollama-save").disabled=locked;
  $("ollama-clear-row").hidden=!state.ollamaApiKeySet;
  $("ollama-key-note").textContent=state.ollamaApiKeySet?"A key is saved on this computer. Leave the field blank to keep it, or remove it.":"Leave the key blank unless this server requires one.";
  $("ollama-server").title=state.ollamaAddress?`Ollama server ${state.ollamaAddress}`:"Ollama host, port, and optional API key";
}

function readOllamaForm() {
  const host=String($("ollama-host").value||"").trim();
  const portText=String($("ollama-port").value??"").trim();
  const url=String($("ollama-url").value||"").trim();
  if(!host || /\s|[/\\]/.test(host) || host.includes("://")) throw new Error("Enter a host name or IP address, and put the port in the port field.");
  if(url.includes("://") || /\s/.test(url)) throw new Error("Enter a path or query, such as /ollama or ?think=false. Host and port stay in their own fields.");
  if(url && !url.startsWith("/") && !url.startsWith("?")) throw new Error("Start the URL path with / or ?, such as /ollama or ?think=false.");
  let port=null;
  if(portText){
    if(!/^[0-9]+$/.test(portText) || Number(portText)<1 || Number(portText)>65535) throw new Error("Enter a port from 1 to 65535, or leave it blank for 11434.");
    port=Number(portText);
  }
  const payload={host, port, url, clearApiKey:!!$("ollama-clear-key").checked};
  const apiKey=$("ollama-key").value;
  if(!payload.clearApiKey && apiKey) payload.apiKey=apiKey;
  return payload;
}

function openOllamaServer() {
  showSettings(false);
  $("ollama-host").value=state.ollamaHost||"127.0.0.1";
  $("ollama-port").value=state.ollamaPort?String(state.ollamaPort):"";
  $("ollama-url").value=state.ollamaUrl||"";
  $("ollama-key").value="";
  $("ollama-clear-key").checked=false;
  syncOllamaServer();
  const dialog=$("ollama-dialog");
  if(!dialog.open && typeof dialog.showModal==="function") dialog.showModal();
  if(typeof $("ollama-host").focus==="function") $("ollama-host").focus();
}

function openJob(edit = false) {
  $("job-objective").value = state.job?.objective || "";
  $("job-budget").value = state.job?.tokenBudget ?? "";
  renderJob();
  if (!$("job-dialog").open) $("job-dialog").showModal();
  if (edit || !state.job) $("job-objective").focus();
  act("job", {command:"status"});
}

function jobBudget() {
  const value = $("job-budget").value.trim();
  const budget = value ? Number(value) : null;
  if (budget !== null && (!Number.isSafeInteger(budget) || budget <= 0)) throw new Error("Enter a positive whole token budget, or leave it blank.");
  return budget;
}

async function copyCode(button) {
  const code = button.closest(".code-block, .step-body")?.querySelector("code");
  if (!code) return;
  let copied = false;
  try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(code.textContent); copied = true; } } catch (error) { copied = false; }
  if (!copied) {
    try {
      const range = document.createRange(); range.selectNodeContents(code);
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
      copied = document.execCommand("copy"); selection.removeAllRanges();
    } catch (error) { copied = false; }
  }
  button.textContent = copied ? "Copied" : "Copy failed";
  if (copied) button.dataset.copied = "true";
  clearTimeout(button.resetTimer);
  button.resetTimer = setTimeout(() => { button.textContent = "Copy"; delete button.dataset.copied; }, 1600);
}

$("login").onclick=()=>state.provider==="ollama"?act("accountRefresh",{refreshModels:true}):act("login");
$("dream").onclick=()=>{showPlusMenu(false);dreamDraft();};
$("claude-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("chatgpt-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("check-codex-updates").onclick=()=>act("checkCodexUpdates");
$("update-codex").onclick=()=>act("updateCodex");
$("bundled-codex").onclick=()=>act("useBundledCodex");
$("restart-steve").onclick=()=>act("restartRuntime");
$("install-claude").onclick=()=>act("setupHelp",{page:"claude"});
$("openrouter-keys").onclick=$("openrouter-credits").onclick=()=>act("setupHelp",{page:"openrouter"});
$("openrouter-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("job-button").onclick=()=>{showPlusMenu(false);openJob();};
$("job-strip").onclick=()=>openJob();
$("job-close").onclick=()=>$("job-dialog").close();
$("job-pause").onclick=()=>act("job",{command:"pause"});
$("transcript-older").onclick=()=>act("transcriptPage",{threadId:state.threadId,provider:state.provider||"chatgpt",before:state.messageOffset});
$("transcript-latest").onclick=()=>act("transcriptPage",{threadId:state.threadId,provider:state.provider||"chatgpt"});
$("job-clear").onclick=()=>act("job",{command:"clear"});
$("job-resume").onclick=()=>{
  try { act("job",{command:"resume",tokenBudget:jobBudget()}); $("job-dialog").close(); }
  catch(error) { state.error=error.message; $("job-dialog").close(); render(); }
};
$("job-form").onsubmit=(event)=>{
  event.preventDefault();
  try { act("job",{command:"set",objective:$("job-objective").value.trim(),tokenBudget:jobBudget()}); $("job-dialog").close(); }
  catch(error) { state.error=error.message; $("job-dialog").close(); render(); }
};
$("local-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("install-ollama").onclick=()=>act("setupHelp",{page:"ollama"});
$("local-help").onclick=$("local-setup").onclick=()=>act("setupHelp",{page:"local"});
$("ollama-server").onclick=$("ollama-server-welcome").onclick=()=>openOllamaServer();
$("ollama-close").onclick=()=>$("ollama-dialog").close();
$("ollama-form").onsubmit=(event)=>{
  event.preventDefault();
  let payload;
  try { payload=readOllamaForm(); }
  catch(error) { state.error=error.message; dismissedError=""; render(); return; }
  return bridge("ollamaServer", payload).then(()=>{
    $("ollama-key").value="";
    $("ollama-clear-key").checked=false;
    const dialog=$("ollama-dialog");
    if(typeof dialog.close==="function") dialog.close();
  }).catch((error)=>{ state.error=error.message; dismissedError=""; render(); });
};
$("device-login").onclick=()=>act("deviceLogin");
$("cancel-login").onclick=()=>act("cancelLogin");
$("refresh-account").onclick=()=>act("accountRefresh",{refreshToken:true});
$("logout").onclick=()=>{act("logout");showSettings(false,true);};
$("reconnect").onclick=()=>act("connect");
$("repair-steve").onclick=()=>act("setupHelp",{page:"steve"});
$("install-codex").onclick=()=>act("setupHelp",{page:"codex"});
$("debug-logging").onchange=(event)=>act("debugLogging",{enabled:event.target.checked});
$("dfm-enabled").onchange=(event)=>act("dfm",{enabled:event.target.checked});
$("rmfg-connect").onclick=()=>act("rmfgConnect");
$("rmfg-enable-checkout").onclick=()=>act("rmfgEnableCheckout");
$("rmfg-open-checkout").onclick=()=>state.rmfgCheckout && act("rmfgOpenCheckout",{checkoutId:state.rmfgCheckout.id});
$("rmfg-refresh").onclick=()=>act("rmfgRefresh");
$("rmfg-disconnect").onclick=()=>act("rmfgDisconnect");
$("rmfg-cancel").onclick=()=>act("rmfgCancel");
$("open-logs").onclick=()=>act("openLogs");
$("check-updates").onclick=()=>{dismissedUpdate="";act("checkUpdates");};
$("menu-update").onclick=()=>act("openUpdate",{page:"notes"});
$("download-update").onclick=()=>act(state.updateDownload?.state==="ready" && state.updateDownload.version===state.updateInfo?.version?"openDownloads":"downloadUpdate");
$("menu-download").onclick=$("download-update").onclick;
function openReleaseNotes(){
  const notes=state.releaseNotes;if(!notes)return;
  $("release-notes-heading").textContent=`STEVE ${notes.version} — ${notes.title}`;
  $("release-notes-items").replaceChildren(...notes.items.map(text=>{const item=document.createElement("li");item.textContent=text;return item;}));
  $("release-notes-note").textContent=notes.note||"";
  $("release-notes-dialog").showModal();
  act("acknowledgeReleaseNotes",{version:notes.version});
}
$("show-release-notes").onclick=openReleaseNotes;
$("installed-release-notes").onclick=openReleaseNotes;
$("dismiss-release-notes").onclick=()=>{if(state.releaseNotes)act("acknowledgeReleaseNotes",{version:state.releaseNotes.version});};
$("close-release-notes").onclick=()=>$("release-notes-dialog").close();
$("update-steve-now").onclick=()=>$("update-confirm").showModal();
$("menu-update-now").onclick=$("update-steve-now").onclick;
$("confirm-update").onclick=()=>{
  $("update-confirm").close();
  if($("message").value.trim() || draftImages.length || clipboardRequest || submitting){
    state.error="Send or clear your draft before restarting STEVE. Your update is ready when you are.";dismissedError="";render();return;
  }
  act("updateSteve");
};
$("cancel-update").onclick=()=>$("update-confirm").close();
$("update-notes").onclick=()=>act("openUpdate",{page:"notes"});
$("dismiss-update").onclick=()=>{dismissedUpdate=state.updateInfo?.version||"";renderedControls="";render();};
$("new-chat").onclick=()=>{showHistory(false);act("new");};
$("history-button").onclick=()=>{const open=$("history-panel").hidden;showHistory(open);if(open){renderHistory();act("history");}};
$("history-close").onclick=()=>{showHistory(false);$("history-button").focus();};
$("history-search").oninput=renderHistory;
$("history-more").onclick=()=>act("history",{more:true});
$("stop").onclick=()=>act("stop");
$("dismiss-error").onclick=()=>{dismissedError=state.error;render();};
$("model").onchange=(event)=>act("model",{model:event.target.value});
$("provider").onchange=(event)=>act("provider",{provider:event.target.value});
$("welcome-provider").onchange=$("provider").onchange;
$("effort").onchange=(event)=>act("effort",{effort:event.target.value});
$("app-menu-button").onclick=()=>showSettings($("app-menu").hidden,true);
$("settings-close").onclick=()=>showSettings(false,true);
$("settings-back").onclick=()=>settingsBack(true);
document.querySelectorAll(".settings-row").forEach((row)=>row.onclick=()=>showSettingsPage(row.dataset.page,true));
$("dfm-chip").onclick=()=>showSettings(true,true,"manufacturing");
$("composer-plus").onclick=()=>showPlusMenu($("plus-menu").hidden,true);
// Links open in the system browser through the bridge; the panel itself never navigates.
$("conversation").addEventListener("click",(event)=>{
  const link=event.target.closest("a[href]");
  if(link){event.preventDefault();act("openLink",{url:link.getAttribute("href")});return;}
  const copy=event.target.closest(".copy-code");
  if(copy)copyCode(copy);
});
// Returning from the external browser should immediately reveal a saved sign-in.
let lastAccountCheck=0;
function checkAccountOnReturn(){
  if(!preview && state.connection==="ready" && !state.busy && Date.now()-lastAccountCheck>1500){
    lastAccountCheck=Date.now();act("accountRefresh");
  }
}
window.addEventListener("focus",checkAccountOnReturn);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)checkAccountOnReturn();});
document.addEventListener("keydown",(event)=>{
  if(event.key!=="Escape")return;
  if(!$("plus-menu").hidden){showPlusMenu(false,true);return;}
  if(!$("app-menu").hidden){if(settingsPage!=="root")settingsBack(true);else showSettings(false,true);return;}
  if(!$("history-panel").hidden){showHistory(false);$("history-button").focus();}
});
document.addEventListener("click",(event)=>{
  if(!$("plus-menu").hidden && !event.target.closest("#plus-menu, #composer-plus"))showPlusMenu(false);
});
document.addEventListener("focusin",(event)=>{
  if(!$("plus-menu").hidden && !event.target.closest("#plus-menu, #composer-plus"))showPlusMenu(false);
});
document.querySelectorAll(".suggestion").forEach((button)=>button.onclick=()=>{
  if(!state.account){$("login").focus();return;}
  $("message").value=button.dataset.prompt;resize();$("message").focus();render();
});
function resize(){const input=$("message");input.style.height="auto";input.style.height=Math.min(input.scrollHeight,170)+"px";}
$("message").oninput=()=>{resize();render();};
$("message").onkeydown=(event)=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();$("composer").requestSubmit();}};
$("message").onpaste=(event)=>{
  if(event.isTrusted===false)return;
  const clipboard=event.clipboardData;
  const items=Array.from(clipboard?.items||[]);
  const hasImage=items.some(item=>item.kind==="file" && item.type.startsWith("image/"));
  const hasText=items.some(item=>item.kind==="string" && item.type==="text/plain") || Array.from(clipboard?.types||[]).includes("text/plain");
  if(hasText && !hasImage)return; // Text remains the browser's native paste operation.
  event.preventDefault();pasteClipboardImage();
};
$("attach-images").onclick=()=>{showPlusMenu(false);$("image-files").click();};
if(typeof navigator!=="undefined" && /Mac/.test(navigator.platform||""))$("attach-hint").textContent="PNG, JPEG or WebP · ⌘V pastes a screenshot";
$("image-files").onchange=(event)=>{const files=Array.from(event.target.files||[]);event.target.value="";attachImages(files);};
$("close-image").onclick=()=>$("image-viewer").close();
$("image-viewer").onclick=(event)=>{if(event.target===$("image-viewer"))$("image-viewer").close();};
$("image-viewer").onclose=()=>$("expanded-image").removeAttribute("src");
$("composer").onsubmit=async(event)=>{
  event.preventDefault();const text=$("message").value.trim();
  const jobCommand=/^\/jobs(?:\s|$)/.test(text);
  if((!text&&!draftImages.length)||draftImages.some(item=>!item.url)||clipboardRequest||(state.busy&&!state.canSteer&&!jobCommand)||submitting||state.jobBusy||!state.account||state.connection!=="ready")return;
  if(/^\/jobs(?:\s+(?:edit|status|help))?$/.test(text) && !draftImages.length){$("message").value="";resize();openJob(text.endsWith("edit"));return;}
  const sentImages=draftImages.slice();const draftText=$("message").value;
  dismissedError="";submitting=true;render();
  try{
    await bridge(state.busy?"steer":"send",{text,images:sentImages.map(({name,url})=>({name,url})),threadId:state.threadId,turnId:state.turnId});
    if($("message").value===draftText)$("message").value="";
    draftImages=draftImages.filter(item=>!sentImages.includes(item));draftImageRevision++;renderDraftImages();resize();
  }
  catch(error){state.error=error.message;}
  submitting=false;render();
};

// Explicit design preview. No account connection or AI calls are made in this mode.
let previewTimer;
function previewAction(action,payload){
  if(action==="login"||action==="deviceLogin"){
    state.account={email:"designer@example.com",planType:"Plus"};state.status="Ready";
    state.models=[{id:"preview-model",name:"Preview model"}];
  }else if(action==="logout"){state.account=null;state.messages=[];state.status="Sign in to begin";}
  else if(action==="new"){state.messages=[];state.status="Ready";}
  else if(action==="model"){state.model=payload.model;}
  else if(action==="effort"){state.effort=payload.effort;}
  else if(action==="debugLogging"){state.debugLogging=payload.enabled;}
  else if(action==="dfm"){state.dfmEnabled=payload.enabled;}
  else if(action==="send"){
    state.messages.push({role:"user",text:payload.text});state.busy=true;state.status="Thinking";
    previewTimer=setTimeout(()=>{state.messages.push({role:"assistant",text:"Start with the **design intent**: what should stay fixed, and what should be easy to change?\n\nFor a mounting bracket, I'd define three parameters first:\n\n1. **Plate thickness** — driven by material and load.\n2. **Hole spacing** — matched to the parts it connects.\n3. **Bend height** — enough clearance for assembly.\n\nThen build a fully constrained sketch around the origin.\n\nWhat will your bracket attach to?"});state.busy=false;state.status="Ready";render();},900);
  }else if(action==="stop"){clearTimeout(previewTimer);state.busy=false;state.status="Stopped";}
  render();
}
async function initialize(){
  render();
  if(preview){
    $("preview-banner").hidden=false;state.connection="ready";state.accountChecked=true;state.status="Sign in to begin";
    if(preview==="chat"){previewAction("login",{});previewAction("send",{text:"I'm designing a mounting bracket. Where should I start?"});}
    render();return;
  }
  for(let attempt=0;attempt<50;attempt++){
    if(window.adsk?.fusionSendData){await act("sync");return;}
    await new Promise((resolve)=>setTimeout(resolve,100));
  }
  state.connection="disconnected";state.status="Fusion connection unavailable";
  state.error="Open STEVE from the Fusion toolbar. This panel connects through the Fusion add-in.";render();
}
initialize();

SteveGallery.init({bridge,openImage,
  beforeOpen:()=>{showSettings(false);showHistory(false);showPlusMenu(false);},
  context:()=>JSON.stringify([state.provider,state.threadId,draftImageRevision]),
  canAttach:()=>!!state.account && state.connection==='ready' && !submitting && !clipboardRequest &&
    !state.updateInstalling && !state.updateInstallReady && draftImages.length<4 &&
    state.models?.find(model=>model.id===state.model)?.supportsImages!==false,
  attach:file=>attachImages([file])
});
