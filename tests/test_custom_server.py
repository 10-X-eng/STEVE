"""Shared custom-server regressions: credentials, legacy settings and mode changes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_core as core
from steve.controller import Controller
from steve.custom_server import SameOriginRedirects
from steve.debug_log import DebugLog
from steve.ollama_transport import OllamaSettings, OllamaAPI, OllamaError
from steve.openai_compat_transport import OpenAICompatSettings, OpenAICompatTransport, OpenAICompatError
from steve.preferences import ProviderChoice
from test_openai_compat import MemoryStore


class ServerSettingsTests(unittest.TestCase):
    def test_old_ollama_endpoint_key_and_preferences_survive_https_save(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / 'ollama').mkdir()
            endpoint = home / 'ollama' / 'endpoint.json'
            endpoint.write_text(json.dumps({'host':'printer.lan', 'port':11435, 'url':'/ollama?think=false', 'apiKeySet':True}))
            (home / 'provider.json').write_text('{"provider":"ollama"}')
            store = MemoryStore()
            store.write({'apiKey':'fixture-secret'})
            settings = OllamaSettings(home, store=store)
            self.assertEqual(settings.origin(), 'http://printer.lan:11435/ollama')
            self.assertEqual(settings.api_key, 'fixture-secret')
            settings.save_url('https://printer.lan/ollama?think=false')
            restored = OllamaSettings(home, store=store)
            self.assertEqual(restored.request_url('/api/tags'), 'https://printer.lan:443/ollama/api/tags?think=false')
            self.assertEqual(restored.api_key, 'fixture-secret')
            self.assertNotIn('fixture-secret', endpoint.read_text())
            choice = ProviderChoice(home)
            choice.preferences().save('my-existing-model', '')
            choice.save('chatgpt')
            choice = ProviderChoice(home)
            choice.save('custom')
            self.assertEqual(choice.provider, 'ollama')
            self.assertEqual(choice.preferences().model, 'my-existing-model')
            choice.save('openai')
            choice.save('grok')
            choice = ProviderChoice(home)
            choice.save('custom')
            self.assertEqual(choice.provider, 'openai')

    def test_both_discovery_paths_refuse_cross_origin_redirects(self):
        received = []
        class Destination(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":[]}')
            def log_message(self, *args):
                pass
        destination = ThreadingHTTPServer(('127.0.0.1', 0), Destination)
        class Source(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{destination.server_port}/models')
                self.end_headers()
            def log_message(self, *args):
                pass
        source = ThreadingHTTPServer(('127.0.0.1', 0), Source)
        for server in (source, destination):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                ollama = OllamaSettings(folder, store=MemoryStore())
                ollama.save_url(f'http://127.0.0.1:{source.server_port}', 'synthetic-key')
                generic = OpenAICompatSettings(folder, store=MemoryStore())
                generic.save(f'http://127.0.0.1:{source.server_port}/v1', 'synthetic-key')
                client = OpenAICompatTransport(lambda *args: None, home=folder)
                client.use(generic)
                with self.assertRaisesRegex(OllamaError, 'different origin'):
                    OllamaAPI(ollama).request('/api/version')
                with self.assertRaisesRegex(OpenAICompatError, 'different origin'):
                    client.models()
                self.assertEqual(received, [])
        finally:
            for server in (source, destination):
                server.shutdown()
                server.server_close()

    def test_same_origin_redirects_work_but_https_downgrades_do_not(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        redirect = SameOriginRedirects()
        request = Request('https://server.example/v1/models', headers={'Authorization':'Bearer fixture'})
        allowed = redirect.redirect_request(request, None, 302, 'Found', {}, 'https://server.example:443/catalog')
        self.assertEqual(allowed.get_header('Authorization'), 'Bearer fixture')
        with self.assertRaises(HTTPError):
            redirect.redirect_request(request, None, 302, 'Found', {}, 'http://server.example/catalog')


class ServerControllerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        def factory(kind):
            def create(notify):
                client = core.FakeClient(notify)
                client.account = {'type':kind, 'id':kind, 'email':kind}
                return client
            return create
        self.controller = Controller(lambda state: None, transport_factory=core.FakeClient,
            ollama_factory=factory('ollama'), openai_factory=factory('openai'),
            debug_log=DebugLog(Path(self.folder.name)))
        self.controller.ollama._store = MemoryStore()
        self.controller.openai_compat._store = MemoryStore()
        self.controller.dispatch('connect')
        core.eventually(lambda: bool(self.controller.state['models']))

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(3)
        self.folder.cleanup()

    def save(self, kind, url, **kwargs):
        self.assertTrue(self.controller.dispatch('customServer', {'serverType':kind, 'baseUrl':url, **kwargs}))
        core.eventually(lambda: not self.controller.state['serverSaving'])
        self.assertEqual(self.controller.state['provider'], kind)
        self.assertFalse(self.controller.state['error'])

    def test_switch_types_preserves_separate_keys_and_preferences(self):
        self.save('ollama', 'https://ollama.example/prefix?think=false', apiKey='ollama-key')
        self.controller.preferences.save('ollama-model', '')
        self.save('openai', 'https://responses.example/v1', apiKey='responses-key')
        self.controller.preferences.save('responses-model', '')
        self.save('ollama', 'https://ollama.example/prefix?think=false')
        self.assertEqual(self.controller.preferences.model, 'ollama-model')
        self.assertEqual(self.controller.ollama.api_key, 'ollama-key')
        self.assertEqual(self.controller.openai_compat.api_key, 'responses-key')
        self.assertEqual(self.controller.state['customServerType'], 'ollama')
        snapshot = json.dumps(self.controller.snapshot())
        self.assertNotIn('ollama-key', snapshot)
        self.assertNotIn('responses-key', snapshot)

    def test_save_blocks_send_switch_and_restart_until_reconnect_finishes(self):
        entered, release = threading.Event(), threading.Event()
        original = self.controller.ollama.save_url
        def held(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        with patch.object(self.controller.ollama, 'save_url', side_effect=held):
            self.controller.dispatch('customServer', {'serverType':'ollama', 'baseUrl':'http://127.0.0.1:11434'})
            self.assertTrue(entered.wait(1))
            try:
                for action, payload in [('send', {'text':'Hello'}), ('provider', {'provider':'chatgpt'}), ('restartRuntime', {})]:
                    self.assertFalse(self.controller.dispatch(action, payload))
                self.assertFalse(self.controller.state['codexRestarting'])
            finally:
                release.set()
            core.eventually(lambda: not self.controller.state['serverSaving'])
        self.assertEqual(self.controller.state['provider'], 'ollama')

    def test_failed_save_releases_controls_without_switching_provider(self):
        with patch.object(self.controller.ollama, 'save_url', side_effect=RuntimeError('Store is locked')):
            self.controller.dispatch('customServer', {'serverType':'ollama', 'baseUrl':'http://127.0.0.1:11434'})
            core.eventually(lambda: not self.controller.state['serverSaving'])
        self.assertEqual(self.controller.state['provider'], 'chatgpt')
        self.assertIn('Store is locked', self.controller.state['error'])
