"""Local Ollama discovery and the bundled conversation runtime's Responses provider."""
import ipaddress
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request

from .custom_server import (CustomServerTransport, ServerSettings, normalize_api_key, normalize_base_url,
                            responses_config, server_opener)

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


class OllamaSettings(ServerSettings):
    """Host, port, and an optional API key. The key stays in the system credential store."""

    def __init__(self, home, store=None):
        super().__init__(home, "ollama", "ollama-key", store)
        self.scheme = "http"
        self.host = DEFAULT_HOST
        self.port = DEFAULT_PORT
        self.prefix = ""
        self.query = {}
        self.url = ""
        self.explicit = False
        self._load()

    def __repr__(self):
        return f"OllamaSettings(host={self.host!r}, port={self.port}, api_key_set={self.api_key_set})"

    @property
    def label(self):
        return f"{format_host(self.host)}:{self.port}{self.url}"

    def origin(self):
        return f"{self.scheme}://{format_host(self.host)}:{self.port}{self.prefix}"

    def request_url(self, suffix):
        url = self.origin() + suffix
        if self.query:
            url += "?" + urlencode(self.query)
        return url

    def public_state(self):
        return {"ollamaHost": self.host, "ollamaPort": self.port, "ollamaAddress": self.label,
                "ollamaUrl": self.url, "ollamaApiKeySet": self.api_key_set,
                "ollamaBaseUrl": self.origin() + ("?" + urlencode(self.query) if self.query else "")}

    def _load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(value, dict):
            return
        try:
            if value.get("baseUrl"):
                self.scheme, self.host, self.port, self.prefix, self.query, self.url = self.parse_url(value["baseUrl"])
                self.api_key_set = value.get("apiKeySet") is True
                self.explicit = True
                return
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

    @staticmethod
    def parse_url(base_url):
        if not isinstance(base_url, str):
            raise ValueError("Enter the Ollama server URL.")
        base, sep, query_text = base_url.strip().partition("?")
        base = normalize_base_url(base)
        parts = urlsplit(base)
        host, port = normalize_endpoint(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        prefix, query, extra = normalize_url_extra(parts.path + ("?" + query_text if sep else ""))
        return parts.scheme, host, port, prefix, query, extra

    def save_url(self, base_url, api_key=None, clear_api_key=False):
        scheme, host, port, prefix, query, extra = self.parse_url(base_url)
        canonical = f"{scheme}://{format_host(host)}:{port}{extra}"
        self.save_endpoint({"baseUrl": canonical, "host": host, "port": port, "url": extra}, api_key, clear_api_key)
        self.scheme, self.host, self.port = scheme, host, port
        self.prefix, self.query, self.url = prefix, query, extra
        self.explicit = True

    def save(self, host, port=None, api_key=None, clear_api_key=False, url=""):
        # Compatibility for existing callers and endpoint.json records.
        host, port = normalize_endpoint(host, port)
        _, _, extra = normalize_url_extra(url)
        self.save_url(f"http://{format_host(host)}:{port}{extra}", api_key, clear_api_key)


class OllamaAPI:
    def __init__(self, settings=None):
        # Reach the configured server directly. A system HTTP proxy must not see model metadata.
        self.opener = server_opener()
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
            if exc.code in (401, 403):
                raise OllamaError("The server rejected the API key. Check it under Server.") from None
            if 300 <= exc.code < 400:
                raise OllamaError("The server redirected to a different origin. Enter its direct URL under Server.") from None
            raise OllamaError("Ollama could not load the requested model. Check that it is downloaded and fits in memory, then refresh models.") from None
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


class OllamaTransport(CustomServerTransport):
    provider_id = "steve_ollama"
    runtime_folder = "ollama-runtime"
    api_key_env = API_KEY_ENV
    error_type = OllamaError

    def __init__(self, on_event, home=None, command=None, api=None):
        super().__init__(on_event, home=home, command=command)
        self.api = api or OllamaAPI()

    def use(self, settings):
        super().use(settings)
        if isinstance(self.api, OllamaAPI):
            self.api.settings = settings

    def _endpoint_signature(self):
        settings = self.settings
        query = tuple(sorted((settings.query or {}).items())) if settings is not None and settings.explicit else ()
        return (active_origin(settings), query, bool(self._api_key()), getattr(settings, "generation", 0))

    @staticmethod
    def config(prepared, origin=None, api_key_set=False, query=None):
        return responses_config("steve_ollama", "Ollama (local)", (BASE_URL if origin is None else origin) + "/v1",
                                prepared["context"], env_key=API_KEY_ENV if api_key_set else None, query=query)

    def provider_config(self, prepared):
        settings = self.settings
        explicit = settings is not None and settings.explicit
        return self.config(prepared, origin=settings.origin() if explicit else None,
                           api_key_set=bool(self._api_key()), query=settings.query if explicit else None)

    def read_account(self):
        try:
            info = self.api.request("/api/version")
            version = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(info.get("version", "")))
            if not version or tuple(map(int, version.groups())) < (0, 13, 3):
                raise OllamaError("Update Ollama to 0.13.3 or newer for Responses API support, then refresh models.")
        except OllamaError as exc:
            return {"account": None, "localStatus": str(exc)}
        return {"account": {"type": "ollama", "id": "local-ollama", "email": "Local Ollama", "planType": "On this computer"},
                "localStatus": connection_status(self.settings, True)}

    def models(self):
        return self.api.models()

    def prepare(self, model):
        return self.api.prepare(model)
