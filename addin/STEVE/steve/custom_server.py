"""Shared settings, HTTP boundaries and Codex Responses transport for custom servers."""
import copy
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .secure_store import SecureStore
from .tool_protocol import FUSION_QUICK_REFERENCE
from .transport import Transport, data_home


def normalize_api_key(value):
    """Blank keeps the saved key; never accept header or control characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Enter the API key as text, or leave it blank.")
    if len(value) > 4096:
        raise ValueError("That API key is too long.")
    value = value.strip()
    if not value:
        return None
    if any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("The API key cannot include spaces or control characters.")
    return value


def normalize_base_url(value):
    if not isinstance(value, str):
        raise ValueError("Enter the server's base URL, such as http://127.0.0.1:1234/v1.")
    value = value.strip().rstrip("/")
    if not value or len(value) > 512 or "\\" in value or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Enter a valid server base URL without spaces or control characters.")
    try:
        parts = urlsplit(value)
        if parts.port == 0:
            raise ValueError()
    except ValueError:
        raise ValueError("That base URL is not valid. Use a port from 1 to 65535.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The base URL must start with http:// or https://.")
    if "@" in parts.netloc or "?" in value or "#" in value:
        raise ValueError("Put only the base URL here, without credentials, ? or #. Put the key in the API key field.")
    return value


class SameOriginRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        def origin(url):
            parts = urlsplit(url)
            return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        if origin(req.full_url) != origin(newurl):
            # urllib otherwise forwards Authorization, even to an unrelated host or an HTTP downgrade.
            raise HTTPError(req.full_url, code, "Cross-origin server redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def server_opener():
    return build_opener(ProxyHandler({}), SameOriginRedirects())


class ServerSettings:
    """Reuse existing credential identities and metadata files without moving secrets."""
    def __init__(self, home, folder, store_name, store=None):
        self.home = Path(home) / folder
        self.path = self.home / "endpoint.json"
        self.store_name = store_name
        self.api_key_set = False
        self.generation = 0
        self._secret = None
        self._store = store

    @property
    def store(self):
        if self._store is None:
            self._store = SecureStore(self.home, self.store_name)
        return self._store

    @property
    def api_key(self):
        if not self.api_key_set:
            return ""
        if self._secret is None:
            secret = (self.store.read() or {}).get("apiKey", "")
            self._secret = secret if isinstance(secret, str) else ""
        return self._secret

    def save_endpoint(self, metadata, api_key=None, clear_api_key=False):
        secret = "" if clear_api_key else normalize_api_key(api_key)
        key_set = False if clear_api_key else bool(secret) or self.api_key_set
        if secret is not None and (secret or self.api_key_set or self._store is not None):
            self.store.write({"apiKey": secret})
        self.home.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.home, 0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({**metadata, "apiKeySet": key_set}), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        self.api_key_set = key_set
        if secret is not None:
            self._secret = secret
        self.generation += 1


def responses_config(provider, name, base_url, context, *, env_key=None, query=None, compact_limit=None):
    config = {"model_provider": provider, f"model_providers.{provider}.name": name,
              f"model_providers.{provider}.base_url": base_url,
              f"model_providers.{provider}.requires_openai_auth": False,
              f"model_providers.{provider}.wire_api": "responses",
              f"model_providers.{provider}.supports_websockets": False,
              "model_context_window": context,
              "model_auto_compact_token_limit": compact_limit or context - max(2048, context // 4),
              "model_supports_reasoning_summaries": False, "web_search": "disabled",
              "features.shell_snapshot": False,
              "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]}}
    if env_key:
        config[f"model_providers.{provider}.env_key"] = env_key
    if query:
        config[f"model_providers.{provider}.query_params"] = dict(query)
    return config


class CustomServerTransport(Transport):
    """One runtime lifecycle; subclasses supply discovery and model preparation only.

    Provider IDs and runtime homes remain stable so existing chats can be resumed.
    """
    def __init__(self, on_event, home=None, command=None):
        super().__init__(on_event, home=Path(home or data_home()) / self.runtime_folder, command=command)
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
        env.pop(self.api_key_env, None)
        if self._api_key():
            env[self.api_key_env] = self._api_key()
        return env

    def _remember(self, thread_id, prepared):
        self.threads[thread_id] = {"prepared": prepared, "endpoint": self._endpoint_signature()}

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            return self.read_account()
        if method.startswith("account/"):
            raise self.error_type("Custom servers need no sign-in. Set the server URL and optional API key under Server.")
        if method == "model/list":
            result = self.models()
            self.catalog = {m["id"]: m for m in result["data"]}
            self.default_model = next((m["id"] for m in result["data"] if m["isDefault"]), None)
            return result
        if method == "thread/list":
            params["modelProviders"] = [self.provider_id]
        if method in ("thread/start", "thread/resume"):
            model = params.get("model")
            if not model and method == "thread/resume":
                saved = super().request("thread/read", {"threadId": params["threadId"], "includeTurns": False})
                model = saved.get("thread", {}).get("model")
            if not model and not self.default_model:
                self.request("model/list")
            model = model or self.default_model
            if not model:
                raise self.error_type("The server lists no usable models. Load a model, then choose Refresh models.")
            prepared = self.prepare(model)
            params["model"] = model
            params.setdefault("config", {}).update(self.provider_config(prepared))
            params["baseInstructions"] = params.get("baseInstructions", "") + (
                "\nThis is a custom server session. Web search is unavailable. Use fusion_api_help and "
                "fusion_fetch_docs for Fusion API documentation. Keep tool results small." + FUSION_QUICK_REFERENCE)
            result = super().request(method, params, **kwargs)
            self._remember(result["thread"]["id"], prepared)
            return result
        if method == "turn/start":
            record = self.threads.get(params["threadId"]) or {}
            previous = record.get("prepared") or {}
            model = params.get("model") or previous.get("model") or self.default_model
            prepared = self.prepare(model)
            if previous != prepared or record.get("endpoint") != self._endpoint_signature():
                super().request("thread/resume", {"threadId": params["threadId"], "model": model,
                                                "config": self.provider_config(prepared)})
                self._remember(params["threadId"], prepared)
            params["model"] = model
        if method in ("turn/start", "turn/steer"):
            prepared = (self.threads.get(params["threadId"]) or {}).get("prepared") or {}
            if prepared.get("vision") is False and any(item.get("type") in ("image", "localImage") for item in params.get("input", [])):
                raise self.error_type("This model cannot read images. Select a model with vision support, then resend the image.")
        return super().request(method, params, **kwargs)
