"""Local Ollama discovery and the bundled conversation runtime's Responses provider."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .secure_store import SecureStore
from .tool_protocol import FUSION_QUICK_REFERENCE
from .transport import Transport, data_home

BASE_URL = "http://127.0.0.1:11434"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11434
API_KEY_ENV = "STEVE_OLLAMA_API_KEY"
MAX_METADATA = 4 * 1024 * 1024
MIN_CONTEXT = 8192
_HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$")
_URL_TOKEN = re.compile(r"[A-Za-z0-9._~-]+")
_QUERY_VALUE = re.compile(r"[A-Za-z0-9._~-]*")


class OllamaError(RuntimeError):
    pass


class UnsupportedModel(OllamaError):
    pass


def cloud_name(model):
    return ":cloud" in model.lower() or model.lower().endswith("-cloud")


def format_host(host):
    """Bracket IPv6 so it can sit in an http origin beside the port."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return str(address)


def normalize_port(port):
    if port is None or port == "":
        return DEFAULT_PORT
    if isinstance(port, str):
        port = port.strip()
        if not port.isdigit():
            raise ValueError("Enter a port from 1 to 65535, or leave it blank for 11434.")
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Enter a port from 1 to 65535, or leave it blank for 11434.")
    return port


def normalize_endpoint(host, port):
    """Accept a host name or IP, and an optional port. Reject pasted URLs and credentials."""
    if not isinstance(host, str):
        raise ValueError("Enter a host name or IP address, and put the port in the port field.")
    host = host.strip()
    if host.endswith("."):
        host = host[:-1]
    if (not host or any(character.isspace() for character in host) or "://" in host or "/" in host
            or "\\" in host or "@" in host or "?" in host or "#" in host):
        raise ValueError("Enter a host name or IP address, and put the port in the port field.")
    if host.startswith("[") and "]" in host and host.find("]") != len(host) - 1:
        raise ValueError("Enter only the host in the host field, and put the port in the port field.")
    if host.count(":") == 1 and not host.startswith("["):
        _, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            raise ValueError("Enter only the host in the host field, and put the port in the port field.")
    bracketed = host.startswith("[") and host.endswith("]")
    bare = host[1:-1] if bracketed else host
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        lowered = host.lower()
        try:
            ascii_host = lowered.encode("idna").decode("ascii")
        except UnicodeError:
            ascii_host = ""
        if bracketed or ":" in lowered or not _HOSTNAME.fullmatch(ascii_host) or len(lowered) > 253:
            raise ValueError("Enter a host name or IP address, and put the port in the port field.") from None
        canonical = lowered
    else:
        canonical = address.compressed if isinstance(address, ipaddress.IPv6Address) else str(address)
    return canonical, normalize_port(port)


def normalize_url_extra(value):
    """Optional path prefix and query. Blank keeps the normal /api and /v1 routes."""
    if value is None:
        return "", {}, ""
    if not isinstance(value, str):
        raise ValueError("Enter a URL path or query, or leave it blank.")
    value = value.strip()
    if not value or value in ("/", "?"):
        return "", {}, ""
    if len(value) > 512:
        raise ValueError("That URL path is too long.")
    if ("://" in value or value.startswith("//") or "@" in value or "\\" in value or "#" in value
            or any(ord(character) < 33 or ord(character) == 127 for character in value)):
        raise ValueError("Enter a path or query, such as /ollama or ?think=false. Host and port stay in their own fields.")
    if not value.startswith("/") and not value.startswith("?"):
        raise ValueError("Start the URL path with / or ?, such as /ollama or ?think=false.")
    path, _, query_text = value.partition("?")
    path = path.rstrip("/")
    if path:
        parts = path.split("/")
        if parts[0] != "" or any(part in ("", ".", "..") or not _URL_TOKEN.fullmatch(part) for part in parts[1:]):
            raise ValueError("Use a URL path such as /ollama. Avoid spaces, .., and a trailing slash.")
    query = {}
    if query_text:
        try:
            pairs = parse_qsl(query_text, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise ValueError("That query is not valid. Use a form such as ?think=false.") from None
        if len(pairs) > 8:
            raise ValueError("Use at most 8 query parameters.")
        for key, item in pairs:
            if key in query:
                raise ValueError("Use each query name once.")
            if not key or len(key) > 64 or not _URL_TOKEN.fullmatch(key) or len(item) > 256 or not _QUERY_VALUE.fullmatch(item):
                raise ValueError("Query names and values can use letters, numbers, and . _ ~ -. Put secrets in the API key field.")
            query[key] = item
    canonical = path + ("?" + urlencode(query) if query else "")
    return path, query, canonical


def normalize_api_key(value):
    """Blank means leave the saved key unchanged. Never accept header or control characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Enter the API key as text, or leave it blank.")
    if len(value) > 4096:
        raise ValueError("That API key is too long.")
    value = value.strip()
    if not value:
        return None
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValueError("The API key cannot include spaces or control characters.")
    return value


def active_origin(settings):
    """Saved servers use their own origin. The default still follows BASE_URL for tests."""
    if settings is not None and settings.explicit:
        return settings.origin()
    return BASE_URL


def service_url(settings, suffix):
    if settings is not None and settings.explicit:
        return settings.request_url(suffix)
    return active_origin(settings) + suffix


def server_label(settings):
    if settings is not None:
        return settings.label
    return BASE_URL.removeprefix("http://")


def connection_status(settings, models_found):
    label = server_label(settings)
    if not models_found:
        return f"No models with tool support found at {label}. Download a model, then refresh."
    if settings is not None and settings.api_key_set:
        return f"Connected to {label}."
    return f"Connected to {label}. No sign-in needed."


class OllamaSettings:
    """Host, port, and an optional API key. The key stays in the system credential store."""

    def __init__(self, home, store=None):
        self.home = Path(home) / "ollama"
        self.path = self.home / "endpoint.json"
        self.host = DEFAULT_HOST
        self.port = DEFAULT_PORT
        self.prefix = ""
        self.query = {}
        self.url = ""
        self.explicit = False
        self.api_key_set = False
        self.generation = 0
        self._secret = None
        self._store = store
        self._load()

    def __repr__(self):
        return f"OllamaSettings(host={self.host!r}, port={self.port}, api_key_set={self.api_key_set})"

    @property
    def label(self):
        return f"{format_host(self.host)}:{self.port}{self.url}"

    def origin(self):
        return f"http://{format_host(self.host)}:{self.port}{self.prefix}"

    def request_url(self, suffix):
        url = self.origin() + suffix
        if self.query:
            url += "?" + urlencode(self.query)
        return url

    def public_state(self):
        return {"ollamaHost": self.host, "ollamaPort": self.port, "ollamaAddress": self.label,
                "ollamaUrl": self.url, "ollamaApiKeySet": self.api_key_set}

    @property
    def store(self):
        if self._store is None:
            self._store = SecureStore(self.home, "ollama-key")
        return self._store

    @property
    def api_key(self):
        if not self.api_key_set:
            return ""
        if self._secret is None:
            record = self.store.read() or {}
            secret = record.get("apiKey", "")
            self._secret = secret if isinstance(secret, str) else ""
        return self._secret

    def _load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(value, dict):
            return
        try:
            host, port = normalize_endpoint(value.get("host"), value.get("port"))
        except (TypeError, ValueError):
            return
        self.host, self.port = host, port
        self.api_key_set = value.get("apiKeySet") is True
        self.explicit = True
        try:
            self.prefix, self.query, self.url = normalize_url_extra(value.get("url") if isinstance(value.get("url"), str) else "")
        except ValueError:
            self.prefix, self.query, self.url = "", {}, ""

    def _write(self, host, port, key_set, url):
        self.home.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.home, 0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"host": host, "port": port, "apiKeySet": bool(key_set), "url": url}), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def save(self, host, port=None, api_key=None, clear_api_key=False, url=""):
        host, port = normalize_endpoint(host, port)
        prefix, query, canonical = normalize_url_extra(url)
        if not clear_api_key and api_key is not None:
            api_key = normalize_api_key(api_key)
        stored_secret = None
        key_set = self.api_key_set
        if clear_api_key:
            stored_secret = ""
            key_set = False
        elif api_key:
            stored_secret = api_key
            key_set = True
        if stored_secret is not None and (stored_secret or self.api_key_set or self._store is not None):
            self.store.write({"apiKey": stored_secret})
        self._write(host, port, key_set, canonical)
        self.host, self.port = host, port
        self.prefix, self.query, self.url = prefix, query, canonical
        self.explicit = True
        self.api_key_set = key_set
        self.generation += 1
        if stored_secret is not None:
            self._secret = stored_secret


class OllamaAPI:
    def __init__(self, settings=None):
        # Reach the configured server directly. A system HTTP proxy must not see model metadata.
        self.opener = build_opener(ProxyHandler({}))
        self.settings = settings

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.settings is not None and self.settings.api_key_set:
            key = self.settings.api_key
            if key:
                headers["Authorization"] = "Bearer " + key
        return headers

    def request(self, path, body=None, timeout=5):
        request = Request(service_url(self.settings, path), data=json.dumps(body).encode() if body is not None else None,
                          headers=self._headers())
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise OllamaError("Ollama returned too much model metadata. Update Ollama, then refresh models.")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError("Invalid model metadata")
            return result
        except HTTPError as exc:
            exc.close()
            raise OllamaError("Ollama could not load the requested model. Check that it is downloaded and fits in memory, then refresh models.") from exc
        except TimeoutError as exc:
            raise OllamaError("Ollama took too long to respond. Check available memory or choose a smaller model, then retry.") from exc
        except (URLError, OSError) as exc:
            raise OllamaError(f"Cannot reach Ollama at {server_label(self.settings)}. Start the Ollama app, or check the host and port under Server, then choose Refresh models.") from exc
        except (ValueError, TypeError) as exc:
            raise OllamaError("Ollama returned invalid model information. Update Ollama, then refresh models.") from exc

    def inspect(self, model):
        info = self.request("/api/show", {"model": model})
        if info.get("remote_model") or info.get("remote_host") or cloud_name(model):
            raise UnsupportedModel("Choose a downloaded local model. STEVE's Ollama provider does not use cloud models.")
        capabilities = info.get("capabilities") or []
        if "tools" not in capabilities or "completion" not in capabilities:
            raise UnsupportedModel("This model does not support tool calling. Download a model with tools support, then refresh models.")
        return info

    def models(self):
        models = []
        for entry in self.request("/api/tags").get("models", []):
            name = entry.get("name", "")
            if not isinstance(name, str) or not name or cloud_name(name):
                continue
            try:
                info = self.inspect(name)
            except UnsupportedModel:
                continue
            configured = re.search(r"(?m)^num_ctx\s+(\d+)", info.get("parameters", ""))
            models.append({"id": name, "model": name, "displayName": name,
                           "defaultReasoningEffort": "", "supportedReasoningEfforts": [],
                           "supportsImages": "vision" in info["capabilities"],
                           "configuredContext": int(configured[1]) if configured else 0,
                           "size": entry.get("size", 0)})
        models.sort(key=lambda m: (m["configuredContext"] < MIN_CONTEXT, m["size"], m["id"]))
        for index, model in enumerate(models):
            model["isDefault"] = index == 0
        return {"data": models}

    def prepare(self, model):
        info = self.inspect(model)
        # Use the model's saved settings. A temporary num_ctx override is lost on /v1/responses.
        self.request("/api/generate", {"model": model, "stream": False, "keep_alive": "5m"}, timeout=180)
        running_models = self.request("/api/ps").get("models", [])
        running = next((m for m in running_models if model in (m.get("name"), m.get("model"))), None)
        if running is None:
            # Ollama reuses a loaded parent's runner for aliases with the same weights/settings.
            parent = (info.get("details") or {}).get("parent_model")
            running = next((m for m in running_models if parent and parent in (m.get("name"), m.get("model"))), {})
        allocated = running.get("context_length", 0)
        metadata = info.get("model_info") or {}
        supported = metadata.get(str(metadata.get("general.architecture", "")) + ".context_length")
        if isinstance(supported, int) and supported > 0 and isinstance(allocated, int):
            allocated = min(allocated, supported)
        if not isinstance(allocated, int) or allocated < MIN_CONTEXT:
            raise OllamaError("This model has less than 8K context allocated. Set num_ctx to at least 8192 in an Ollama Modelfile, create that model, then select it in STEVE. See Local setup.")
        return {"model": model, "context": allocated, "vision": "vision" in info["capabilities"]}


class OllamaTransport(Transport):
    def __init__(self, on_event, home=None, command=None, api=None):
        super().__init__(on_event, home=(home or data_home()) / "ollama-runtime", command=command)
        self.api = api or OllamaAPI()
        self.settings = None
        self.default_model = None
        self.threads = {}

    def use(self, settings):
        self.settings = settings
        if isinstance(self.api, OllamaAPI):
            self.api.settings = settings

    def _api_key(self):
        settings = self.settings
        if settings is None or not settings.api_key_set:
            return ""
        return settings.api_key or ""

    def _endpoint_signature(self):
        settings = self.settings
        query = tuple(sorted((settings.query or {}).items())) if settings is not None and settings.explicit else ()
        return (active_origin(settings), query, bool(self._api_key()), getattr(settings, "generation", 0))

    def environment(self):
        env = super().environment()
        env.pop(API_KEY_ENV, None)
        key = self._api_key()
        if key:
            env[API_KEY_ENV] = key
        return env

    @staticmethod
    def config(prepared, origin=None, api_key_set=False, query=None):
        context = prepared["context"]
        # env_key names the child-process variable. Codex reads it per request, so the
        # secret is not copied into thread config.
        config = {"model_provider": "steve_ollama", "model_providers.steve_ollama.name": "Ollama (local)",
                  "model_providers.steve_ollama.base_url": (BASE_URL if origin is None else origin) + "/v1",
                  "model_providers.steve_ollama.requires_openai_auth": False,
                  "model_providers.steve_ollama.wire_api": "responses",
                  "model_providers.steve_ollama.supports_websockets": False,
                  "model_context_window": context, "model_auto_compact_token_limit": context - max(2048, context // 4),
                  "model_supports_reasoning_summaries": False, "web_search": "disabled",
                  "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]}}
        if api_key_set:
            config["model_providers.steve_ollama.env_key"] = API_KEY_ENV
        if query:
            # Codex appends these to /v1/responses. They are not a JSON think switch.
            config["model_providers.steve_ollama.query_params"] = dict(query)
        return config

    def provider_config(self, prepared):
        settings = self.settings
        explicit = settings is not None and settings.explicit
        return self.config(prepared, origin=settings.origin() if explicit else None,
                           api_key_set=bool(self._api_key()), query=settings.query if explicit else None)

    def _prepared(self, thread_id):
        prepared = (self.threads.get(thread_id) or {}).get("prepared")
        return prepared if isinstance(prepared, dict) else {}

    def _remember(self, thread_id, prepared):
        self.threads[thread_id] = {"prepared": prepared, "endpoint": self._endpoint_signature()}

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            try:
                info = self.api.request("/api/version")
                version = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(info.get("version", "")))
                if not version or tuple(map(int, version.groups())) < (0, 13, 3):
                    raise OllamaError("Update Ollama to 0.13.3 or newer for Responses API support, then refresh models.")
            except OllamaError as exc:
                return {"account": None, "localStatus": str(exc)}
            return {"account": {"type": "ollama", "id": "local-ollama", "email": "Local Ollama", "planType": "On this computer"},
                    "localStatus": connection_status(self.settings, True)}
        if method.startswith("account/"):
            raise OllamaError("Ollama runs locally and needs no sign-in. Start Ollama and refresh models.")
        if method == "model/list":
            result = self.api.models()
            self.default_model = next((m["id"] for m in result["data"] if m["isDefault"]), None)
            return result
        if method == "thread/list":
            params["modelProviders"] = ["steve_ollama"]
        if method in ("thread/start", "thread/resume"):
            model = params.get("model")
            if not model and method == "thread/resume":
                saved = super().request("thread/read", {"threadId": params["threadId"], "includeTurns": False})
                model = saved.get("thread", {}).get("model")
            model = model or self.default_model
            if not model:
                raise OllamaError("Download a local model with tools support, then choose Refresh models.")
            prepared = self.api.prepare(model)
            params["model"] = model
            params.setdefault("config", {}).update(self.provider_config(prepared))
            params["baseInstructions"] = params.get("baseInstructions", "") + "\nThis is a local Ollama session. Web search is unavailable. Use fusion_api_help for installed Fusion API documentation. Keep tool results small." + FUSION_QUICK_REFERENCE
            result = super().request(method, params, **kwargs)
            self._remember(result["thread"]["id"], prepared)
            return result
        if method == "turn/start":
            record = self.threads.get(params["threadId"]) or {}
            previous = record.get("prepared") if isinstance(record.get("prepared"), dict) else {}
            model = params.get("model") or previous.get("model") or self.default_model
            prepared = self.api.prepare(model)
            if previous != prepared or record.get("endpoint") != self._endpoint_signature():
                super().request("thread/resume", {"threadId": params["threadId"], "model": model,
                                                "config": self.provider_config(prepared)})
                self._remember(params["threadId"], prepared)
            params["model"] = model
        if method in ("turn/start", "turn/steer"):
            prepared = self._prepared(params["threadId"])
            if not prepared.get("vision") and any(item.get("type") in ("image", "localImage") for item in params.get("input", [])):
                raise OllamaError("This model cannot read images. Select a local model with vision support, then resend the image.")
        return super().request(method, params, **kwargs)
