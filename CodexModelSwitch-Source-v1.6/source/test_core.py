import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import core

class Server(BaseHTTPRequestHandler):
    mode = 'ok'
    requests = []
    def log_message(self, *_): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.__class__.requests.append(body)
        if self.mode == '401':
            self.send_response(401); self.end_headers(); return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        if self.mode == 'truncated':
            self.wfile.write(b'data: [DONE]\n\n'); return
        tool = body['tool_choice'] != 'none'
        output = [{'type': 'function_call', 'name': 'connection_check', 'call_id': 'call_1', 'arguments': '{}'}] if tool else [
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'OK'}]}]
        if self.mode == 'no_tool': output = []
        e = {'type': 'response.completed', 'response': {'status': 'completed', 'model': 'test', 'output': output}}
        if self.mode == 'failed': e['type'] = 'response.failed'
        self.wfile.write(('data: ' + json.dumps(e) + '\n\n').encode())

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'config.toml'
        self.original = b'# keep comment\nmodel = "original"\nmodel_reasoning_effort = "high"\n[plugins.example]\nenabled = true\n'
        self.path.write_bytes(self.original)
    def tearDown(self): self.temp.cleanup()
    def apply(self): return core.apply_config(self.path, 'https://example.com/v1', 'test/model', 'fake-test-key', self.root)
    def test_dpapi_roundtrip(self):
        encrypted = core.crypt(b'fake-test-key')
        self.assertNotIn(b'fake-test-key', encrypted)
        self.assertEqual(core.crypt(encrypted, True), b'fake-test-key')
    def test_apply_preserves_settings_and_hides_key(self):
        journal = self.apply()
        raw, d = core.read_config(self.path)
        self.assertIn(b'# keep comment', raw)
        self.assertTrue(d['plugins']['example']['enabled'])
        self.assertEqual(core.selected_config(d), ('test/model', core.PROVIDER))
        self.assertNotIn(b'fake-test-key', raw)
        self.assertNotIn('model_reasoning_effort', d)
        record = json.loads(Path(journal).read_text())
        self.assertEqual(core.crypt(Path(record['backup']).read_bytes(), True), self.original)
    def test_restore_exact_bytes(self):
        self.apply(); core.restore_config(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), self.original)
    def test_restore_multiple_switches(self):
        self.apply(); first = self.path.read_bytes(); self.apply()
        core.restore_config(self.path, self.root); self.assertEqual(self.path.read_bytes(), first)
        core.restore_config(self.path, self.root); self.assertEqual(self.path.read_bytes(), self.original)
    def test_restore_preserves_external_comment(self):
        self.apply(); changed = self.path.read_bytes() + b'\n# external edit\n'; self.path.write_bytes(changed)
        core.restore_config(self.path, self.root)
        self.assertIn(b'# external edit', self.path.read_bytes())
        self.assertEqual(core.selected_config(core.read_config(self.path)[1]), ('original', 'openai'))
    def test_merge_keeps_projects_and_mcp(self):
        self.apply()
        d = core.read_config(self.path)[1]
        d['projects'] = {'new-project': {'trust_level': 'trusted'}}
        d['mcp_servers'] = {'new-tool': {'command': 'example'}}
        core.atomic_write(self.path, core.tomlkit.dumps(d).encode())
        core.restore_config(self.path, self.root)
        result = core.read_config(self.path)[1]
        self.assertEqual(result['projects'], d['projects'])
        self.assertEqual(result['mcp_servers'], d['mcp_servers'])
        self.assertEqual(core.selected_config(result), ('original', 'openai'))
    def test_merge_refuses_model_conflict(self):
        self.apply()
        d = core.read_config(self.path)[1]; d['model'] = 'externally-changed'
        raw = core.tomlkit.dumps(d).encode(); core.atomic_write(self.path, raw)
        with self.assertRaisesRegex(RuntimeError, 'model'): core.restore_config(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), raw)
    def test_legacy_backup_merge(self):
        journal = Path(self.apply())
        r = json.loads(journal.read_text()); r.pop('after_backup'); r.pop('status')
        journal.write_text(json.dumps(r))
        d = core.read_config(self.path)[1]; d['projects'] = {'new': {'trust_level': 'trusted'}}
        core.atomic_write(self.path, core.tomlkit.dumps(d).encode())
        core.restore_config(self.path, self.root)
        self.assertEqual(core.selected_config(core.read_config(self.path)[1]), ('original', 'openai'))
        self.assertIn('new', core.read_config(self.path)[1]['projects'])
    def test_aborted_journal_does_not_block_undo(self):
        self.apply()
        with patch.object(core, 'verify_credential', side_effect=lambda *args: self.path.write_bytes(self.path.read_bytes() + b'\n# concurrent\n')):
            with self.assertRaises(RuntimeError): self.apply()
        core.restore_config(self.path, self.root)
        self.assertEqual(core.selected_config(core.read_config(self.path)[1]), ('original', 'openai'))
    def test_merge_multi_undo_preserves_external_setting(self):
        self.apply(); core.reset_codex_default(self.path, self.root)
        d = core.read_config(self.path)[1]; d['mcp_servers'] = {'new': {'command': 'test'}}
        core.atomic_write(self.path, core.tomlkit.dumps(d).encode())
        core.restore_config(self.path, self.root); core.restore_config(self.path, self.root)
        result = core.read_config(self.path)[1]
        self.assertEqual(core.selected_config(result), ('original', 'openai'))
        self.assertEqual(result['mcp_servers']['new']['command'], 'test')
    def test_missing_config(self):
        self.path.unlink(); self.apply(); core.restore_config(self.path, self.root)
        self.assertFalse(self.path.exists())
    def test_active_profile(self):
        self.path.write_text('profile="work"\n[profiles.work]\nmodel="old"\nmodel_provider="other"\nmodel_reasoning_effort="high"\n', encoding='utf-8')
        self.apply()
        _, d = core.read_config(self.path)
        self.assertEqual(core.selected_config(d), ('test/model', core.PROVIDER))
        self.assertNotIn('model_reasoning_effort', d['profiles']['work'])
    def test_invalid_toml_not_changed(self):
        self.path.write_bytes(b'bad = [');
        with self.assertRaises(Exception): self.apply()
        self.assertEqual(self.path.read_bytes(), b'bad = [')
    def test_concurrent_edit_not_overwritten(self):
        with patch.object(core, 'verify_credential', side_effect=lambda *args: self.path.write_bytes(b'# external')):
            with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.path.read_bytes(), b'# external')
    def test_url_validation(self):
        self.assertEqual(core.normalize_url('https://example.com/v1/responses/'), 'https://example.com/v1')
        for url in ['http://example.com/v1', 'https://user:secret@example.com/v1', 'https://example.com/v1?key=secret', 'https://example.com/chat/completions']:
            with self.assertRaises(ValueError): core.normalize_url(url)
    def test_default_without_switch_backup(self):
        self.path.write_text('# retained\nmodel="third-party"\nmodel_provider="vendor"\nprofile="work"\n[profiles.work]\nmodel="another"\nmodel_provider="vendor"\nweb_search="disabled"\n[plugins.example]\nenabled=true\n[profiles.other]\nmodel="keep-me"\n', encoding='utf-8')
        before = self.path.read_bytes()
        auth = self.root / 'auth.json'
        auth.write_bytes(b'{"test":"unchanged"}')
        self.assertTrue(core.reset_codex_default(self.path, self.root))
        raw, d = core.read_config(self.path)
        self.assertEqual(core.selected_config(d), ('默认', 'openai'))
        self.assertNotIn('model', d)
        self.assertNotIn('web_search', d['profiles']['work'])
        self.assertEqual(d['profiles']['other']['model'], 'keep-me')
        self.assertTrue(d['plugins']['example']['enabled'])
        self.assertIn(b'# retained', raw)
        self.assertEqual(auth.read_bytes(), b'{"test":"unchanged"}')
        self.assertFalse(core.reset_codex_default(self.path, self.root))
        core.restore_config(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), before)
    def test_default_after_switch_can_undo(self):
        self.apply()
        switched = self.path.read_bytes()
        core.reset_codex_default(self.path, self.root)
        core.restore_config(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), switched)
        core.restore_config(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), self.original)
    def test_default_missing_and_invalid(self):
        self.path.unlink()
        self.assertFalse(core.reset_codex_default(self.path, self.root))
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b'bad = [')
        with self.assertRaises(Exception): core.reset_codex_default(self.path, self.root)
        self.assertEqual(self.path.read_bytes(), b'bad = [')
    def test_probe_protocol(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            Server.mode = 'ok'; Server.requests = []
            self.assertEqual(core.probe(base, 'fake-test-key', 'test')['reported'], 'test')
            self.assertEqual(len(Server.requests), 2)
            self.assertFalse(Server.requests[0]['store'])
            self.assertTrue(any(x.get('type') == 'function_call_output' for x in Server.requests[1]['input']))
            for mode in ('401', 'truncated', 'no_tool', 'failed'):
                Server.mode = mode
                with self.assertRaises(RuntimeError): core.probe(base, 'fake-test-key', 'test')
            self.assertEqual(self.path.read_bytes(), self.original)
        finally:
            server.shutdown(); server.server_close()

if __name__ == '__main__': unittest.main(verbosity=2)
