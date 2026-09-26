import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import core
from connections import *

class ConnectionTests(unittest.TestCase):
    def test_default_does_not_select_openrouter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_connections(tmp), {'active': GATEWAY, 'profiles': {}})
    def test_encrypted_profiles_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {'active': GATEWAY, 'profiles': {GATEWAY: {'base': 'https://example.com/v1', 'key': 'fake-gateway-key', 'model': 'qwen-test'}, ROUTER: {'base': OPENROUTER, 'key': 'fake-router-key', 'model': 'vendor/model'}}}
            save_connections(tmp, data)
            self.assertEqual(load_connections(tmp), data)
            raw = (Path(tmp)/'connections.bin').read_bytes()
            self.assertNotIn(b'fake-gateway-key', raw)
            self.assertNotIn(b'fake-router-key', raw)
    def test_migrate_working_custom_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'key.bin'; p.write_bytes(crypt(b'fake-key'))
            (Path(tmp)/'last.json').write_text(json.dumps({'base': 'https://example.com/v1', 'credential': str(p), 'model': 'my-model'}))
            d = load_connections(tmp)
            self.assertEqual(d['active'], GATEWAY)
            self.assertEqual(d['profiles'][GATEWAY]['key'], 'fake-key')
    def test_native_model_ids_filter(self):
        for model, family in [('qwen3.8-27b','Qwen'), ('claude-sonnet-test','Claude'), ('gemini-test','Gemini'), ('deepseek-chat','DeepSeek'), ('kimi-k3','Kimi'), ('glm-test','GLM')]:
            self.assertTrue(family_matches({'id':model},family))
        self.assertFalse(family_matches({'id':'qwen-test'}, 'Claude'))
    def test_preset_bound_to_host(self):
        with self.assertRaises(ValueError): connection_base(ROUTER, 'https://example.com/v1')
        self.assertEqual(connection_base(GATEWAY, 'https://example.com/v1'), 'https://example.com/v1')
    def test_401_reports_destination_not_false_expiry(self):
        class Response:
            status_code = 401
            def close(self): pass
        with patch.object(core.requests, 'request', return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, 'OpenRouter'):
                core.api_request('GET', OPENROUTER+'/models', 'fake')
            with self.assertRaisesRegex(RuntimeError, 'example.com'):
                core.api_request('GET', 'https://example.com/v1/models', 'fake')

if __name__ == '__main__': unittest.main(verbosity=2)
