# STEVE

## Your engineering partner inside Autodesk Fusion

**Describe what you want. Build it inside Autodesk Fusion.**

STEVE is an AI engineering assistant that lives in Fusion. Ask it to create a parametric part, inspect an assembly, work with your CAM setup, or find an existing design to build around. Share a reference image, point to geometry, and keep the conversation going while STEVE works.

STEVE writes and runs Python through Fusion's installed API. It can inspect your actual document, make changes, and check the result through queries and viewport images. Its reach includes sketches, solid modeling, assemblies, parameters, manufacturing, and other capabilities exposed by Autodesk's API.

### Shared image gallery

Click the image icon in the top bar to browse, import, rename or attach images. Existing
attachments, viewport captures and Dream concepts appear automatically. Turn on
**Available to STEVE** for references it may find across conversations; images start off.
Turning access off stops future gallery lookup, while pictures already sent stay in their
chats. Start a new chat after updating for STEVE's gallery tools; manual Attach also works
in older chats. Everything is stored locally in STEVE's shared `images` folder.

After updating, **New in STEVE** shows a short, dismissible summary. Reopen it anytime
from **Settings → Updates → What’s new in this version**; it works offline.

Choose **ChatGPT** for your subscription’s Codex access, **Grok / X** for your xAI account’s Grok access, **Claude (experimental)** through your Claude Code subscription login, **OpenRouter (experimental)** for pay-per-use models from many companies, or **Custom server** for Ollama or an OpenAI-compatible Responses API server. The Windows and macOS packages include the conversation runtime, so you can get started without a separate Python, Node.js, or Codex installation. Claude additionally requires the official Claude Code client; OpenRouter requires an account with credits; Ollama requires its local app. Custom servers can use an optional API key stored in the system credential store. No separate STEVE account is required.

For Claude, [install Claude Code](https://code.claude.com/docs/en/setup), run `claude auth login` in a terminal outside Fusion, then choose **Claude (experimental)** in STEVE and **Check connection**. Already signed in? STEVE checks automatically. Your account's models and effort choices appear in the composer. See [Claude setup and limitations](docs/INSTALL.md#claude-subscription-experimental).

> **Preview 0.8.1 · Windows and macOS.** Sign-in and streaming chat have been reported working in Fusion on Windows. The macOS (Apple silicon) package passes the same automated checks, including its bundled runtime, and has been reported working in Fusion on one Mac; its itemized live checks are still being confirmed. See [verification status](docs/VERIFICATION.md) for what has been tested.

## What STEVE can do

### Build and inspect across Fusion

- **Create and modify with Python.** Turn a request into complete operations through Fusion's installed API: sketches, features, components, parameters, assemblies, and supported manufacturing workflows.
- **Query your actual design.** Inspect geometry, measure entities, examine parameters, and verify changes. A dedicated query tool makes reading the document the default when you ask a question.
- **Work with CAM context.** Inspect setups, assigned machines, document tools, and accessible local or cloud tool libraries before choosing how to approach an operation.
- **Find and assemble existing designs.** Search projects and folders accessible through your Autodesk session, identify matching files, and insert selected designs into assemblies through Fusion's API.
- **Read the right documentation.** Search installed API classes and official samples, inspect exact signatures, and fetch Autodesk API references through tools available to every provider.
- **Inspect each Fusion product.** Bounded summaries expose Design structure and feature health, CAM setup and operation state, and the Electronics information available through the installed API.
- **Check measured outcomes.** STEVE can report measured checks and feature-health changes separately from whether its Python completed. Missing coverage and failed checks remain visible.
- **Consider manufacturing (experimental).** Enable **DFM** in the menu and tell STEVE how a part will be made. It can retain per-body process stages and sourced limits, then run measured Python checks with explicit concerns and unknowns. This is an experimental checking workflow, not a certified process-rule library; see [DFM scope and validation](docs/DFM.md).
- **Use the intended machine's capabilities.** Separate [machine definition files](docs/MACHINES.md) supply sourced limits for selected process stages. Definitions are version-bound, with unsupported capabilities left unknown. The catalog covers nominal envelopes for four FDM, resin and polymer SLS printers; additional machines can be added without changing the DFM engine.
- **Optional RMFG sheet-metal checks (experimental).** Connect your supplier account and enable DFM; STEVE automatically uploads the relevant part's STEP snapshot and reads its revision-bound supplier report. Ask for a quote to combine checked parts and quantities in one cart, then choose **Open checkout** to review and pay on RMFG. See [setup, supported geometry and validation limits](docs/RMFG.md).

### Show STEVE what you mean

- **STEVE Dream (experimental).** With ChatGPT selected, choose **+ → Dream a concept image** or ask for one. Refine it in the same chat, use it as a design reference, or save the original to Downloads. Generation uses your Codex limits; no separate image API key is needed. Concepts illustrate intent; Fusion geometry and DFM checks establish dimensions and manufacturability.
- **Selection context, automatically.** Select a face, body, sketch, or component and ask about “this.” Each request includes a snapshot of the selection and Data Panel scope.
- **Paste reference images.** Use **Ctrl+V** (Windows) or **⌘V** (macOS) in the message box, or **+ → Attach images**, to share screenshots, drawings, and visual references. Preview, enlarge, or remove attachments before sending.
- **Images during a task.** Send an image with text, on its own, or as a correction while STEVE is already working. Up to four PNG, JPEG, or WebP images can accompany each message.
- **Visual verification.** STEVE can capture named views and close-ups of a selected entity, then restore your camera. Images complement measurements and other API checks.
- **Revisit earlier pictures.** STEVE can list and reopen saved attachments, generated concepts and viewport captures from the same chat. Images indexed by this version remain available when that chat is reopened; older captures are identified as historical rather than current model state.

### Stay in control of the conversation

- **Steer while it works.** Add a dimension, correct an assumption, or send another reference without waiting for the response to finish. A separate **Stop** button cancels pending work.
- **See what STEVE did in Fusion.** Each run of Python steps folds into one activity block ("Ran 4 steps in Fusion · 1 failed") that stays open while STEVE works and collapses when it is done. Expand any step to read the highlighted script, copy it, or see the exception a failed step raised. The status line under the message box names the current Fusion or saved-image tool. Scripts appear when submitted; the runtime does not stream partial tool arguments.
- **Work toward a job.** Use `/jobs <objective>` for tasks that need multiple turns. Codex manages continuation, completion, and optional token budgets; STEVE provides status, edit, pause, resume, and clear controls.
- **Update without closing Fusion.** Managed installations automatically download and verify new releases on startup and every 12 hours. Choose **Update & restart STEVE** when ready; STEVE waits for idle, replaces its add-in, and reopens the current chat while Fusion stays open. A failed startup restores the previous files. The **Settings (⚙) → Updates** menu also has **Check for updates** and **Open Downloads**.
- **Keep the intended target.** A task retains its original document, product, selection, and Data Panel scope. Later clicks do not silently redirect it. The panel shows which document the task belongs to.
- **Switch documents without losing the task.** Pending Fusion calls wait when another document or one of your commands is active, then resume when the target document is active and your command has finished.
- **Return to old chats.** Browse and search local conversation history, reopen a previous session, and continue where you left off.
- **Choose the model and effort.** Pick from your account's available models and their supported reasoning levels. STEVE remembers your model and a separate effort preference for each model across restarts.
- **Recover failed messages.** Unconfirmed delivery stays visible. **Reuse message** restores the text and image attachments for an explicit retry.

### Built to feel at home in Fusion

STEVE has a dockable dark interface, readable Markdown and code blocks, and incremental streaming that preserves existing message elements as text arrives. Open it from Fusion's **Quick Access toolbar** across workspaces, or through Design **Utilities > Add-ins** and command search.

Click the **Settings (⚙) → Diagnostics** for the remembered **Debug logging** switch and **Open logs folder** action. Optional local diagnostics record generated code, tool results, errors, and timing to help investigate failures.

### Jobs

Choose **+ → Start a job** beside the message box or use these commands. STEVE calls each one a job; Codex still stores it with its [goal workflow](https://learn.chatgpt.com/use-cases/follow-goals):

| Command | Action |
| --- | --- |
| `/jobs <objective>` | Create or replace the job and start working. |
| `/jobs` | Show status, usage, and controls. |
| `/jobs edit` | Edit the objective and optional token budget. Pause running work first. |
| `/jobs pause` | Pause the job and interrupt the current response. |
| `/jobs resume` | Continue the job. |
| `/jobs clear` | Remove the job and stop its work, keeping the chat. |

Jobs belong to individual chats and use the selected provider, model, and effort. The model receives Codex's native `create_goal`, `get_goal`, and `update_goal` tools. **Stop also pauses the job.** A changed objective starts fresh usage tracking; resuming retains usage. After reaching a token limit, increase or remove the budget in job controls before resuming.

Automatic turns keep their Fusion document and selection pinned. STEVE waits while another document or command is active. Within the same Fusion session, resuming a job restores its saved target; a closed target is rejected. Opening a saved chat leaves its job paused. After restarting STEVE, open the intended Fusion document before resuming—the job controls explain that this establishes a new document binding. STEVE and Fusion must remain running for work to continue.

### Grok / X — new in 0.3.0

The **AI provider** selector is available on the sign-in card and under **Settings (⚙) → Provider & account**. Choose **Grok / X**, then **Sign in with X / Grok**, and finish the xAI browser flow. If the browser shows a code for Grok Build after approval, you can return to Fusion: STEVE completes sign-in automatically. A separate device-code option is also available. If your access comes through X, [link your X account to xAI](https://docs.x.ai/grok/faq#accounts--login).

Grok uses the same Fusion Python tools, image inputs, streaming, steering, and saved chat image tools. Provider sign-ins, conversation history, and model preferences are separate; switching is disabled while a task or sign-in is running. Available models, supported effort levels, and defaults come from xAI's live catalog. STEVE remembers your effort choice for each model.

The integration uses xAI OAuth and its public Grok CLI client; STEVE does not require an API key or operate an inference service. xAI controls account eligibility and access. Browser sign-in is user-confirmed on Windows. The local runtime/tool loop and effort forwarding pass automated tests; live Grok modeling and macOS sign-in still need verification.

### OpenRouter (experimental)

Choose **OpenRouter (experimental)**, then **Sign in with OpenRouter**, and approve access in your browser. OpenRouter creates a key labeled STEVE in your account; STEVE stores it in the macOS Keychain or Windows' per-user encryption, and you never copy it. The model picker lists OpenRouter models with tool calling and at least 64K context, grouped by company, with each model's effort levels. Usage is billed to your OpenRouter credits. Tool-calling quality varies by model, and web search is unavailable. See [OpenRouter setup](docs/INSTALL.md#openrouter-experimental).

### Custom server

Choose **Custom server**, open **Server**, and select **Ollama** or **OpenAI-compatible**. Both use the existing Codex runtime, one server dialog, and protected API-key storage. Enter an HTTP or HTTPS server URL and an optional key. Switching types preserves each type's settings, keys, preferences, and chat history.

Ollama defaults to `http://127.0.0.1:11434` and supports path prefixes and gateway queries. STEVE discovers downloaded models with tool support, loads them with their saved context settings, and checks vision capability. Existing Ollama installations keep their settings and chats. See [local setup](docs/INSTALL.md#local-ollama) for the required 8K context setting.

OpenAI-compatible servers must implement the Responses API and tool calling. Enter the API base URL, usually ending in `/v1`. STEVE discovers models through `/models`; see [server setup](docs/INSTALL.md#openai-compatible-server-experimental). Web search is unavailable with custom servers.

## Try asking

> “Create a mounting bracket with adjustable plate thickness and hole spacing.”

> “Inspect this sketch and explain why it is underconstrained.”

> “Use this reference image to help model the enclosure. Ask me for any missing dimensions.”

> “Which machines and tools are available for this CAM setup?”

> “Find the matching housing in this project and insert it into this assembly.”

> “Actually, use 8 mm holes and keep the existing spacing.”

## Install the Windows preview

Get the complete Windows package from [STEVE Releases](https://github.com/10-X-eng/STEVE/releases). If no release is listed yet, developers can [build the package](docs/DEVELOPMENT.md). GitHub's **Source code** download does not include the runtime or installer.

With an `STEVE-0.8.1-windows-x64.zip` package:

1. Extract the entire zip into a folder.
2. Save your work and close Fusion.
3. Double-click **Install STEVE.exe**, then choose **Install STEVE**.
4. Open Fusion. In **Scripts and Add-ins**, enable STEVE if it has not started automatically.
5. Open **STEVE** from the **Quick Access toolbar**.
6. Choose **ChatGPT**, **Grok / X**, or **OpenRouter (experimental)** and sign in, or follow [local Ollama setup](docs/INSTALL.md#local-ollama).

## Install the macOS preview

Get `STEVE-0.8.1-macos-arm64.zip` from [STEVE Releases](https://github.com/10-X-eng/STEVE/releases). It is built for Apple silicon Macs. GitHub's **Source code** download does not include the runtime or installer.

1. Double-click the zip to extract it. Keep the extracted folder together, including `Install STEVE.command`, `SHA256SUMS`, and the `STEVE` folder.
2. Save your work and quit Fusion.
3. Open Terminal, type `bash ` (with a trailing space), drag **Install STEVE.command** into the window, and press Return. Double-clicking the installer also works once macOS lets you open it under **System Settings > Privacy & Security**, because this preview is not signed.
4. Open Fusion. In **Scripts and Add-ins**, enable STEVE if it has not started automatically.
5. Open **STEVE** from the **Quick Access toolbar**.
6. Choose **ChatGPT**, **Grok / X**, or **OpenRouter (experimental)** and sign in, or follow [local Ollama setup](docs/INSTALL.md#local-ollama).

**Upgrading from an earlier name?** Download this release manually. The installer replaces the previous managed add-in folder, and STEVE transfers your saved data on first run with a backup. Older update checkers cannot discover the renamed repository's release.

See the [installation guide](docs/INSTALL.md) for first-use instructions, updates, troubleshooting, and uninstalling on both platforms. Each package also includes `INSTALL.md` and `START HERE.txt`.

STEVE checks for a saved sign-in before opening a new login. Model availability and usage limits depend on the selected provider and your account's access.

The preview supports **Windows x64** and **macOS on Apple silicon**, and requires Fusion and an internet connection. The installers are currently unsigned. They install per user, preserve the previous managed installation during updates, and refuse to replace a STEVE folder they did not install.

Codex updates independently of STEVE. Click the **Settings (⚙) → Updates** to see the running Codex version. STEVE checks OpenAI for stable updates automatically. Choose **Update Codex** to download and verify the complete runtime in the background, then click **Restart STEVE** in the same menu to activate it and reopen your chat. Fusion stays open. Your current task keeps its existing runtime until restart. **Refresh models** reloads the ChatGPT model picker from Codex; availability depends on your account. **Use bundled Codex** selects the included runtime for the next restart if you need to recover from an update.

To reload an updated development add-in, **Stop STEVE, then Run it again** in Scripts and Add-ins. Start a **New conversation** after changes to tool definitions.

## How STEVE works

```text
Your request, selection, and reference images
                    ↓
STEVE's dockable panel inside Fusion
                    ↓
Local Codex app-server with Code Mode
                    ↓
Fusion inspection, API help, Python operations, and viewport capture
                    ↓
Results returned to the conversation
```

Codex handles ChatGPT authentication, model access, inference, and persistent conversations. STEVE connects that conversation to five Fusion tools—document inspection, Python queries, Python execution, installed API help, and viewport capture—and two tools for listing and reopening saved chat images. Runtime communication stays off Fusion's main thread; document operations run on the main thread through Autodesk's supported event mechanism.

Modeling commands request grouped Undo through Fusion's command transactions. Errors return concrete recovery guidance, and oversized results return bounded previews so the model can narrow a query without repeating a modifying operation just to recover its output. The bridge also includes cancellation and document-target checks.

See the [execution bridge](docs/FUSION_EXECUTION.md) for tool contracts, Undo behavior, and safeguards.

## Your account and data

Conversation content, attached images, and requested Fusion tool results travel through the local Codex runtime to your selected provider: OpenAI for ChatGPT, xAI for Grok, Anthropic for Claude, OpenRouter and the model's provider for OpenRouter, or the configured custom server for Ollama and OpenAI-compatible models. STEVE does not operate an AI proxy or manage separate AI billing. Codex manages authentication locally; STEVE does not copy credentials from another installation or inherit API keys from the environment.

History, preferences, image caches, and optional logs live under the current user's STEVE data folder: `%LOCALAPPDATA%\STEVE` on Windows and `~/Library/Application Support/STEVE` on macOS. History is local to STEVE and does not sync with the ChatGPT website. Signing out hides conversations without deleting local files. Debug logs may contain design details and are never automatically uploaded by STEVE.

Attached images are prepared locally before sending, with a maximum longest edge of 2,048 pixels and compression when needed to stay under 1 MiB per image. They are sent only when you press Send. Image previews load separately from streaming text updates. Saved chats show previews when their native history includes the image data.

Closing and reopening the panel keeps the conversation. Restarting STEVE or reconnecting opens a blank chat while retaining saved sign-in and history; use **Chat history** to resume a previous session.

## Preview boundaries

STEVE's coverage follows Autodesk's installed Python API; some Fusion UI features have no exposed API. Generated code runs with Fusion's process privileges. Save your work before trying changes: command grouping and recovery guidance cannot guarantee rollback or prevent every native Fusion failure.

Fusion API calls share its main thread. Long native calculations can block the UI and cannot be forcibly interrupted by STEVE's Stop button. A task waits while another document is active; it does not continuously model in a background document. There is currently one active conversation across the Fusion instance, rather than independent sessions per document.

Live testing of image paste, generated modeling and CAM operations, Undo, document switching, and clean-machine installation is still underway. See [verification status](docs/VERIFICATION.md).

## Development and contributions

See [development setup](docs/DEVELOPMENT.md) for runtime download, Fusion loading, testing, packaging, and the browser preview.

```bash
python3 scripts/fetch_runtime.py
python3 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
python3 scripts/smoke_runtime.py
python3 scripts/build_package.py
python3 scripts/verify_package.py
```

Use `py -3.13` in place of `python3` on Windows. Each script targets the platform it runs on. Release builds include a reproducible Codex baseline verified against its SHA-256 digest. That build baseline does not restrict independent Codex updates: newer stable runtimes can be installed from **Settings (⚙) → Updates** without a STEVE version change. Source and release audits check for machine-specific paths. Runtime licensing is documented in [licenses](licenses/README.md).

Bring a real Fusion task, a reproducible failure, or a workflow you want to improve. Include the relevant Fusion version and, when useful, reviewed debug logs with private design information removed.

STEVE is an independent project and is not affiliated with or endorsed by Autodesk or OpenAI.

## License

STEVE's source code and documentation are available under the [MIT License](LICENSE), copyright 2026 10-X-eng and STEVE contributors. Bundled third-party components retain their own licenses; see [third-party licensing](licenses/README.md).
