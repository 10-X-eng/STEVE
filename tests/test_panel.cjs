// Exercise the production text renderer without a browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../addin/STEVE/panel/panel.js'), 'utf8');
const context = {URL, URLSearchParams, location:{search:''}, document:{getElementById:()=>null}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../addin/STEVE/panel/markdown.js'), 'utf8'), context);
vm.runInContext(source.slice(0, source.indexOf('async function bridge')), context);
const render = context.markdown;
const strip = html => html.replace(/<[^>]+>/g, '');
assert.equal(render('<img src=x onerror=alert(1)>'), '<p>&lt;img src=x onerror=alert(1)&gt;</p>');
assert.equal(render('`<script>alert(1)</script>`'), '<p><code>&lt;script&gt;alert(1)&lt;/script&gt;</code></p>');
const fence = render('```python\nprint("<hello>")');
assert.match(fence, /^<div class="code-block"><div class="code-tools"><span class="code-lang">Python<\/span><button type="button" class="copy-code">Copy<\/button><\/div><pre><code>/);
assert.equal(strip(fence.slice(fence.indexOf('<pre>'))), 'print(&quot;&lt;hello&gt;&quot;)');
assert.doesNotMatch(fence, /<script/);
assert.equal(render('- First\n- Second\n\nThen continue.'), '<ul><li>First</li><li>Second</li></ul><p>Then continue.</p>');
assert.equal(render('1. First\n2. Second'), '<ol><li>First</li><li>Second</li></ol>');
assert.equal(render('- Outer\n  - Inner one\n  - Inner two\n- Next'), '<ul><li>Outer<ul><li>Inner one</li><li>Inner two</li></ul></li><li>Next</li></ul>');
assert.equal(render('**Important** and *helpful*'), '<p><strong>Important</strong> and <em>helpful</em></p>');
assert.equal(render('`**literal**`'), '<p><code>**literal**</code></p>');
assert.equal(render('## Next step\n\n> A quote'), '<h3>Next step</h3><blockquote><p>A quote</p></blockquote>');
assert.equal(render('| Name | Value |\n| --- | ---: |\n| `plate_w` | 60 mm |'),
  '<div class="table-wrap"><table><thead><tr><th>Name</th><th style="text-align:right">Value</th></tr></thead><tbody><tr><td><code>plate_w</code></td><td style="text-align:right">60 mm</td></tr></tbody></table></div>');
assert.equal(render('See [docs](https://help.autodesk.com/a?b=1 "t") and [x](javascript:alert(1)) or https://example.com/p.'),
  '<p>See <a href="https://help.autodesk.com/a?b=1">docs</a> and [x](javascript:alert(1)) or <a href="https://example.com/p">https://example.com/p</a>.</p>');
assert.equal(render('[evil](https://example.com/"onclick="alert(1))'), '<p>[evil](https://example.com/&quot;onclick=&quot;alert(1))</p>');
const highlighted = render('```python\ndef run(context):\n    return {"n": 0x1F}  # <b>\n```');
assert.match(highlighted, /<span class="tok-kw">def<\/span> <span class="tok-fn">run<\/span>/);
assert.match(highlighted, /<span class="tok-cm"># &lt;b&gt;<\/span>/);
assert.equal(strip(highlighted.slice(highlighted.indexOf('<pre>'))), 'def run(context):\n    return {&quot;n&quot;: 0x1F}  # &lt;b&gt;');
console.log('Panel rendering checks passed: escaping, fences, highlighting, lists, tables and safe links.');

// Test the incremental updater using a minimal DOM tree, without starting a browser.
class TreeNode {
  constructor(name, ...children) {
    this.nodeName = name;
    this.nodeType = name === '#text' ? 3 : 1;
    this.childNodes = [];
    if (this.nodeType === 3) this.data = children[0];
    else children.forEach(child => this.appendChild(child));
  }
  get length() { return this.data.length; }
  get lastChild() { return this.childNodes.at(-1); }
  appendChild(child) { child.remove(); this.childNodes.push(child); child.parent = this; }
  replaceChild(next, previous) {
    next.remove(); this.childNodes[this.childNodes.indexOf(previous)] = next;
    next.parent = this; previous.parent = null;
  }
  remove() {
    if (this.parent) this.parent.childNodes.splice(this.parent.childNodes.indexOf(this), 1);
    this.parent = null;
  }
  appendData(data) { this.data += data; }
  replaceData(start, count, data) { this.data = this.data.slice(0, start) + data + this.data.slice(start + count); }
}
const text = value => new TreeNode('#text', value);
const tree = (name, ...children) => new TreeNode(name, ...children);
const frames = [];
context.requestAnimationFrame = callback => { frames.push(callback); return frames.length; };
context.window = {};
vm.runInContext(source.slice(source.indexOf('async function bridge'), source.indexOf('$("login").onclick')), context);
const oldText = text('First');
const paragraph = tree('P', oldText);
const code = tree('CODE', text('print(1)'));
const body = tree('DIV', paragraph, tree('PRE', code));
for (let i = 1; i <= 240; i++) {
  context.patchChildren(body, tree('DIV', tree('P', text('First' + 'x'.repeat(i))), tree('PRE', tree('CODE', text('print(1)')))));
  assert.equal(body.childNodes[0], paragraph);
  assert.equal(paragraph.childNodes[0], oldText);
  assert.equal(body.childNodes[1].childNodes[0], code);
}
assert.equal(oldText.data, 'First' + 'x'.repeat(240));
context.patchChildren(body, tree('DIV', tree('P', tree('STRONG', text('Final')), text(' answer'))));
assert.equal(body.childNodes[0], paragraph);
assert.equal(paragraph.childNodes[0].nodeName, 'STRONG');
assert.equal(body.childNodes.length, 1);
context.patchChildren(body, tree('DIV'));
assert.equal(body.childNodes.length, 0);
vm.runInContext('let paintCount = 0; let paintedState; render = () => { paintCount++; paintedState = state; };', context);
for (let i = 0; i < 240; i++) {
  assert.equal(context.window.fusionJavaScriptHandler.handle('state', JSON.stringify({token: i})), 'OK');
}
assert.equal(frames.length, 1);
frames.shift()();
assert.equal(vm.runInContext('paintCount', context), 1);
assert.equal(vm.runInContext('paintedState.token', context), 239);
context.window.fusionJavaScriptHandler.handle('state', JSON.stringify({busy: false, status: 'Stopped'}));
assert.equal(frames.length, 1);
frames.shift()();
assert.equal(vm.runInContext('paintedState.status', context), 'Stopped');
assert.equal(context.window.fusionJavaScriptHandler.handle('state', '{broken'), 'FAILED');
console.log('Incremental streaming checks passed: node retention, Markdown changes, reset, batching and final state.');

// History rows are text-only, searchable, and resume the selected native thread.
const elements = new Map();
function element() {
  return {value: '', hidden: false, children: [], attrs: {}, textContent: '', dataset: {}, style: {},
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); },
    add(child) { this.children.push(child); },
    setAttribute(name, value) { this.attrs[name] = value; }, removeAttribute(name) { delete this.attrs[name]; },
    querySelectorAll() { return []; }, querySelector() { return null; }, addEventListener() {}, focus() {}};
}
context.document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
  createElement: element,
};
vm.runInContext(`state = {history: [
  {id: 'saved-1', title: '<img src=x> Bracket', updatedAt: 100},
  {id: 'saved-2', title: 'Sketch constraints', updatedAt: 200}
], threadId: 'saved-1', busy: false};
let selectedAction; act = (action, payload) => { selectedAction = {action, payload}; };`, context);
context.renderHistory();
assert.equal(elements.get('history-list').children.length, 2);
assert.equal(elements.get('history-list').children[0].children[0].textContent, '<img src=x> Bracket');
assert.equal(elements.get('history-list').children[0].attrs['aria-current'], 'true');
elements.get('history-search').value = 'CONSTRAINTS';
context.renderHistory();
assert.equal(elements.get('history-list').children.length, 1);
elements.get('history-list').children[0].onclick();
assert.equal(vm.runInContext('selectedAction.action', context), 'openHistory');
assert.equal(vm.runInContext('selectedAction.payload.threadId', context), 'saved-2');
assert.equal(elements.get('history-panel').hidden, true);
vm.runInContext('state.busy = true;', context);
context.renderHistory();
assert.equal(elements.get('history-list').children[0].disabled, true);
console.log('History checks passed: safe titles, filtering, current chat, resume action and busy state.');

vm.runInContext(source.slice(source.indexOf('$("debug-logging").onchange'), source.indexOf('$("new-chat").onclick')), context);
elements.get('debug-logging').onchange({target:{checked:true}});
assert.equal(vm.runInContext('selectedAction.action', context), 'debugLogging');
assert.equal(vm.runInContext('selectedAction.payload.enabled', context), true);
elements.get('debug-logging').onchange({target:{checked:false}});
assert.equal(vm.runInContext('selectedAction.payload.enabled', context), false);
elements.get('open-logs').onclick();
assert.equal(vm.runInContext('selectedAction.action', context), 'openLogs');
elements.get('dfm-enabled').onchange({target:{checked:true}});
assert.equal(vm.runInContext('selectedAction.action', context), 'dfm');
assert.equal(vm.runInContext('selectedAction.payload.enabled', context), true);
console.log('Debug menu checks passed: enable, disable, and open logs.');

// Updating requires an explicit in-app confirmation.
context.document.getElementById('update-confirm').showModal = () => {elements.get('update-confirm').open = true;};
elements.get('update-confirm').close = () => {elements.get('update-confirm').open = false;};
vm.runInContext(source.slice(source.indexOf('$("update-steve-now").onclick'), source.indexOf('$("new-chat").onclick')), context);
elements.get('update-steve-now').onclick();
assert.equal(elements.get('update-confirm').open, true);
elements.get('confirm-update').onclick();
assert.equal(vm.runInContext('selectedAction.action', context), 'updateSteve');
assert.equal(elements.get('update-confirm').open, false);
console.log('Update confirmation controls passed.');

// The composer steers an active turn, keeps Stop available, and retains failed drafts.
(async () => {
  context.Option = function(text, value) { return {text, value}; };
  context.document.getElementById('app').classList = {toggle() {}};
  vm.runInContext(`state = {connection:'ready', account:{}, accountChecked:true,
    messages:[{role:'user',text:'Make a bracket'}], models:[], history:[],
    busy:true, canSteer:false, threadId:'thread-1', turnId:null};
    resize = () => {}; let composerCalls=[];
    bridge = async (action,payload) => {composerCalls.push({action,payload});};`, context);
  const input = context.document.getElementById('message');
  input.value = 'Use 8 mm holes';
  context.renderControls();
  assert.equal(elements.get('send').disabled, true);
  assert.equal(elements.get('stop').hidden, false);
  assert.equal(input.disabled, false);
  vm.runInContext(source.slice(source.indexOf('$("composer").onsubmit'), source.indexOf('// Explicit design preview')), context);
  const submit = () => elements.get('composer').onsubmit({preventDefault() {}});
  await submit();
  assert.equal(input.value, 'Use 8 mm holes');
  assert.equal(vm.runInContext('composerCalls.length', context), 0);
  vm.runInContext("state.canSteer=true; state.turnId='turn-1';", context);
  context.renderControls();
  assert.equal(elements.get('send').disabled, false);
  assert.equal(elements.get('send').attrs['aria-label'], 'Steer current response');
  await submit();
  assert.equal(vm.runInContext('composerCalls[0].action', context), 'steer');
  assert.equal(vm.runInContext('composerCalls[0].payload.turnId', context), 'turn-1');
  assert.equal(input.value, '');
  vm.runInContext('state.busy=false; state.canSteer=false;', context);
  input.value = 'Next operation';
  await submit();
  assert.equal(vm.runInContext('composerCalls[1].action', context), 'send');
  vm.runInContext("bridge=async()=>{throw new Error('Disconnected')};", context);
  input.value = 'Keep this draft';
  await submit();
  assert.equal(input.value, 'Keep this draft');
  assert.equal(vm.runInContext('state.error', context), 'Disconnected');
  console.log('Composer checks passed: turn readiness, steering, Stop, normal send and failed draft.');
  vm.runInContext(`state.busy=false; state.model='model-1'; state.effort='ultra'; state.defaultEffort='low';
    state.effortOptions=[{id:'low',description:'Fast'},{id:'ultra',description:'More reasoning'}];`, context);
  context.renderControls();
  assert.equal(elements.get('effort').disabled, false);
  assert.equal(elements.get('effort').value, 'ultra');
  assert.deepEqual(elements.get('effort').children.map(e=>e.value), ['', 'low', 'ultra']);
  assert.equal(elements.get('effort').children[0].text, 'Default (Low)');
  vm.runInContext(source.slice(source.indexOf('$("model").onchange'), source.indexOf('$("app-menu-button").onclick')), context);
  elements.get('effort').onchange({target:{value:'low'}});
  assert.equal(vm.runInContext('selectedAction.action', context), 'effort');
  assert.equal(vm.runInContext('selectedAction.payload.effort', context), 'low');
  vm.runInContext(`state.busy=true; state.taskDocument={name:'Bracket <draft>'};
    state.waitingForFusion=true; state.waitingReason='Waiting for Bracket';`, context);
  context.renderControls();
  assert.equal(elements.get('model').disabled, true);
  assert.equal(elements.get('effort').disabled, true);
  assert.equal(elements.get('task-target').hidden, false);
  assert.equal(elements.get('task-target-label').textContent, 'Bracket <draft>');
  assert.equal(elements.get('task-target-meta').textContent, 'Waiting');
  assert.equal(elements.get('status').textContent, 'Waiting for Bracket');
  assert.equal(elements.get('status-dot').className, 'status-dot waiting');
  assert.equal(elements.get('thinking').hidden, true);
  assert.equal(elements.get('stop').hidden, false);
  console.log('Effort and task UI checks passed: catalog options, selection, busy controls, target and wait status.');
  // The footer is the single status line; it names the active tool while STEVE works.
  vm.runInContext(`state.activeTools=[{name:'fusion_query_python',title:'Inspect <faces>'},
    {name:'fusion_api_help',title:'adsk.fusion.Sketch'}]; state.waitingForFusion=false; state.status='Running in Fusion';`, context);
  context.renderControls();
  assert.equal(elements.get('status').textContent, 'Running in Fusion · Inspect <faces> · +1 more');
  assert.equal(elements.get('status').title, 'fusion_query_python: Inspect <faces>\nfusion_api_help: adsk.fusion.Sketch');
  assert.equal(elements.get('thinking').hidden, false);
  assert.equal(elements.get('thinking-label').textContent, 'Inspect <faces> · +1 more');
  assert.equal(elements.get('task-target-meta').textContent, 'Pinned');
  vm.runInContext(`state.messages.push({id:'python-1',role:'tool',code:'def run(context):\\n    pass',toolStatus:'running'});`, context);
  context.renderControls();
  assert.equal(elements.get('thinking').hidden, true, 'A running step already shows progress in the transcript');
  vm.runInContext(`state.messages.pop(); state.activeTools=[{name:'fusion_api_help',title:'adsk.fusion.Sketch'}]; state.status='Thinking';`, context);
  context.renderControls();
  assert.equal(elements.get('status').textContent, 'Thinking · Reading docs · adsk.fusion.Sketch');
  assert.equal(elements.get('thinking-label').textContent, 'Reading docs · adsk.fusion.Sketch');
  vm.runInContext(`state.status='Writing';`, context);
  context.renderControls();
  assert.equal(elements.get('thinking').hidden, true);
  vm.runInContext(`state.activeTools=[]; state.status='Thinking';`, context);
  context.renderControls();
  assert.equal(elements.get('status').textContent, 'Thinking');
  assert.equal(elements.get('thinking-label').textContent, 'Thinking');
  assert.equal(elements.get('status').title, '');
  console.log('Status line checks passed: safe labels, overlapping calls, running steps, docs lookups, writing and idle thinking.');
  vm.runInContext(`state.version='0.2.0'; state.updateInfo={version:'0.3.0'};
    state.updateChecking=true; state.updateStatus='Checking for updates…';`, context);
  context.renderControls();
  assert.equal(elements.get('installed-version').textContent, 'STEVE 0.2.0');
  assert.equal(elements.get('update-title').textContent, 'STEVE 0.3.0 is available');
  assert.equal(elements.get('update-banner').hidden, false);
  assert.equal(elements.get('update-steve-now').hidden, false);
  elements.get('update-steve-now').onclick();
  assert.equal(elements.get('update-confirm').open, true);
  elements.get('cancel-update').onclick();
  assert.equal(elements.get('check-updates').disabled, true);
  elements.get('download-update').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'downloadUpdate');
  vm.runInContext(`state.updateDownload={state:'downloading',version:'0.3.0',percent:47};`, context);
  context.renderControls();
  assert.equal(elements.get('download-update').textContent, 'Downloading 47%');
  assert.equal(elements.get('menu-download').disabled, true);
  assert.equal(elements.get('update-steve-now').disabled, true);
  vm.runInContext(`state.updateDownload={state:'ready',version:'0.3.0'};`, context);
  context.renderControls();
  assert.equal(elements.get('update-steve-now').hidden, false);
  // A verified download must explain why applying is blocked, then recover when idle.
  for (const [field, value, explanation] of [
    ['busy', true, /STEVE is still working/],
    ['job', {status:'active'}, /Pause or finish the current job/],
    ['jobBusy', true, /job operation/],
    ['loginPending', true, /Finish or cancel sign-in/],
    ['codexUpdating', true, /Codex update to finish/],
  ]) {
    vm.runInContext(`state.busy=false;state.job=null;state.jobBusy=false;state.loginPending=false;state.codexUpdating=false;
      state[${JSON.stringify(field)}]=${JSON.stringify(value)};`, context);
    context.renderControls();
    for (const id of ['update-steve-now','menu-update-now']) {
      assert.equal(elements.get(id).disabled, true);
      assert.match(elements.get(id).title, explanation);
    }
    assert.match(elements.get('update-hint').textContent, explanation);
    assert.match(elements.get('download-status').textContent, explanation);
  }
  vm.runInContext(`state.codexUpdating=false;`, context);
  context.renderControls();
  assert.equal(elements.get('update-steve-now').disabled, false);
  assert.equal(elements.get('menu-update-now').title, '');
  assert.match(elements.get('update-hint').textContent, /Update downloaded and verified/);
  vm.runInContext(`state.updateInstallReady=true;`, context);
  context.renderControls();
  assert.equal(elements.get('update-steve-now').hidden, true);
  vm.runInContext(`state.updateInstallReady=false;`, context);
  elements.get('download-update').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'openDownloads');
  elements.get('dismiss-update').onclick();
  context.renderControls();
  assert.equal(elements.get('update-banner').hidden, true);
  assert.equal(elements.get('menu-update').hidden, false);
  vm.runInContext('state.updateChecking=false;', context);
  elements.get('check-updates').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'checkUpdates');
  context.renderControls();
  assert.equal(elements.get('update-banner').hidden, false);
  assert.equal(elements.get('check-updates').disabled, false);
  console.log('Update UI checks passed: version, notice, dismissal, manual check and download action.');
  vm.runInContext(`state.provider='grok';state.busy=false;state.loginPending=false;`, context);
  context.renderControls();
  assert.equal(elements.get('provider').value, 'grok');
  assert.equal(elements.get('welcome-provider').value, 'grok');
  assert.equal(elements.get('login').textContent, 'Sign in with X / Grok ↗');
  elements.get('provider').onchange({target:{value:'chatgpt'}});
  assert.equal(vm.runInContext('selectedAction.action', context), 'provider');
  assert.equal(vm.runInContext('selectedAction.payload.provider', context), 'chatgpt');
  vm.runInContext(`state.busy=true;`, context);
  context.renderControls();
  assert.equal(elements.get('provider').disabled, true);
  console.log('Provider UI checks passed: selector, login labels, routing and busy lock.');
  vm.runInContext(`state.provider='ollama';state.busy=false;state.account=null;state.models=[];
    state.localStatus='Start Ollama';state.accountChecked=true;`, context);
  context.renderControls();
  assert.equal(elements.get('login').textContent, 'Refresh models');
  assert.equal(elements.get('device-login').hidden, true);
  assert.equal(elements.get('logout').hidden, true);
  assert.equal(elements.get('custom-controls').hidden, false);
  assert.equal(elements.get('custom-status').textContent, 'Start Ollama');
  assert.equal(elements.get('send').disabled, true);
  vm.runInContext(source.slice(source.indexOf('$("login").onclick'), source.indexOf('$("device-login").onclick')), context);
  elements.get('login').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'accountRefresh');
  assert.equal(vm.runInContext('selectedAction.payload.refreshModels', context), true);
  assert.equal(elements.get('account-plan').textContent, '127.0.0.1:11434 · No sign-in needed');
  assert.equal(elements.get('provider').value, 'custom');
  const serverDialog = context.document.getElementById('server-dialog');
  serverDialog.showModal = () => { serverDialog.open = true; };
  serverDialog.close = () => { serverDialog.open = false; };
  elements.get('custom-server').onclick();
  assert.equal(serverDialog.open, true);
  assert.equal(elements.get('server-type').value, 'ollama');
  assert.equal(elements.get('server-url').value, 'http://127.0.0.1:11434');
  assert.equal(elements.get('server-key').value, '');
  vm.runInContext('bridge = async (action, payload) => { selectedAction = {action, payload}; return {ok:true}; };', context);
  elements.get('server-url').value = 'https://printer.lan/ollama?think=false';
  elements.get('server-key').value = 'secret-value';
  await elements.get('server-form').onsubmit({preventDefault() {}});
  assert.equal(vm.runInContext('selectedAction.action', context), 'customServer');
  assert.deepEqual({...vm.runInContext('selectedAction.payload', context)}, {serverType:'ollama', baseUrl:'https://printer.lan/ollama?think=false', apiKey:'secret-value', clearApiKey:false});
  assert.equal(elements.get('server-key').value, '');
  assert.equal(serverDialog.open, false);
  elements.get('custom-server').onclick();
  elements.get('server-url').value = 'http://printer.lan:99999';
  elements.get('server-key').value = 'kept-secret';
  await elements.get('server-form').onsubmit({preventDefault() {}});
  assert.equal(serverDialog.open, true);
  assert.equal(elements.get('server-key').value, 'kept-secret');
  assert.equal(elements.get('server-error').hidden, false);
  elements.get('server-url').value = 'http://printer.lan:11434';
  elements.get('server-clear-key').checked = true;
  await elements.get('server-form').onsubmit({preventDefault() {}});
  assert.equal(vm.runInContext('selectedAction.payload.clearApiKey', context), true);
  assert.equal(vm.runInContext('selectedAction.payload.apiKey', context), undefined);
  vm.runInContext('state.ollamaAddress="10.1.2.3:11435"; state.ollamaApiKeySet=true; state.error="";', context);
  context.renderControls();
  assert.match(elements.get('account-plan').textContent, /10.1.2.3:11435/);
  assert.equal(elements.get('server-clear-row').hidden, false);
  vm.runInContext(`state.account={email:'Local Ollama'};state.models=[];`, context);
  context.renderControls();
  assert.equal(elements.get('sign-in-card').hidden, false);
  assert.equal(elements.get('send').disabled, true);
  vm.runInContext(`state.models=[{id:'local',name:'Local',isDefault:true,supportsImages:false}];state.model='local';`, context);
  context.renderControls();
  assert.equal(elements.get('sign-in-card').hidden, true);
  assert.equal(elements.get('message').disabled, false);
  assert.equal(elements.get('attach-images').disabled, true);
  assert.equal(elements.get('model').children[0].text, 'Local default');
  vm.runInContext(`state.busy=true;`, context);
  context.renderControls();
  assert.equal(elements.get('custom-refresh').disabled, true);
  assert.equal(elements.get('custom-server').disabled, true);
  assert.equal(elements.get('server-save').disabled, true);
  console.log('Ollama UI checks passed: no sign-in, offline/empty states, refresh, local models and vision limits.');
  vm.runInContext(`state.provider='claude';state.busy=false;state.account=null;state.models=[];
    state.localStatus='Run claude auth login outside Fusion';`, context);
  context.renderControls();
  assert.equal(elements.get('login').textContent, 'Check connection');
  assert.equal(elements.get('device-login').hidden, true);
  assert.equal(elements.get('logout').hidden, true);
  assert.equal(elements.get('claude-controls').hidden, false);
  assert.equal(elements.get('claude-links').hidden, false);
  assert.equal(elements.get('claude-version').textContent, 'Claude Code · Version unavailable');
  vm.runInContext(`state.providerVersion='2.1.260';`, context);
  context.renderControls();
  assert.equal(elements.get('claude-version').textContent, 'Claude Code 2.1.260');
  vm.runInContext(`state.providerVersion='2.1.263';`, context);
  context.renderControls();
  assert.equal(elements.get('claude-version').textContent, 'Claude Code 2.1.263');
  assert.match(elements.get('sign-in-description').textContent, /claude auth login/);
  elements.get('login').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'login');
  elements.get('claude-refresh').onclick();
  assert.equal(vm.runInContext('selectedAction.payload.refreshModels', context), true);
  elements.get('install-claude').onclick();
  assert.equal(vm.runInContext('selectedAction.payload.page', context), 'claude');
  vm.runInContext(`state.account={email:'Claude fixture'};`, context);
  context.renderControls();
  assert.equal(elements.get('send').disabled, true);
  vm.runInContext(`state.models=[{id:'sonnet',name:'Sonnet',isDefault:true}];state.model='sonnet';`, context);
  context.renderControls();
  assert.equal(elements.get('sign-in-card').hidden, true);
  assert.equal(elements.get('message').disabled, false);
  assert.equal(elements.get('logout').hidden, true);
  console.log('Claude UI checks passed: external login, setup link, account refresh and model readiness.');
  vm.runInContext(`state.provider='openrouter';state.busy=false;state.account=null;state.models=[];state.model='';
    state.accountChecked=true;state.loginPending=false;`, context);
  context.renderControls();
  assert.equal(elements.get('login').textContent, 'Sign in with OpenRouter ↗');
  assert.equal(elements.get('device-login').hidden, true);
  assert.equal(elements.get('openrouter-links').hidden, false);
  assert.equal(elements.get('openrouter-controls').hidden, true);
  assert.match(elements.get('sign-in-note').textContent, /OpenRouter credits.*Web search is unavailable/);
  elements.get('login').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'login');
  elements.get('openrouter-credits').onclick();
  assert.equal(vm.runInContext('selectedAction.payload.page', context), 'openrouter');
  vm.runInContext(`state.account={email:'STEVE',planType:'OpenRouter · Pay as you go'};state.models=[
    {id:'anthropic/claude-sonnet-5',name:'Anthropic: Claude Sonnet 5',group:'anthropic',isDefault:true,supportsImages:true},
    {id:'qwen/qwen3-coder',name:'Qwen: Qwen3 Coder',group:'qwen',isDefault:false,supportsImages:false}];state.model='qwen/qwen3-coder';`, context);
  context.renderControls();
  assert.equal(elements.get('sign-in-card').hidden, true);
  assert.equal(elements.get('logout').hidden, false);
  assert.equal(elements.get('chatgpt-refresh').hidden, true);
  assert.equal(elements.get('openrouter-controls').hidden, false);
  assert.equal(elements.get('account-plan').textContent, 'OpenRouter · Pay as you go · Connected');
  assert.equal(elements.get('attach-images').disabled, true);
  const picker = elements.get('model').children;
  assert.equal(picker[0].text, 'Most popular');
  assert.deepEqual(picker.slice(1).map(group => [group.label, group.children.map(option => option.value)]),
    [['anthropic', ['anthropic/claude-sonnet-5']], ['qwen', ['qwen/qwen3-coder']]]);
  vm.runInContext(`state.model='anthropic/claude-sonnet-5';`, context);
  context.renderControls();
  assert.equal(elements.get('attach-images').disabled, false);
  elements.get('openrouter-refresh').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'accountRefresh');
  assert.equal(vm.runInContext('selectedAction.payload.refreshModels', context), true);
  elements.get('openrouter-keys').onclick();
  assert.equal(vm.runInContext('selectedAction.payload.page', context), 'openrouter');
  console.log('OpenRouter UI checks passed: browser sign-in, key links, grouped models and image limits.');
  vm.runInContext(`state.provider='openai';state.account=null;state.models=[];state.model='';state.localStatus='';
    state.openaiBaseUrl='http://127.0.0.1:1234/v1';state.openaiApiKeySet=true;`, context);
  context.renderControls();
  assert.equal(elements.get('login').textContent, 'Refresh models');
  assert.equal(elements.get('device-login').hidden, true);
  assert.equal(elements.get('custom-links').hidden, false);
  assert.equal(elements.get('server-clear-row').hidden, false);
  elements.get('login').onclick();
  assert.equal(vm.runInContext('selectedAction.action', context), 'accountRefresh');
  vm.runInContext(`state.account={email:'127.0.0.1:1234',planType:'OpenAI-compatible'};state.models=[{id:'qwen3',name:'qwen3',isDefault:true}];`, context);
  context.renderControls();
  assert.equal(elements.get('sign-in-card').hidden, true);
  assert.equal(elements.get('logout').hidden, true);
  assert.equal(elements.get('account-plan').textContent, 'http://127.0.0.1:1234/v1 · API key saved');
  elements.get('custom-server').onclick();
  assert.equal(elements.get('provider').value, 'custom');
  assert.equal(elements.get('server-type').value, 'openai');
  vm.runInContext(`$('server-url').value=' https://llm.example/v1 ';$('server-key').value='sk-test';$('server-clear-key').checked=false;`, context);
  await elements.get('server-form').onsubmit({preventDefault() {}});
  assert.equal(vm.runInContext('selectedAction.action', context), 'customServer');
  assert.deepEqual({...vm.runInContext('selectedAction.payload', context)}, {serverType:'openai',baseUrl:'https://llm.example/v1',clearApiKey:false,apiKey:'sk-test'});
  assert.equal(elements.get('server-key').value, '');
  elements.get('custom-server').onclick();
  elements.get('server-key').value = 'never-reuse-on-another-type';
  elements.get('server-type').value = 'ollama';
  elements.get('server-type').onchange();
  assert.equal(elements.get('server-key').value, '');
  assert.equal(elements.get('server-url').value, 'http://10.1.2.3:11435');
  vm.runInContext('state.serverSaving=true;', context);
  context.renderControls();
  assert.equal(elements.get('send').disabled, true);
  assert.equal(elements.get('server-save').disabled, true);
  assert.equal(elements.get('provider').disabled, true);
  console.log('OpenAI-compatible UI checks passed: server dialog, key handling and no-sign-in readiness.');
})().catch(error => { console.error(error); process.exitCode = 1; });
