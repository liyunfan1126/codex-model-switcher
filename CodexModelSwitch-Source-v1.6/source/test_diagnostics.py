import tempfile
from pathlib import Path
import threading
import unittest
from diagnostics import Diagnostics

class LogTests(unittest.TestCase):
    def test_redaction_disk_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Diagnostics(tmp)
            log.add_secret('private-test-key')
            log.write('private-test-key Bearer another-secret api_key=third-secret https://user:pass@example.com/?key=secret sk-dummysecret')
            try:
                raise ValueError('raw-private-response-body')
            except ValueError as exc:
                log.exception(exc, '验证失败')
            saved = log.path.read_text(encoding='utf-8')
            self.assertEqual(saved, log.snapshot())
            for secret in ('private-test-key', 'another-secret', 'third-secret', 'user:pass', 'raw-private-response-body', 'sk-dummysecret'):
                self.assertNotIn(secret, saved)
            self.assertIn('ValueError', saved)
            log.close()

    def test_threads_and_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Diagnostics(tmp)
            log.handler.maxBytes = 500
            workers = [threading.Thread(target=lambda: [log.write('thread event') for _ in range(30)]) for _ in range(4)]
            for t in workers: t.start()
            for t in workers: t.join()
            self.assertEqual(len(log.snapshot().splitlines()), 120)
            self.assertTrue(Path(str(log.path) + '.1').exists())
            self.assertLessEqual(len(list(Path(tmp).iterdir())), 3)
            log.close()

    def test_unwritable_directory_keeps_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / 'file'; blocked.write_text('not a directory')
            log = Diagnostics(blocked)
            log.write('still available')
            self.assertTrue(log.disk_error)
            self.assertIn('still available', log.snapshot())
            log.close()

if __name__ == '__main__': unittest.main(verbosity=2)
