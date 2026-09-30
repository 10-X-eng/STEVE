"""Local model and per-model effort choices. No credentials or conversation data."""
import json
from pathlib import Path


class ProviderChoice:
    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "provider.json"
        self.provider = "chatgpt"
        self.custom_provider = "ollama"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            selected = saved.get("provider")
            custom = saved.get("customProvider", selected)
            if custom in ("ollama", "openai"):
                self.custom_provider = custom
            if selected in ("chatgpt", "grok", "ollama", "claude", "openrouter", "openai"):
                self.provider = selected
        except (OSError, ValueError, AttributeError):
            pass

    def save(self, provider):
        if provider == "custom":
            provider = self.custom_provider
        if provider not in ("chatgpt", "grok", "ollama", "claude", "openrouter", "openai"):
            raise ValueError("Choose ChatGPT, Grok, Claude, OpenRouter, an OpenAI-compatible server, or local Ollama.")
        custom = provider if provider in ("ollama", "openai") else self.custom_provider
        self.home.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"provider": provider, "customProvider": custom}), encoding="utf-8")
        temporary.replace(self.path)
        self.provider = provider
        self.custom_provider = custom

    def preferences(self):
        return Preferences(self.home if self.provider == "chatgpt" else self.home / self.provider)


class Preferences:
    def __init__(self, home):
        self.path = Path(home) / "preferences.json"
        self.model = ""
        self.efforts = {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value.get("model"), str):
                self.model = value["model"]
            if isinstance(value.get("efforts"), dict):
                self.efforts = {k: v for k, v in value["efforts"].items()
                                if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            pass

    def save(self, model, effort):
        efforts = {**self.efforts, model: effort}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"model": model, "efforts": efforts}), encoding="utf-8")
        temporary.replace(self.path)
        self.model, self.efforts = model, efforts
