"""Any OpenAI-compatible server that serves the Responses API, reached by base URL and optional API key."""
import copy
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .ollama_transport import normalize_api_key
from .secure_store import SecureStore
from .transport import Transport, data_home

PROVIDER = "steve_openai_compat"
API_KEY_ENV = "STEVE_OPENAI_COMPAT_API_KEY"
MAX_METADATA = 4 * 1024 * 1024
# Used when /models does not report a context window.
FALLBACK_CONTEXT = 32768


class OpenAICompatError(RuntimeError):
    pass


def normalize_base_url(value):
    """http(s) origin plus optional path, such as http://127.0.0.1:1234/v1. No credentials, query, or fragment."""
    if not isinstance(value, str):
        raise ValueError("Enter the server's base URL, such as http://127.0.0.1:1234/v1.")
    value = value.strip().rstrip("/")
    if not value or len(value) > 512 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Enter the server's base URL, such as http://127.0.0.1:1234/v1.")
    try:
        parts = urlsplit(value)
        parts.port
    except ValueError:
        raise ValueError("That base URL is not valid. Use a form such as http://127.0.0.1:1234/v1.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The base URL must start with http:// or https://.")
    if "@" in parts.netloc or parts.query or parts.fragment or "?" in value or "#" in value:
        raise ValueError("Put only the base URL here, without credentials, ? or #. Put the key in the API key field.")
    return value


class OpenAICompatSettings:
    """Base URL and an optional API key. The key stays in the system credential store."""

    def __init__(self, home, store=None):
        self.home = Path(home) / "openai-compat"
        self.path = self.home / "endpoint.json"
        self.base_url = ""
        self.api_key_set = False
        self.generation = 0
        self._secret = None
        self._store = store
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            self.base_url = normalize_base_url(value.get("baseUrl"))
            self.api_key_set = value.get("apiKeySet") is True
        except (OSError, ValueError, AttributeError):
            pass

    def __repr__(self):
        return f"OpenAICompatSettings(base_url={self.base_url!r}, api_key_set={self.api_key_set})"

    def public_state(self):
        return {"openaiBaseUrl": self.base_url, "openaiApiKeySet": self.api_key_set}

    @property
    def store(self):
        if self._store is None:
            self._store = SecureStore(self.home, "openai-compat-key")
        return self._store

    @property
    def api_key(self):
        if not self.api_key_set:
            return ""
        if self._secret is None:
            secret = (self.store.read() or {}).get("apiKey", "")
            self._secret = secret if isinstance(secret, str) else ""
        return self._secret

    def save(self, base_url, api_key=None, clear_api_key=False):
        base_url = normalize_base_url(base_url)
        api_key = None if clear_api_key else normalize_api_key(api_key)
        secret = "" if clear_api_key else api_key
        key_set = False if clear_api_key else bool(api_key) or self.api_key_set
        if secret is not None and (secret or self.api_key_set):
            self.store.write({"apiKey": secret})
        self.home.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.home, 0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"baseUrl": base_url, "apiKeySet": key_set}), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        self.base_url, self.api_key_set = base_url, key_set
        if secret is not None:
            self._secret = secret
        self.generation += 1


def catalog(payload):
    models = []
    for item in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
        name = item.get("id") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue
        context = next((item[k] for k in ("context_length", "max_model_len", "context_window")
                        if isinstance(item.get(k), int) and not isinstance(item.get(k), bool) and item[k] > 0), 0)
        models.append({"id": name, "model": name, "displayName": name, "context": context or FALLBACK_CONTEXT,
                       "defaultReasoningEffort": "", "supportedReasoningEfforts": []})
    models.sort(key=lambda m: m["id"].lower())
    for index, model in enumerate(models):
        model["isDefault"] = index == 0
    return {"data": models}


class OpenAICompatTransport(Transport):
    def __init__(self, on_event, home=None, command=None):
        super().__init__(on_event, home=Path(home or data_home()) / "openai-compat-runtime", command=command)
        # Reach the configured server directly. A system HTTP proxy must not see the key.
        self.opener = build_opener(ProxyHandler({}))
        self.settings = None
        self.catalog = {}
        self.default_model = None
        self.threads = {}

    def use(self, settings):
        self.settings = settings

    def _api_key(self):
        return self.settings.api_key if self.settings is not None and self.settings.api_key_set else ""

    def environment(self):
        env = super().environment()
        env.pop(API_KEY_ENV, None)
        key = self._api_key()
        if key:
            env[API_KEY_ENV] = key
        return env

    def models(self):
        if self.settings is None or not self.settings.base_url:
            raise OpenAICompatError("Set the server's base URL under Server, then refresh models.")
        headers = {"Accept": "application/json", "User-Agent": "STEVE"}
        if self._api_key():
            headers["Authorization"] = "Bearer " + self._api_key()
        try:
            with self.opener.open(Request(self.settings.base_url + "/models", headers=headers), timeout=10) as response:
                raw = response.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise ValueError("Too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Expected object")
        except HTTPError as exc:
            exc.close()
            # Never expose response bodies, keys, or request headers.
            raise OpenAICompatError("The server rejected the API key. Check it under Server." if exc.code in (401, 403)
                                    else f"The server answered {exc.code} for /models. Check the base URL under Server.") from None
        except (URLError, OSError):
            raise OpenAICompatError(f"Cannot reach {self.settings.base_url}. Start the server or check the base URL under Server.") from None
        except ValueError:
            raise OpenAICompatError("The server returned an invalid model list. Check the base URL ends with /v1.") from None
        return catalog(payload)

    def config(self, model):
        context = (self.catalog.get(model) or {}).get("context") or FALLBACK_CONTEXT
        config = {"model_provider": PROVIDER, f"model_providers.{PROVIDER}.name": "OpenAI-compatible",
                  f"model_providers.{PROVIDER}.base_url": self.settings.base_url,
                  f"model_providers.{PROVIDER}.requires_openai_auth": False,
                  f"model_providers.{PROVIDER}.wire_api": "responses",
                  f"model_providers.{PROVIDER}.supports_websockets": False,
                  "model_context_window": context, "model_auto_compact_token_limit": context * 4 // 5,
                  "model_supports_reasoning_summaries": False, "web_search": "disabled",
                  "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]}}
        if self._api_key():
            # Codex reads the key from the child environment per request; it never enters thread config.
            config[f"model_providers.{PROVIDER}.env_key"] = API_KEY_ENV
        return config

    def _signature(self):
        return (self.settings.base_url, bool(self._api_key()), self.settings.generation)

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            try:
                found = bool(self.models()["data"])
            except OpenAICompatError as exc:
                return {"account": None, "localStatus": str(exc)}
            base = self.settings.base_url
            return {"account": {"type": "openai", "id": hashlib.sha256(base.encode()).hexdigest()[:24],
                                "email": urlsplit(base).netloc, "planType": "OpenAI-compatible"},
                    "localStatus": f"Connected to {base}." if found else f"No models found at {base}."}
        if method.startswith("account/"):
            raise OpenAICompatError("OpenAI-compatible servers need no sign-in. Set the base URL and API key under Server.")
        if method == "model/list":
            result = self.models()
            self.catalog = {m["id"]: m for m in result["data"]}
            self.default_model = next((m["id"] for m in result["data"] if m["isDefault"]), None)
            return result
        if method == "thread/list":
            params["modelProviders"] = [PROVIDER]
        if method in ("thread/start", "thread/resume"):
            if not self.catalog:
                self.request("model/list")
            model = params.get("model")
            if not model and method == "thread/resume":
                saved = super().request("thread/read", {"threadId": params["threadId"], "includeTurns": False})
                model = saved.get("thread", {}).get("model")
            model = model or self.default_model
            if not model:
                raise OpenAICompatError("The server lists no models. Load a model, then choose Refresh models.")
            params["model"] = model
            params.setdefault("config", {}).update(self.config(model))
            params["baseInstructions"] = params.get("baseInstructions", "") + "\nThis is an OpenAI-compatible server session. Web search is unavailable. Use fusion_api_help and fusion_fetch_docs for Fusion API documentation."
            result = super().request(method, params, **kwargs)
            self.threads[result["thread"]["id"]] = (model, self._signature())
            return result
        if method == "turn/start":
            model = params.get("model") or (self.threads.get(params["threadId"]) or (None,))[0] or self.default_model
            if (model, self._signature()) != self.threads.get(params["threadId"]):
                # Context limits and the server are thread settings; apply them before the next request.
                super().request("thread/resume", {"threadId": params["threadId"], "model": model, "config": self.config(model)})
                self.threads[params["threadId"]] = (model, self._signature())
            params["model"] = model
        return super().request(method, params, **kwargs)
