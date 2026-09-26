"""Local, bounded, redacted diagnostic logging. No network or import side effects."""
from collections import deque
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading
import traceback
import uuid

class Diagnostics:
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.secrets = set()
        self.lines = deque(maxlen=2000)
        self.version = 0
        self.disk_error = False
        self.handler = None
        self.path = Path(directory) / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.log')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(self.path, maxBytes=1024*1024, backupCount=2, encoding='utf-8')
            self.handler.setFormatter(logging.Formatter('%(message)s'))
            # Logging must not silently swallow a disk failure.
            def failed(record):
                self.disk_error = True
            self.handler.handleError = failed
        except OSError:
            self.disk_error = True

    def add_secret(self, value):
        if value:
            with self.lock:
                self.secrets.add(value)

    def redact(self, value):
        text = str(value)
        with self.lock:
            for key in sorted(self.secrets, key=len, reverse=True):
                text = text.replace(key, '[REDACTED]')
        text = re.sub(r'(?i)(bearer\s+)[^\s,;\"\']+', r'\1[REDACTED]', text)
        text = re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|authorization|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
        text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', text)
        text = re.sub(r'https?://[^\s]+', '[URL omitted]', text)
        text = text.replace(str(Path.home()), '%USERPROFILE%')
        return text.replace('\r', r'\r').replace('\n', r'\n')[:4000]

    def write(self, message, level='INFO'):
        with self.lock:
            line = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + f' [{level}] ' + self.redact(message)
            self.lines.append(line)
            self.version += 1
            if self.handler and not self.disk_error:
                try:
                    self.handler.emit(logging.LogRecord('switch', logging.INFO, '', 0, line, (), None))
                    self.handler.flush()
                except OSError:
                    self.disk_error = True

    def exception(self, error, summary):
        # Record frame positions, never locals, source lines or raw response bodies.
        frames = ' > '.join(f'{Path(x.filename).name}:{x.lineno}:{x.name}' for x in traceback.extract_tb(error.__traceback__))
        self.write(f'{summary} | {type(error).__name__} | {frames}', 'ERROR')

    def snapshot(self):
        with self.lock:
            return '\n'.join(self.lines) + '\n'

    def close(self):
        with self.lock:
            if self.handler:
                self.handler.close()

_sink = None

def set_sink(sink):
    global _sink
    _sink = sink

def event(message, level='INFO'):
    if _sink:
        _sink.write(message, level)
