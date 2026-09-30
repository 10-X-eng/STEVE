// Real browser coverage for the Settings list and pages, the Conversations view and the composer menu. Requires Playwright and Edge.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 436, height: 626}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.testActions = [];
      window.adsk = {fusionSendData: async (action, payload) => {
        window.testActions.push({action, payload});
        return '{"ok":true}';
      }};
    });
    await page.goto(pathToFileURL(path.resolve(__dirname, '../addin/STEVE/panel/index.html')).href);
    const snapshot = {connection: 'ready', account: {email: 'designer@example.com', planType: 'Plus'},
      accountChecked: true, models: [], messages: [], busy: false, status: 'Ready', version: '0.6.2',
      codexVersion: '0.155.1', codexPendingVersion: '0.155.2', dfmEnabled: true, rmfgState: 'connected'};
    const send = async patch => {
      Object.assign(snapshot, patch);
      await page.evaluate(snapshot => window.fusionJavaScriptHandler.handle('state', JSON.stringify(snapshot)), snapshot);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    };
    const focused = selector => page.locator(selector).evaluate(el => el === document.activeElement);
    const row = name => page.locator(`.settings-row[data-page="${name}"]`);
    await send({});

    // The gear opens a short list of categories; each row summarizes its page.
    assert.equal(await page.locator('#settings-dot').isVisible(), true, 'A pending runtime restart is flagged on the gear');
    await page.locator('#app-menu-button').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#app-menu').isVisible(), true);
    assert.equal(await page.locator('#app-menu-button').getAttribute('aria-expanded'), 'true');
    assert.equal(await page.locator('#settings-root').isVisible(), true);
    assert.equal(await page.locator('#settings-back').isVisible(), false);
    assert.equal(await page.locator('#settings-title').textContent(), 'Settings');
    assert.equal(await focused('.settings-row[data-page="account"]'), true, 'Focus moves to the first row');
    assert.equal(await page.locator('#row-account-value').textContent(), 'ChatGPT · designer@example.com');
    assert.equal(await page.locator('#row-manufacturing-value').textContent(), 'DFM on · RMFG connected');
    assert.equal(await page.locator('#row-updates-value').textContent(), 'Codex 0.155.2 ready · restart to use it');
    assert.equal(await page.locator('#updates-badge').textContent(), 'Restart ready');
    assert.equal(await page.locator('#row-diagnostics-value').textContent(), 'Debug logging off');
    assert.equal(await page.locator('#settings-version').textContent(), 'STEVE v0.6.2 · Codex 0.155.1');
    assert.equal(await page.locator('#provider').isVisible(), false, 'Pages stay closed until chosen');
    assert(await page.evaluate(() => { const body = document.querySelector('#app-menu .panel-body'); return body.scrollHeight <= body.clientHeight; }), 'The list fits without scrolling');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    assert.equal(await focused('#app-menu-button'), true);

    // Rows open pages; Back and Escape return to the list with focus on the row that was opened.
    await page.locator('#app-menu-button').click();
    await row('account').click();
    assert.equal(await page.locator('#settings-root').isVisible(), false);
    assert.equal(await page.locator('#settings-account').isVisible(), true);
    assert.equal(await page.locator('#settings-title').textContent(), 'AI provider');
    assert.equal(await page.locator('#settings-back').isVisible(), true);
    assert.equal(await focused('#provider'), true);
    assert.equal(await page.locator('#account-email').textContent(), 'designer@example.com');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#app-menu').isVisible(), true, 'Escape steps back one level first');
    assert.equal(await page.locator('#settings-root').isVisible(), true);
    assert.equal(await focused('.settings-row[data-page="account"]'), true);
    await row('updates').click();
    assert.equal(await page.locator('#settings-title').textContent(), 'Updates');
    assert.equal(await page.locator('#installed-version').textContent(), 'STEVE 0.6.2');
    assert.equal(await page.locator('#restart-steve').isVisible(), true);
    await page.locator('#check-codex-updates').click();
    assert.equal(await page.locator('#settings-updates').isVisible(), true, 'Actions keep the page open');
    await page.locator('#settings-back').click();
    assert.equal(await focused('.settings-row[data-page="updates"]'), true);
    await row('diagnostics').click();
    await page.locator('#debug-logging').check();
    await page.locator('#open-logs').click();
    await page.locator('#settings-back').click();
    await row('manufacturing').click();
    await page.locator('#dfm-enabled').uncheck();
    const actions = await page.evaluate(() => window.testActions);
    for (const name of ['checkCodexUpdates', 'debugLogging', 'openLogs', 'dfm'])
      assert(actions.some(entry => entry.action === name), `Missing bridge action ${name}`);
    await send({busy: true});
    assert.equal(await page.locator('#dfm-enabled').isDisabled(), true);
    await page.locator('#settings-back').click();
    await row('updates').click();
    assert.equal(await page.locator('#restart-steve').isDisabled(), true);
    await send({busy: false});
    await page.locator('#settings-back').click();

    // RMFG lives under the DFM switch on the Manufacturing page and only appears while DFM is on.
    await row('manufacturing').click();
    assert.equal(await page.locator('#rmfg-settings').isVisible(), true);
    assert.equal(await page.locator('#rmfg-disconnect').isVisible(), true);
    assert.equal(await page.locator('#rmfg-enable-checkout').isVisible(), true);
    await page.locator('#rmfg-enable-checkout').click();
    assert.equal(await page.evaluate(() => window.testActions.at(-1).action), 'rmfgEnableCheckout');
    await send({rmfgCheckoutEnabled: true});
    assert.equal(await page.locator('#rmfg-enable-checkout').isVisible(), false);
    await send({dfmEnabled: false});
    assert.equal(await page.locator('#rmfg-settings').isVisible(), false);
    await page.locator('#settings-back').click();
    assert.equal(await page.locator('#row-manufacturing-value').textContent(), 'DFM off');
    await send({dfmEnabled: true, rmfgState: 'reconnect'});
    assert.equal(await page.locator('#row-manufacturing-value').textContent(), 'DFM on · RMFG needs reconnect');
    assert.equal(await page.locator('#rmfg-badge').isVisible(), true, 'Attention shows on the row');
    await send({rmfgState: 'connected'});
    assert.equal(await page.locator('#rmfg-badge').isVisible(), false);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#dfm-chip').isVisible(), true);

    // Settings and conversations are exclusive full-height views; the DFM chip deep-links to Manufacturing.
    await page.locator('#history-button').click();
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    assert.equal(await page.locator('#history-panel').isVisible(), true);
    assert.equal(await focused('#history-search'), true);
    await page.locator('#app-menu-button').click();
    assert.equal(await page.locator('#history-panel').isVisible(), false);
    assert.equal(await page.locator('#app-menu').isVisible(), true);
    assert.equal(await page.locator('#settings-root').isVisible(), true, 'Reopening starts at the list');
    await page.locator('#app-menu-button').click();
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    await page.locator('#app-menu-button').click();
    await page.locator('#settings-close').click();
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    assert.equal(await focused('#app-menu-button'), true);
    await page.locator('#dfm-chip').click();
    assert.equal(await page.locator('#settings-manufacturing').isVisible(), true);
    assert.equal(await focused('#dfm-enabled'), true);
    await page.locator('#settings-close').click();
    await page.locator('#history-button').click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#history-panel').isVisible(), false);
    assert.equal(await focused('#history-button'), true);

    // The composer + menu: outside clicks and focus changes dismiss it; Escape returns focus.
    await page.locator('#composer-plus').click();
    assert.equal(await page.locator('#plus-menu').isVisible(), true);
    assert.equal(await page.locator('#composer-plus').getAttribute('aria-expanded'), 'true');
    assert.equal(await focused('#attach-images'), true);
    assert.equal(await page.locator('#dream-entry').isVisible(), true, 'ChatGPT accounts can Dream');
    assert.equal(await page.locator('#job-button-label').textContent(), 'Start a job');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#plus-menu').isVisible(), false);
    assert.equal(await focused('#composer-plus'), true);
    await page.locator('#composer-plus').click();
    await page.locator('#message').focus();
    assert.equal(await page.locator('#plus-menu').isVisible(), false);
    await page.locator('#composer-plus').click();
    await page.mouse.click(4, 300);
    assert.equal(await page.locator('#plus-menu').isVisible(), false);
    await send({provider: 'claude', models: [{id: 'sonnet', name: 'Sonnet', isDefault: true}], model: 'sonnet'});
    await page.locator('#composer-plus').click();
    assert.equal(await page.locator('#dream-entry').isVisible(), false, 'Dream needs a ChatGPT account');
    await page.keyboard.press('Escape');
    await page.locator('#app-menu-button').click();
    assert.equal(await page.locator('#row-account-value').textContent(), 'Claude · designer@example.com');
    await page.keyboard.press('Escape');
    await send({provider: 'chatgpt', models: [], model: ''});

    // Chips summarize the pinned document, the job and a ready checkout without extra status blocks.
    await send({threadId: 'fixture-chat', rmfgCheckout: {id: 'receipt-1', threadId: 'fixture-chat'}});
    assert.equal(await page.locator('#rmfg-checkout').isVisible(), true);
    await page.locator('#rmfg-open-checkout').click();
    const checkoutAction = await page.evaluate(() => window.testActions.find(entry => entry.action === 'rmfgOpenCheckout'));
    assert.deepEqual(JSON.parse(checkoutAction.payload), {checkoutId: 'receipt-1'});
    await send({threadId: 'other-chat'});
    assert.equal(await page.locator('#rmfg-checkout').isVisible(), false);
    await send({rmfgCheckout: null});
    await send({busy: true, taskDocument: {name: 'Bracket v3'}, job: {objective: 'Verify the bracket', status: 'active', tokensUsed: 10}});
    assert.equal(await page.locator('#task-target').isVisible(), true);
    assert.equal(await page.locator('#task-target-label').textContent(), 'Bracket v3');
    assert.equal(await page.locator('#task-target-meta').textContent(), 'Pinned');
    assert.equal(await page.locator('#job-strip').isVisible(), true);
    assert.equal(await page.locator('#job-strip-status').textContent(), 'Working');
    assert.equal(await page.locator('#tool-activity').count(), 0, 'No duplicate tool card');
    await send({busy: false, taskDocument: null, job: null});
    assert.equal(await page.locator('#task-target').isVisible(), false);
    assert.equal(await page.locator('#job-strip').isVisible(), false);

    // Keep the list, every page and the conversations view usable in a narrow, short Fusion palette.
    for (const width of [320, 436, 760]) {
      await page.setViewportSize({width, height: 480});
      for (const target of ['root', 'account', 'manufacturing', 'updates', 'diagnostics', 'history']) {
        await page.locator(target === 'history' ? '#history-button' : '#app-menu-button').click();
        if (target !== 'root' && target !== 'history') await row(target).click();
        const id = target === 'history' ? 'history-panel' : 'app-menu';
        const bounds = await page.locator('#' + id).boundingBox();
        assert(bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y + bounds.height <= 480, `${target} overflows at ${width}`);
        assert(await page.locator(`#${id} .panel-body`).evaluate(el => el.scrollWidth <= el.clientWidth), `${target} scrolls sideways at ${width}`);
        const gear = await page.locator('#app-menu-button').boundingBox();
        const history = await page.locator('#history-button').boundingBox();
        assert(history.x + history.width <= gear.x, 'Header controls overlap');
        await page.keyboard.press('Escape');
        if (target !== 'root' && target !== 'history') await page.keyboard.press('Escape');
        assert.equal(await page.locator('#' + id).isVisible(), false, `${target} did not close at ${width}`);
      }
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Page scrolls sideways at ${width}`);
    }
    await page.setViewportSize({width: 436, height: 626});
    await page.locator('#app-menu-button').click();
    if(process.env.STEVE_MENU_SCREENSHOT) await page.screenshot({path: process.env.STEVE_MENU_SCREENSHOT});
    await page.keyboard.press('Escape');
    await send({provider: 'ollama', account: null, accountChecked: true, models: [],
      ollamaBaseUrl: 'https://ollama.example/runner?think=false', ollamaApiKeySet: true,
      openaiBaseUrl: 'https://responses.example/v1', openaiApiKeySet: false});
    assert.deepEqual(await page.locator('#welcome-provider option').evaluateAll(options => options.map(o => o.value)),
      ['chatgpt', 'grok', 'claude', 'openrouter', 'custom']);
    assert.equal(await page.locator('#welcome-provider').inputValue(), 'custom');
    await page.locator('#custom-server-welcome').click();
    assert.equal(await page.locator('#server-type').inputValue(), 'ollama');
    assert.equal(await page.locator('#server-url').inputValue(), 'https://ollama.example/runner?think=false');
    await page.locator('#server-key').fill('do-not-transfer-this-draft');
    await page.locator('#server-type').selectOption('openai');
    assert.equal(await page.locator('#server-url').inputValue(), 'https://responses.example/v1');
    assert.equal(await page.locator('#server-key').inputValue(), '');
    assert.equal(await page.locator('#server-clear-row').isVisible(), false);
    await page.locator('#server-url').fill('https://responses.example/v1?bad=query');
    await page.locator('#server-save').click();
    assert.equal(await page.locator('#server-error').isVisible(), true);
    assert.equal(await page.locator('#server-dialog').isVisible(), true);
    await page.locator('#server-url').fill('https://responses.example/v1');
    await page.locator('#server-key').fill('fixture-key');
    await page.locator('#server-save').click();
    assert.equal(await page.locator('#server-dialog').isVisible(), false);
    const save = await page.evaluate(() => window.testActions.filter(a => a.action === 'customServer').at(-1));
    assert.deepEqual(JSON.parse(save.payload), {serverType:'openai', baseUrl:'https://responses.example/v1', clearApiKey:false, apiKey:'fixture-key'});
    assert.equal(await page.locator('#server-key').inputValue(), '');
    await send({provider:'openai', customServerType:'openai'});
    await page.locator('#custom-server-welcome').click();
    for(const width of [320, 436]) {
      await page.setViewportSize({width, height:626});
      const bounds = await page.locator('#server-dialog').boundingBox();
      assert(bounds.x >= 0 && bounds.x + bounds.width <= width, `Server dialog overflows at ${width}`);
      assert(await page.locator('#server-dialog').evaluate(el => el.scrollWidth <= el.clientWidth));
    }
    if(process.env.STEVE_SERVER_SCREENSHOT) await page.screenshot({path:process.env.STEVE_SERVER_SCREENSHOT});
    await send({serverSaving:true});
    assert.equal(await page.locator('#server-save').isDisabled(), true);
    assert.equal(await page.locator('#server-type').isDisabled(), true);
    assert.deepEqual(errors, []);
    console.log('Menu checks passed: settings list and pages, keyboard/focus, back navigation, exclusive views, composer menu, chips, actions, busy guards and responsive layout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
