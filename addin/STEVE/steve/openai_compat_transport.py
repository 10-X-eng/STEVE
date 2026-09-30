"""Any OpenAI-compatible server that serves the Responses API, reached by base URL and optional API key."""
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from .custom_server import (CustomServerTransport, ServerSettings, normalize_base_url,
                            responses_config, server_opener)

PROVIDER = "steve_openai_compat"
API_KEY_ENV = "STEVE_OPENAI_COMPAT_API_KEY"
MAX_METADATA = 4 * 1024 * 1024
# Used when /models does not report a context window.
FALLBACK_CONTEXT = 32768


class OpenAICompatError(RuntimeError):
    pass


class OpenAICompatSettings(ServerSettings):
    """Base URL and an optional API key. The key stays in the system credential store."""

    def __init__(self, home, store=None):
        super().__init__(home, "openai-compat", "openai-compat-key", store)
        self.base_url = ""
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

    def save(self, base_url, api_key=None, clear_api_key=False):
        base_url = normalize_base_url(base_url)
        self.save_endpoint({"baseUrl": base_url}, api_key, clear_api_key)
        self.base_url = base_url


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


class OpenAICompatTransport(CustomServerTransport):
    provider_id = PROVIDER
    runtime_folder = "openai-compat-runtime"
    api_key_env = API_KEY_ENV
    error_type = OpenAICompatError

    def __init__(self, on_event, home=None, command=None):
        super().__init__(on_event, home=home, command=command)
        self.opener = server_opener()

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
            if 300 <= exc.code < 400:
                raise OpenAICompatError("The server redirected to a different origin. Enter its direct URL under Server.") from None
            # Never expose response bodies, keys, or request headers.
            raise OpenAICompatError("The server rejected the API key. Check it under Server." if exc.code in (401, 403)
                                    else f"The server answered {exc.code} for /models. Check the base URL under Server.") from None
        except (URLError, OSError):
            raise OpenAICompatError(f"Cannot reach {self.settings.base_url}. Start the server or check the base URL under Server.") from None
        except ValueError:
            raise OpenAICompatError("The server returned an invalid model list. Check the base URL ends with /v1.") from None
        return catalog(payload)

    def prepare(self, model):
        if not self.catalog:
            self.request("model/list")
        info = self.catalog.get(model) or {}
        return {"model": model, "context": info.get("context") or FALLBACK_CONTEXT,
                "vision": info.get("supportsImages")}

    def provider_config(self, prepared):
        context = prepared["context"]
        return responses_config(PROVIDER, "OpenAI-compatible", self.settings.base_url, context,
                                env_key=API_KEY_ENV if self._api_key() else None,
                                compact_limit=context * 4 // 5)

    def _endpoint_signature(self):
        return (self.settings.base_url, bool(self._api_key()), self.settings.generation)

    def read_account(self):
        try:
            found = len(self.models()["data"])
        except OpenAICompatError as exc:
            return {"account": None, "localStatus": str(exc)}
        base = self.settings.base_url
        return {"account": {"type": "openai", "id": hashlib.sha256(base.encode()).hexdigest()[:24],
                            "email": urlsplit(base).netloc, "planType": "OpenAI-compatible"},
                "localStatus": f"Connected to {base} · {found} model{'s' * (found != 1)}." if found else f"No models found at {base}."}
