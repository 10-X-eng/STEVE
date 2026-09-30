# Developing STEVE

STEVE is a Fusion add-in for Windows x64 and macOS on Apple silicon, with ChatGPT sign-in, streaming chat, persistent history, and a general Python execution bridge into Fusion's installed APIs.

## Part-by-part design behavior

The shared prompt defaults to functional geometry: establish part functions and shared
interfaces, build one logical part, query its actual geometry and inspect a viewport,
correct discrepancies, then continue. Repeated parts may reuse a verified source.
Assembly integration requires another check; a later interface change invalidates earlier
checks on the affected parts. Basic design verification is independent of the DFM toggle.
The verification result also directs correction before dependent construction.

This is model guidance, not a runtime-enforced design gate. Existing checks validate only
the measurements the script actually records and a bounded feature-health sample. Neither
a passing script nor a screenshot proves the design works. Current instructions are sent
on thread creation and history resume; changing source does not update an already running
conversation. Model compliance still needs a live Fusion trial.

For that trial, request a two-part enclosure with specified mating clearance and screw
interfaces. Check the trace for a completed and measured base before lid construction,
visual inspection, correction of any mismatch, and final assembly clearance/interference
checks. Repeat with DFM off: basic fit checks should remain. Ask for a change to the mating
interface and confirm both parts are rechecked. An unspecified critical screw interface
should trigger inspection or a focused question, not fabricated hardware dimensions.

## Shared image gallery

Release highlights ship in `release_notes.py`; update them with each version bump.
The notice is acknowledged per version in `release-notes-seen.json` in the user data
folder. Settings can reopen the bundled notes without network access. Run
`python scripts/verify_update.py` after building to verify complete-package staging,
activation, migration, rollback and retry without touching Fusion. Optionally pass
`--previous-archive` with a prior release ZIP and its sibling checksum file.

`gallery.py` maintains `images/gallery.json` alongside the existing content-addressed
image files and chat indexes. First use discovers valid cached PNG/JPEG/WebP assets and
recovers names from bounded chat catalogs. Later scans discover new images. Migration
never moves/deletes files, rewrites chat indexes, or enables an entry. Duplicate hashes
share an entry; removal leaves a disabled tombstone so rescanning cannot resurrect it.
Explicit reimport restores a removed entry with access off. Damaged images are skipped;
a damaged gallery index fails closed and is preserved for recovery. Atomic replacement
and the existing cross-process writer lock protect edits and migrations.

The gallery bridge runs file work on a worker and publishes results through Fusion's
custom event, separately from streaming state. Add-in update handoff waits for the gallery
worker. UI management is not exposed as model tools. `list_gallery_images` filters enabled
metadata; `view_gallery_image` rechecks permission before delivering pixels into the
expected active turn. No gallery pixels are injected by listing, and no model can enable
images. Gallery access is shared across AI providers on this OS account; existing chats
keep their original tool definitions, so new gallery tools require a new conversation.

Run `python -m unittest discover -s tests -p 'test_gallery*.py'` and
`node tests/test_gallery.cjs`. Also run the full suite and the update/package verification
scripts before release. Migration/rollback fixtures must preserve image hashes, chat
indexes, enabled states and removed tombstones. Live Fusion visual behavior still needs
user confirmation; standalone browser tests do not substitute for it.

## STEVE Dream

ChatGPT threads enable Codex's native `image_generation` feature; other providers keep
it disabled. Both new and resumed ChatGPT threads receive concise concept instructions.
`item/started` and `item/completed` events with type `imageGeneration` drive a stable
chat card. The controller worker validates and caches completed images (8 MiB maximum),
keeping base64 out of state snapshots. Native image generation, editing and billing
stay with the user's Codex connection; STEVE does not call an image API with a separate key.

Generated images join the per-chat image catalog with source `generated` and the native
item ID. History restores cached previews or reads native results; `savedPath` recovery
is restricted to that thread's Codex generated-images directory. Refine and Use as
reference prepare an ordinary image attachment without sending the user's draft.
Save exports the original to the user's Downloads folder under a unique filename.

Run `python -m unittest discover -s tests -p test_dream.py` and, with Playwright and
Edge installed, `node tests/test_dream.cjs`. The browser test covers large previews,
progress, retained DOM nodes, draft protection, export routing and provider limits.
Live generation consumes subscription limits and is intentionally outside automated tests.
See [OpenAI image generation](https://learn.chatgpt.com/docs/image-generation) and
the [app-server protocol](https://learn.chatgpt.com/docs/app-server).

## Release updates

`STEVE.manifest` owns the STEVE version; `steve.version` supplies it to the panel, Codex handshake, and packaging scripts. Coordinate a new, unused version with the upstream maintainer and update the release notes and installation examples before the next upstream release. Only `10-X-eng/STEVE` publishes a release after verified builds on its `main`; forks build artifacts without publishing from `main`.

`steve.updates` checks the public [GitHub releases API](https://docs.github.com/en/rest/releases/releases) in a separate worker on add-in startup and every 12 hours, plus manual requests. It includes previews, ignores drafts and malformed tags, compares numeric versions, and requires the current platform's ZIP and checksum assets. It sends no ChatGPT credentials, conversations, or design data. HTTP failures update only the menu status and never cancel a model turn.

`steve.downloads` streams packages to unique partial files in Downloads and verifies the published SHA-256 before renaming them to ZIP. Windows uses [SHGetKnownFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath) for redirected Downloads folders; macOS uses the current user's Downloads folder. Managed installations download automatically in the background. **Download only** saves the verified ZIP without installing. **Update & restart STEVE**, after confirmation and an idle check, applies through Fusion's add-in lifecycle without closing Fusion; see In-Fusion updates below. Source checkouts update manually. The separate **Restart STEVE** action restarts only the conversation runtime.

## Independent Codex updates

`steve.runtime_updates` checks OpenAI's latest stable release and the host's complete app-server asset. It requires the official asset URL, uploaded status, bounded size, and SHA-256 digest from GitHub. Downloads and extraction are bounded, archive links and escaping paths are rejected, and package version/target/layout are verified. A temporary isolated runtime checks initialization, model discovery, thread creation with STEVE's tools/Code Mode, and Codex goal reads without credentials or inference.

A successful update moves into a unique directory under the user's `runtimes` folder and atomically replaces `active.json`. Running processes keep their original files. Selection applies on the next transport startup, including provider changes or reconnects. The Settings view’s **Restart STEVE** action closes and reconnects the owned conversation transport, refreshes models, and resumes the current saved thread while leaving Fusion and the add-in running. Active/queued tasks, jobs, sign-ins, and downloads block this action. A restart verifies that the pending version actually activated, and the updater reads back its saved selection before reporting readiness. It shows the running version separately from the pending version. Recovery clears the selection for the next start; existing runtime directories are retained. Invalid or missing selections use the bundled runtime. Chats and credentials stay in their existing provider homes.

`transport.VERSION` specifies only the reproducible package-build baseline. Runtime validation requires internally consistent metadata and supporting files, not equality with that constant. Build downloads have version-specific cache paths and stage a complete package before replacing the development runtime; the previous directory is preserved under `.cache`. Stop the local add-in before replacing a development runtime. Installed users use the background updater instead.

## Grok provider

Model discovery reads `capabilities.reasoning_effort` and `capabilities.default_reasoning_effort` from xAI's [model catalog](https://docs.x.ai/developers/rest-api-reference/inference/models). Only levels understood by the bundled runtime are offered; models without capability metadata keep the provider default. Selected effort travels through Codex's turn settings into Responses `reasoning.effort`, including tool continuations and resumed conversations.

`grok_auth.py` implements browser authorization-code login with PKCE and state validation, cancellable device polling, refresh rotation, userinfo lookup, and revocation. Endpoints and scopes come from [xAI's OpenID metadata](https://auth.x.ai/.well-known/openid-configuration). It uses the public Grok CLI client ID. Credentials live only in STEVE's `grok` folder: Windows uses current-user DPAPI; macOS uses a private directory and owner-only file. No OAuth tokens reach the UI, Codex config, or debug logs.

`GrokTransport` adapts account/model RPCs and uses Codex's [custom Responses provider configuration](https://learn.chatgpt.com/docs/config-file/config-reference). Its random-path loopback gateway forwards only Responses requests to xAI, resolves tokens at request time, retries an authentication failure once after refresh, streams without buffering a full response, and removes the unsupported replayed reasoning items and `external_web_access` search flag. Grok receives STEVE's ordinary Python function tools rather than Code Mode wrappers. Images, steering, tool results, and histories still use the existing Codex protocol.

ChatGPT keeps its existing data paths. Grok has a separate `grok-runtime` home and explicit history provider filter; selection and model preferences are remembered separately. A provider change cannot interrupt a running task, and stale events from the closed runtime are ignored. Tests use fake xAI responses, not real credentials or paid inference. `test_grok_runtime.py` exercises the actual bundled runtime through a tool call, response, history listing, process restart, and continuation.

## OpenRouter provider

`openrouter_auth.py` implements OpenRouter's [OAuth PKCE flow](https://openrouter.ai/docs/guides/overview/auth/oauth): it opens `https://openrouter.ai/auth` with an S256 challenge, `key_label=STEVE`, and a `localhost` callback on a random port. OpenRouter has no `state` parameter, so the callback path contains a random token; other paths are rejected before any exchange. The code is exchanged at `POST /api/v1/auth/keys` for a user-owned API key. `GET /api/v1/key` supplies the account label and credit summary; a 401 there forgets the key. The key and that public summary are stored with `SecureStore` (macOS Keychain, Windows DPAPI). Sign out forgets the local key; OpenRouter has no revoke call for it, so the UI links to OpenRouter's key settings.

Model discovery reads the public [models API](https://openrouter.ai/docs/guides/overview/models) with `supported_parameters=tools` and `sort=most-popular`. It keeps text-output models with at least 64K context, excluding `:batch` variants and expired models. The most popular remaining model is the default; the catalog is grouped by vendor in the picker. `architecture.input_modalities` decides image support, and `reasoning.supported_efforts`/`default_effort` supply the effort choices.

`OpenRouterTransport` uses Codex's custom Responses provider (`steve_openrouter`) with its own `openrouter-runtime` home and history filter. Code Mode and web search are disabled. OpenRouter's [Responses API](https://openrouter.ai/docs/api/reference/responses/overview) is stateless and rejects `store: true` and `previous_response_id`; Codex sends `store: false` and full input, which fits. Each thread's `model_context_window` comes from the model's `context_length`, and auto-compaction starts at 80% of it, capped at 200K tokens because every request resends the history. A turn with a different model reapplies these settings through `thread/resume` first. Turns and steering with images are rejected for text-only models, which also covers viewport captures.

The random-path loopback gateway forwards only Responses requests, adds the key and OpenRouter's app attribution headers at request time, removes `client_metadata` (local installation and session identifiers), and drops the `content: null` field from replayed reasoning items. Reasoning items stay in the input so models that need their earlier reasoning during tool loops keep it. 401, 402, 403 and 429 responses become short explanations without upstream bodies; other upstream errors pass through. Tests use fake OpenRouter responses; `test_openrouter_runtime.py` exercises the bundled runtime through a tool call, reasoning replay, history, restart and a model switch.

`openai_compat_transport.py` connects to any server with the Responses API. `OpenAICompatSettings` keeps the base URL and an `apiKeySet` flag in `openai-compat/endpoint.json` (0600) and the key in `SecureStore` (`openai-compat-key`). Base URLs must be http(s) with no credentials, query or fragment. `GET {base}/models` (Bearer key, no system proxy, 4 MB cap) supplies the catalog; `context_length`, `max_model_len` or `context_window` sets the context window, else 32K, with compaction at 80%. Reasoning effort shows Default only: `/models` has no standard effort field, and servers accept efforts that a model's chat template ignores. `OpenAICompatTransport` uses Codex's `steve_openai_compat` Responses provider with its own `openai-compat-runtime` home and history filter. The key reaches Codex only through the child process variable named by `env_key`, never thread config. Saving the server restarts the engine and reopens the chat. Tests use fake responses (`test_openai_compat.py`).

## Local setup

The panel exposes one **Custom server** entry and a shared Server dialog with an Ollama/OpenAI-compatible selector. `custom_server.py` owns protected endpoint persistence, key validation, same-origin-only metadata redirects, Responses configuration, and the Codex thread/turn lifecycle. The two transport subclasses supply discovery and model preparation. There is no additional inference engine or proxy.

The `customServer` action saves and selects a server type, with sends, provider switches, and restarts blocked until reconnection finishes. Legacy provider IDs, runtime homes, credential identities, and preference paths are retained so existing chats and keys remain accessible. `provider.json` remembers the most recent custom type. Old Ollama host/port settings still load; the shared dialog saves a full HTTP/HTTPS URL, including supported Ollama path prefixes and gateway queries. Both strategies disable shell snapshots to keep child-process keys off disk. Run `test_custom_server.py` alongside the existing adapter, controller, runtime, and panel suites.

`OllamaTransport` connects the bundled runtime directly to Ollama's [Responses API](https://docs.ollama.com/api/openai-compatibility). The default endpoint is `http://127.0.0.1:11434`. **Server** in the panel saves an HTTP/HTTPS URL, optional path or query, and optional API key under the `ollama` data folder. The path is a prefix on both discovery and `/v1`. The query is appended to discovery requests and sent to Codex as `query_params`. The key is stored in the system credential store and passed to the conversation runtime as `STEVE_OLLAMA_API_KEY`; thread config records only that variable name. There is no web search and no Code Mode for this provider. Discovery uses `/api/version`, `/api/tags`, and `/api/show`; cloud and non-tool models are excluded. Before a turn, `/api/generate` loads the selected model with its saved settings and `/api/ps` supplies the actual context allocation. The adapter recognizes a reused parent runner for configured model aliases, caps context at the model's reported limit, and reserves at least 2048 tokens or 25% for output. A model/context change refreshes the runtime's thread configuration. Vision checks also apply to steering and tool-delivered images. All provider files use the platform's STEVE data directory, with an `ollama-runtime` home and `ollama` preferences folder.

Developer prerequisites: Python 3.13+, Node.js for the renderer checks, and Fusion for integration testing. End users do not need Python, Node.js, or a separate Codex installation.

```bash
python3 scripts/fetch_runtime.py
python3 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
python3 scripts/smoke_runtime.py
python3 scripts/build_package.py
python3 scripts/verify_package.py
python3 scripts/audit_portability.py
```

Use `py -3.13` in place of `python3` on Windows. Every script defaults to the platform it runs on: the runtime download, package name, installer, and verification follow `host_target()` in `steve/transport.py`. `fetch_runtime.py --target` downloads another platform's runtime for inspection; packages are built and verified on their own platform.

The reproducible build baseline is Codex 0.155.1 per platform (`x86_64-pc-windows-msvc` and `aarch64-apple-darwin`) and verified with SHA-256. Keep the entire package, including the Code Mode host, resources, and package metadata. `steve-runtime.json` records the version and target, and startup refuses a runtime built for another platform. Code Mode is explicitly enabled, with `core`, `conversation`, and `view` kept as direct-call namespaces.

The smoke test uses `.cache/smoke-home`; it checks startup, account reads, model discovery, thread creation, and shutdown without signing in or making an inference request. It does not prove that a ChatGPT conversation works.

Windows builds require the .NET Framework C# compiler and produce `Install STEVE.exe`. macOS builds copy the `Install STEVE.command` shell installer, which performs the same checksum verification, staging, backup, and marker steps and restores executable bits on the runtime. The generated zip contains the installer and the complete payload, with Unix permission bits recorded for Finder. Existing output folders must be renamed before rebuilding. Installer tests run when the package exists and write only to disposable `.cache/installer-tests` fixtures.

`verify_package.py` checks the zip digest, extracts it under `.cache/package-verification`, runs the platform's installer in its test mode into that fixture, compares installed files with the source and checksums, and starts the installed runtime. It never installs into the actual Fusion add-in directory or signs in. The fixture remains available for inspection.

Toolbar PNGs are committed assets. To change the mark, update the SVG and `scripts/generate_icons.py`, then run the latter with Pillow installed.

## GitHub builds and releases

The **Build and release** workflow runs on pushes to `main`, pull requests, and manual dispatch. A Windows job compiles `Install STEVE.exe` and a macOS (Apple silicon) job packages `Install STEVE.command`. Each downloads its checksum-verified runtime baseline, builds and audits the ZIP, runs Python/JavaScript and installer checks, and verifies an installation of the complete package. Successful builds upload both ZIPs and SHA-256 files as Actions artifacts.

Releases are automatic only in `10-X-eng/STEVE`: push a new version to its `main`, and after the build passes the publishing job creates its version tag and a GitHub preview release with the Windows and macOS assets. Fork `main` pushes build artifacts but do not publish releases. Pushes with an already-published version still run checks but skip publishing. Pull requests never publish. The job checks that `main` still matches the tested commit and never moves an existing tag. Publishing uses GitHub's built-in token; no personal token secret is needed. **Run workflow** on upstream `main` is also available to retry a build.

Before the next release, update the add-in and package versions, related installer/documentation version strings, and `docs/RELEASE_NOTES.md`. A version already published must not be reused.

Upstream Codex binaries may contain their vendor's build paths. The portability audit accepts those only when the entire file matches the checksum-pinned upstream archive for the package's target, read from its `steve-runtime.json`. STEVE's own files and modified vendor binaries receive no exception.

## Fusion development loop

The core behavior prompt lives in `steve/tool_protocol.py`. Python calling conventions live in the tool descriptions; CAM discovery, Data Panel search, and cloud insertion recipes are returned on demand by `fusion_api_help` at the API paths named in the prompt. Keep recovery instructions with tool errors rather than repeating them in the core prompt. Start a new conversation after changing tool descriptions so the session uses the current declarations.

1. Open **Scripts and Add-ins** in Fusion.
2. Add the local `addin/STEVE` folder, select STEVE, and run it.
3. Open STEVE from the **Quick Access toolbar** at the top of Fusion in any workspace (also available under Design **Utilities > Add-ins** and command search).
4. Stop the add-in before editing/reloading it. Use Fusion's Edit/Debug integration with VS Code when needed.

The production runtime home is `%LOCALAPPDATA%\STEVE` on Windows and `~/Library/Application Support/STEVE` on macOS. Codex owns credentials under its `codex` subdirectory. Do not copy authentication from another Codex installation. STEVE clears ambient API credentials from the child environment.

STEVE validates the saved ChatGPT account on startup and before opening a new login. It checks again when the palette reopens or regains focus, handles account-change notifications, and polls while sign-in is pending. Browser login uses the runtime's local completion page instead of the hosted ChatGPT desktop handoff. Refresh the account after successful login.

`thread_start_params` is shared by the controller and runtime/package checks. Initialization enables `experimentalApi` for `thread/start.dynamicTools`. The runtime validates and persists the five Fusion tools and two chat-image tools at thread creation. `thread/resume` restores those declarations; it does not accept replacement tools. Start a new chat when changing tool definitions in this prototype. See [execution details](FUSION_EXECUTION.md).

Before launching Codex, startup checks the bundled executable, Code Mode host, resources, and version metadata. Missing or incompatible files produce a setup card with STEVE repair instructions and the official Codex download/setup page.

The embedded page paints its own opaque backgrounds in `panel/fusion.css` because Fusion's host styling may otherwise expose a light body background. Stop and Run STEVE to reload changes; the panel's versioned stylesheet/script URLs also invalidate cached UI assets. Fully restart Fusion only if it retains stale modules.

The panel is plain HTML, CSS and JavaScript loaded from `file://` under a strict CSP; there is no build step. `style.css` holds every color, size and component as tokens on `:root`; `fusion.css` only paints the embedded document because Fusion can supply a light body style. `markdown.js` renders replies (tables, links, nested and task lists, fenced code with a copy button) and highlights Python and JSON; every text run is escaped and only `http(s)` links become anchors, which open through the `openLink` bridge action rather than navigating the panel.

`panel.js` groups the flat message list into turns: the request, then STEVE's replies. Consecutive Python tool calls form one `details.activity` block with a `details.step` row per script. The block stays open while the turn is live and folds into a summary ("Ran N steps in Fusion · 1 failed") when the turn ends; the running step opens its bounded code pane and closes on completion. A `toggle` listener records when the person overrides that automatic state so their choice is kept. Failed steps show the exception text the controller attaches as `error`.

Streaming snapshots are coalesced with `requestAnimationFrame`. Message articles and unchanged Markdown nodes remain mounted; token appends update existing text nodes and attribute changes are patched in place. Controls render only when their state changes. Scrolling follows replies only when the reader is already near the bottom. `node tests/test_panel.cjs` checks the renderer, incremental tree updates and snapshot batching without a browser. `node tests/test_streaming.cjs` adds real DOM, selection, scrolling, activity-block and mutation-count checks when Playwright and Edge are available. For manual browser testing, run it with `--fixture`, serve the repository root, and open `/.cache/streaming-check.html`.

With Playwright and Edge available, `node tests/test_menus.cjs` checks the Settings list and pages, the Conversations view and the composer's **+** menu: keyboard focus, Back/Escape navigation, outside dismissal, mutual exclusion, bridge actions, busy guards, context chips, and layouts from 320 to 760 pixels wide. The gear opens a short Settings list whose rows summarize their current state (provider and account, DFM and RMFG, update availability, logging); each row opens its own page (`.settings-page`) and Back or Escape returns to the list. `showSettings(open, focus, page)` deep-links, which the DFM chip uses to open Manufacturing. The **+** button beside the message box holds Attach images, Dream and jobs. Active context (pinned document, job, DFM) shows as chips above the message box, and the footer is the single status line.

Jobs use `thread/goal/set|get|clear` and the corresponding notifications. STEVE enables `features.goals`, injects the user's objective and pinned context while paused, configures the selected model/effort, then activates the job; Codex starts and continues turns. There is no STEVE retry loop. Stop pauses before interrupting, and job controls remain usable between turns. History loads pause persisted active jobs before `thread/resume`. In-memory Fusion bindings preserve document objects and selections across pauses and chat switches; after restart, explicit Resume captures the active document. Replacement clears the previous job first because runtime 0.153.4 retains accounting on an objective-only update. `tests/test_job_runtime.py` exercises the real runtime against a local inference fixture, including Codex's native goal tools, budgets, continuation, cancellation, replacement, persistence, and inactive history restoration.

Images use native Codex image inputs. File attachments use the browser picker. Image paste is read from the operating-system clipboard through STEVE's palette bridge: an isolated Windows STA helper reads PNG/bitmap formats, and a macOS AppKit helper reads PNG/TIFF. The helpers use built-in OS runtimes, run on a worker, and never read clipboard text or modify clipboard contents. Completion reaches the palette through Fusion's main-thread custom event, separately from streaming state. Both paths use the same browser preparation and attachment previews: at most four images, 2,048 pixels on the longest edge, and 1 MiB per result. Plain text paste remains native. Temporary clipboard files are deleted immediately after reading; pixels are not logged. Python validates the bounded PNG/JPEG/WebP payloads and sends native `image` inputs through `turn/start` or `turn/steer`. The image cache is the `images` folder under the runtime home, named by content hash. Snapshots contain only image IDs and labels; the palette requests bytes separately through `imageAssets` and retains the existing image nodes while text streams. Assets can only be requested for messages in the current conversation. History never fetches remote URLs or reads arbitrary localImage paths for preview. Failed submissions expose **Reuse message**, without automatically repeating a potentially delivered operation.

Image recall uses a durable per-conversation index under `images/chats`, with hashed conversation filenames and content-addressed image files. Only confirmed attachment/steering deliveries and delivered viewport captures enter the index. `list_chat_images` returns up to 20 metadata entries per page; `view_chat_image` checks membership in the active conversation and reinjects the selected pixels through the existing native image-input path. It cannot select another conversation or arbitrary path. Reopened captures are labeled historical; reopening does not add another catalog entry. Cache integrity is checked against the content hash. Missing or damaged files produce an explicit error, and a cache failure after delivery never changes a successful send into a failed send. Viewport caching preserves the existing 8 MiB capture limit; user attachments remain limited to 1 MiB after preparation. Old unindexed images are not scanned or imported automatically. Start a new conversation once after this update to register the image tools; conversations created with these tools retain them when resumed.

Native Windows bitmap/PNG conversion and image-paste bridge/race checks pass automated tests. Actual clipboard paste inside Fusion, macOS clipboard conversion, and the image viewer still require live verification. The JavaScript tests exercise paste dispatch, draft lifetime, preparation errors, async submit races, and asset caching using stand-ins; they do not prove embedded browser clipboard or canvas behavior.

Codex persists new conversations under STEVE's runtime home. The history drawer uses `thread/list` with the STEVE workspace and supported interactive sources, followed by `thread/resume` to restore messages and model context. It loads 30 conversations at a time and searches the loaded titles locally. Closing/reopening the panel preserves the current conversation. Restarting the add-in or reconnecting opens a blank chat; saved conversations remain available through history. ChatGPT sign-in is persisted by Codex. Sessions created by earlier ephemeral builds are not recoverable after their runtime exits. Local history belongs to the operating-system user, not a separate STEVE account or cloud synchronization service.

All installed assets are resolved relative to the add-in. Runtime data uses the current user's `LOCALAPPDATA` or `~/Library/Application Support`, and the installers use Windows' ApplicationData special folder or `$HOME`. Compiler discovery uses PATH or SystemRoot; no drive letter or developer profile is assumed. The package build audits source and the complete zip, including binaries, for the current checkout/profile paths, literal absolute paths in text, and local debugger/bytecode artifacts.

## Structure

### In-Fusion updates

The release checker downloads verified packages for managed installations; applying
them requires the user's **Update & restart STEVE** click. Staging and per-file
hash checks run off Fusion's thread. `update_transaction.py` prepares a sibling
payload and a separate helper under the user's data folder. The helper is linked
through `Application.scripts.addExisting`, stops the exact installed add-in found
by `Scripts.itemByPath`, renames the prepared/previous directories, and calls
`Script.run(False)`. Custom events carry stop/start work back to Fusion's main
thread. It never cancels commands, closes documents, pumps events or quits Fusion.

The controller freezes new requests only at the idle handoff. A nonce/version
startup receipt confirms the replacement loaded; a missing receipt triggers
rollback. The journal and temporary helper support recovery after an interrupted
swap. Current-chat restoration checks the provider/account and leaves jobs paused.
Source checkouts are not package-update targets. The existing external installers
still require Fusion to close for manual installation.

Autodesk references: [Scripts](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Scripts.htm),
[stop](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Script_stop.htm),
[run](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_Script_run.htm).

### Source files

For diagnostics, open **Settings (⚙) → Diagnostics** and enable **Debug logging**. It defaults off and remembers the choice in `debug.json` under the runtime home. **Open logs folder** opens the `logs` folder there in Explorer or Finder; `steve-debug.jsonl` records UTC timestamps, correlated tool requests with generated code, results/errors, duration, transport request timing, and Codex stderr. Rotation keeps the current file and three backups at approximately 2 MiB each. Disabling logging stops new entries and preserves existing files. Authentication RPC payloads are excluded; common credential patterns in diagnostic text are redacted. Code and tool results may contain design details, so review logs before sharing. Logging is local and never automatically uploaded. This toggle controls STEVE's diagnostics, not Codex's existing session history.

- `addin/STEVE/STEVE.py`: Fusion lifecycle, toolbar, palette, custom-event bridge.
- `addin/STEVE/steve/transport.py`: subprocess lifecycle and JSON-RPC.
- `addin/STEVE/steve/controller.py`: account, model, chat, and cancellation state.
- `addin/STEVE/steve/tool_protocol.py`: general Fusion tool declarations, validation, and instructions.
- `addin/STEVE/steve/fusion_tools.py`: main-thread document inspection, API help, and command execution.
- `addin/STEVE/steve/python_runner.py`: generated script entry point, captured output, errors, and cooperative cancellation.
- `addin/STEVE/panel/`: local HTML/CSS/JavaScript interface, with no runtime web dependencies.
- `scripts/installer/Install.cs` and `scripts/installer/Install STEVE.command`: per-user Windows and macOS installers; both validate files before installation and preserve previous versions.
- `scripts/steve_package.py`: package names, installer names, and test-mode installer commands shared by build, verification, and tests.

Codex I/O runs on worker threads. The only Fusion call from those workers is `fireCustomEvent`; Fusion API work and panel updates run in the custom event handler on Fusion's main thread. Palettes are recreated after workspace changes when visible.

## Visual preview

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory addin/STEVE/panel
```

Open `http://127.0.0.1:8765/?preview=welcome` or `?preview=chat`. These pages display an explicit design-preview banner and use sample content. The sign-in button in preview mode only changes the sample UI; it never authenticates. The actual Fusion palette has no preview query parameter.

## macOS notes

Fusion on macOS runs add-ins with its bundled Python (3.14 in Fusion 2705) and renders palettes with Qt WebEngine, so the panel code is shared with Windows; only the paste hint switches to ⌘V. The add-in manifest declares `windows|mac`. Codex runs as a child process in its own process group; on shutdown STEVE closes its stdin, waits briefly, then kills the group so the Code Mode host cannot linger. OpenAI signs and notarizes the macOS Codex binaries, so Gatekeeper accepts the bundled runtime after a browser download; only the unsigned installer script needs Terminal or a Privacy & Security approval. Codex keeps sign-in in `auth.json` under the runtime home on both platforms. `Open logs folder` uses Finder through `open`.

## Official references

- [Fusion add-in creation and manifests](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WritingDebugging_UM.htm)
- [Fusion palettes and their JavaScript bridge](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm)
- [Fusion threading and custom events](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm)
- [Fusion Python debugging](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server)

Current Autodesk docs and the installed Fusion API were inspected on September 19, 2026. Consult the current runtime's protocol when changing the Codex adapter.
