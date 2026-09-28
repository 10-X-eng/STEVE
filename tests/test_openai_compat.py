"""OpenAI-compatible provider: base URL validation, protected key storage and runtime configuration."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.openai_compat_transport import (API_KEY_ENV, FALLBACK_CONTEXT, PROVIDER, OpenAICompatError,
                                           OpenAICompatSettings, OpenAICompatTransport, catalog,
                                           normalize_base_url)
from steve.preferences import ProviderChoice
from steve.transport import Transport


class MemoryStore:
    def __init__(self):
        self.value = None

    def read(self):
        return None if self.value is None else dict(self.value)

    def write(self, value):
        self.value = dict(value)


MODELS = b'{"object":"list","data":[{"id":"zeta"},{"id":"Alpha","max_model_len":65536},{"id":""},"bad"]}'


class OpenAICompatTests(unittest.TestCase):
    def test_base_url_accepts_http_origins_and_rejects_credentials_and_extras(self):
        self.assertEqual(normalize_base_url(" http://127.0.0.1:1234/v1/ "), "http://127.0.0.1:1234/v1")
        self.assertEqual(normalize_base_url("https://[::1]:8000/v1"), "https://[::1]:8000/v1")
        for bad in ("", "127.0.0.1:1234/v1", "ftp://host/v1", "http://user:pw@host/v1", "http://host/v1?key=x",
                    "http://host/v1#x", "http://ho st/v1", "http://host:99999/v1", "http:///v1", None, 5):
            with self.assertRaises(ValueError, msg=bad):
                normalize_base_url(bad)

    def test_key_stays_in_the_credential_store_and_out_of_files_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore()
            settings = OpenAICompatSettings(folder, store=store)
            self.assertEqual((settings.base_url, settings.api_key_set), ("", False))
            with self.assertRaisesRegex(ValueError, "spaces or control"):
                settings.save("http://127.0.0.1:1234/v1", "secret token")
            settings.save("http://127.0.0.1:1234/v1")
            self.assertIsNone(store.value)  # No key, no credential-store write.
            settings.save("http://10.0.0.8:8000/v1", "  sk-secret  ")
            text = settings.path.read_text(encoding="utf-8")
            self.assertNotIn("sk-secret", text)
            self.assertEqual(json.loads(text), {"baseUrl": "http://10.0.0.8:8000/v1", "apiKeySet": True})
            self.assertNotIn("sk-secret", repr(settings) + json.dumps(settings.public_state()))
            self.assertEqual(store.value, {"apiKey": "sk-secret"})
            if os.name != "nt":
                self.assertEqual(settings.path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(settings.home.stat().st_mode & 0o777, 0o700)
            reloaded = OpenAICompatSettings(folder, store=store)
            self.assertEqual((reloaded.base_url, reloaded.api_key), ("http://10.0.0.8:8000/v1", "sk-secret"))
            reloaded.save("http://10.0.0.8:8000/v1", "   ")
            self.assertEqual(reloaded.api_key, "sk-secret")  # Blank keeps the saved key.
            reloaded.save("http://10.0.0.8:8000/v1", "ignored", clear_api_key=True)
            self.assertEqual((reloaded.api_key_set, reloaded.api_key, store.value), (False, "", {"apiKey": ""}))

    def test_models_list_sends_bearer_directly_and_errors_do_not_leak_the_key(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = OpenAICompatSettings(folder, store=MemoryStore())
            client = OpenAICompatTransport(lambda *args: None, home=folder)
            client.use(settings)
            with self.assertRaisesRegex(OpenAICompatError, "base URL"):
                client.models()
            settings.save("http://127.0.0.1:1234/v1", "sk-secret")
            client.opener = Mock()
            client.opener.open.return_value = io.BytesIO(MODELS)
            models = client.request("model/list")["data"]
            request = client.opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/models")
            self.assertEqual(request.headers["Authorization"], "Bearer sk-secret")
            self.assertEqual([(m["id"], m["context"], m["isDefault"]) for m in models],
                             [("Alpha", 65536, True), ("zeta", FALLBACK_CONTEXT, False)])
            self.assertEqual(client.default_model, "Alpha")
            for failure, message in ((HTTPError("u", 401, "no", {}, io.BytesIO(b"sk-secret")), "rejected the API key"),
                                     (URLError("offline"), "Cannot reach"), (None, "invalid model list")):
                client.opener.open.side_effect = failure
                client.opener.open.return_value = io.BytesIO(b"[]")
                with self.assertRaisesRegex(OpenAICompatError, message) as caught:
                    client.models()
                self.assertNotIn("sk-secret", str(caught.exception))
            account = client.request("account/read")
            self.assertIsNone(account["account"])
            client.opener.open.side_effect = None
            client.opener.open.return_value = io.BytesIO(MODELS)
            result = client.request("account/read")
            self.assertEqual(result["localStatus"], "Connected to http://127.0.0.1:1234/v1 · 2 models.")
            account = result["account"]
            self.assertEqual((account["type"], account["email"]), ("openai", "127.0.0.1:1234"))
            with self.assertRaisesRegex(OpenAICompatError, "no sign-in"):
                client.request("account/logout")

    def test_runtime_config_uses_env_key_and_follows_server_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = OpenAICompatSettings(folder, store=MemoryStore())
            settings.save("http://127.0.0.1:1234/v1", "sk-secret")
            client = OpenAICompatTransport(lambda *args: None, home=folder)
            client.use(settings)
            client.catalog = {"m": {"id": "m", "context": 65536}}
            with patch.object(Transport, "request", return_value={"thread": {"id": "t"}}) as rpc:
                client.request("thread/start", {"model": "m", "baseInstructions": "Fusion"})
                config = rpc.call_args.args[1]["config"]
                self.assertEqual(config["model_provider"], PROVIDER)
                self.assertEqual(config[f"model_providers.{PROVIDER}.base_url"], "http://127.0.0.1:1234/v1")
                self.assertEqual(config[f"model_providers.{PROVIDER}.wire_api"], "responses")
                self.assertEqual(config[f"model_providers.{PROVIDER}.env_key"], API_KEY_ENV)
                self.assertEqual((config["model_context_window"], config["model_auto_compact_token_limit"]), (65536, 52428))
                self.assertNotIn("sk-secret", json.dumps(rpc.call_args.args[1]))
                self.assertIn("API lengths are always centimeters", rpc.call_args.args[1]["baseInstructions"])
                client.request("turn/start", {"threadId": "t", "input": []})
                self.assertEqual(rpc.call_args.args[0], "turn/start")  # Unchanged server: no resume.
                settings.save("http://10.0.0.5:8000/v1", clear_api_key=True)
                client.request("turn/start", {"threadId": "t", "input": []})
                resumed = rpc.call_args_list[-2]
                self.assertEqual(resumed.args[0], "thread/resume")
                self.assertEqual(resumed.args[1]["config"][f"model_providers.{PROVIDER}.base_url"], "http://10.0.0.5:8000/v1")
                self.assertNotIn(f"model_providers.{PROVIDER}.env_key", resumed.args[1]["config"])
                client.request("thread/list", {})
                self.assertEqual(rpc.call_args.args[1]["modelProviders"], [PROVIDER])
            settings.save("http://10.0.0.5:8000/v1", "sk-secret")
            with patch.dict(os.environ, {API_KEY_ENV: "ambient"}):
                env = client.environment()
                self.assertEqual(os.environ[API_KEY_ENV], "ambient")
            self.assertEqual(env[API_KEY_ENV], "sk-secret")
            settings.save("http://10.0.0.5:8000/v1", clear_api_key=True)
            with patch.dict(os.environ, {API_KEY_ENV: "ambient"}):
                self.assertNotIn(API_KEY_ENV, client.environment())

    def test_efforts_come_from_metadata_then_known_families_and_never_guess(self):
        models = {m["id"]: m for m in catalog({"data": [
            {"id": "gateway/model", "reasoning": {"supported_efforts": ["high", "bogus", "low"], "default_effort": "low"}},
            {"id": "flat", "supported_reasoning_efforts": [{"reasoningEffort": "medium"}], "default_reasoning_effort": "max"},
            {"id": "gpt-oss-20b"}, {"id": "openai/GPT-OSS-120B"}, {"id": "gpt-oss-20b-meta", "reasoning": {"supported_efforts": []}},
            {"id": "Qwen3.5-9B"}]})["data"]}
        levels = lambda name: [e["reasoningEffort"] for e in models[name]["supportedReasoningEfforts"]]
        self.assertEqual((levels("gateway/model"), models["gateway/model"]["defaultReasoningEffort"]), (["low", "high"], "low"))
        self.assertEqual((levels("flat"), models["flat"]["defaultReasoningEffort"]), (["medium"], ""))
        for name in ("gpt-oss-20b", "openai/GPT-OSS-120B"):
            self.assertEqual((levels(name), models[name]["defaultReasoningEffort"]), (["low", "medium", "high"], "medium"))
        self.assertEqual(levels("gpt-oss-20b-meta"), [])  # Server metadata wins over the family table.
        self.assertEqual((levels("Qwen3.5-9B"), models["Qwen3.5-9B"]["defaultReasoningEffort"]), ([], ""))

    def test_provider_choice_remembers_openai(self):
        with tempfile.TemporaryDirectory() as folder:
            ProviderChoice(folder).save("openai")
            choice = ProviderChoice(folder)
            self.assertEqual(choice.provider, "openai")
            self.assertEqual(choice.preferences().path, Path(folder) / "openai" / "preferences.json")


if __name__ == "__main__":
    unittest.main()
