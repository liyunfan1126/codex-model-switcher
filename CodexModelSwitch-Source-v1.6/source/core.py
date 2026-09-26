"""Configuration transactions and Responses API checks. No changes on import."""
from __future__ import annotations
import base64
import ctypes
import copy
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlsplit, urlunsplit
import requests
import tomlkit
from diagnostics import event

OPENROUTER = 'https://openrouter.ai/api/v1'
PROVIDER = 'codex_model_switch'

def config_path():
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'

def data_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexModelSwitch'

def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.switch-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def normalize_url(value):
    p = urlsplit(value.strip().rstrip('/'))
    if not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('请输入完整 API Base URL，不要带密钥、查询参数或 #。')
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('远程接口必须使用 HTTPS；本机接口可以使用 HTTP。')
    path = p.path.rstrip('/')
    if path.endswith('/responses'):
        path = path[:-10]
    if path.endswith('/chat/completions') or path.endswith('/messages'):
        raise ValueError('这里需要 Responses API 的 Base URL；不能使用 Chat Completions / Messages 地址。')
    return urlunsplit((p.scheme, p.netloc, path, '', ''))

class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def crypt(data, decrypt=False):
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError('Windows 凭据加密/解密失败。')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)

def credential_command(path):
    # Use native Windows PowerShell so the portable UI need not remain running.
    literal = str(Path(path).resolve()).replace("'", "''")
    script = ("$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Security; "
              "$b=[IO.File]::ReadAllBytes('" + literal + "'); "
              "$p=[Security.Cryptography.ProtectedData]::Unprotect($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); "
              "[Console]::Write([Text.Encoding]::UTF8.GetString($p))")
    exe = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    return {'command': exe, 'args': ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode()], 'timeout_ms': 10000}

def verify_credential(auth, expected):
    p = subprocess.run([auth['command'], *auth['args']], capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if p.returncode or p.stdout.decode('utf-8') != expected:
        raise RuntimeError('Windows 凭据读取自检失败，未修改 Codex 配置。')

def api_request(method, url, key='', **kwargs):
    event('HTTP 请求开始：' + method + (' /models' if url.endswith('/models') else ' /responses'))
    headers = {'Accept': 'application/json', 'User-Agent': 'CodexModelSwitch/1.0'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        r = requests.request(method, url, headers=headers, timeout=(12, 60), allow_redirects=False, **kwargs)
    except requests.RequestException:
        event('HTTP 连接失败或超时', 'ERROR')
        raise RuntimeError('连接失败或超时，请检查接口地址、代理和网络。') from None
    event(f'HTTP 响应状态：{r.status_code}')
    if not 200 <= r.status_code < 300:
        status = r.status_code
        r.close()
        hints = {401: 'API Key 无效或已过期', 403: '没有访问权限', 402: '余额不足', 404: '模型或 Responses 接口不存在', 429: '请求限流或额度不足'}
        if status == 401:
            host = urlsplit(url).hostname or '当前平台'
            hint = '这里只接受 OpenRouter 签发的 Key；其他平台请选择“聚合 / 中转”并填写该平台地址。' if host == 'openrouter.ai' else '请核对地址与 Key 是否来自同一平台，以及 Key 是否有效。'
            raise RuntimeError(f'HTTP 401：{host} 拒绝鉴权。{hint}')
        raise RuntimeError(f'HTTP {status}：{hints.get(status, "接口拒绝请求，请检查模型与 Responses 兼容性")}。')
    return r

def fetch_models(base, key=''):
    with api_request('GET', normalize_url(base) + '/models', key) as r:
        data = r.json().get('data')
    if not isinstance(data, list):
        raise ValueError('接口未返回标准 models 列表；可以手动填写模型 ID。')
    return [x for x in data if isinstance(x, dict) and isinstance(x.get('id'), str)]

def stream_response(base, key, body):
    body = dict(body, stream=True, store=False)
    started = time.monotonic()
    with api_request('POST', base + '/responses', key, json=body, stream=True) as r:
        if 'text/event-stream' not in r.headers.get('Content-Type', ''):
            raise RuntimeError('接口没有返回 SSE 流；无法确认与 Codex 兼容。')
        data_lines = []
        for raw in r.iter_lines(chunk_size=1):
            if time.monotonic() - started > 100:
                raise RuntimeError('模型响应超过 100 秒，验证停止。')
            line = raw.decode('utf-8-sig')
            if line.startswith('data:'):
                data_lines.append(line[5:].lstrip())
            elif not line and data_lines:
                payload = '\n'.join(data_lines)
                data_lines = []
                if payload == '[DONE]':
                    break
                e = json.loads(payload)
                if e.get('type') in ('error', 'response.failed', 'response.incomplete'):
                    raise RuntimeError('模型返回失败或不完整的响应，未通过验证。')
                if e.get('type') == 'response.completed':
                    result = e.get('response', {})
                    if result.get('status') != 'completed' or not isinstance(result.get('output'), list):
                        raise RuntimeError('完成事件结构异常，无法确认兼容。')
                    return result
    raise RuntimeError('流式连接提前结束，没有收到 response.completed。')

def probe(base, key, model, progress=lambda x: None):
    base = normalize_url(base)
    if not key.strip() or any(c in key for c in '\r\n'):
        raise ValueError('请输入有效的 API Key。')
    if not model.strip():
        raise ValueError('请先选择模型或输入模型 ID。')
    progress('1/3  正在验证流式工具调用…')
    tool = {'type': 'function', 'name': 'connection_check', 'description': 'Return a connection check.',
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
    first_input = [{'role': 'user', 'content': 'Call connection_check once. Do not call any other tools.'}]
    first = stream_response(base, key, {'model': model, 'input': first_input, 'tools': [tool],
                                      'tool_choice': {'type': 'function', 'name': 'connection_check'}, 'max_output_tokens': 512})
    calls = [x for x in first['output'] if x.get('type') == 'function_call' and x.get('name') == 'connection_check' and x.get('call_id')]
    if len(calls) != 1:
        raise RuntimeError('未收到预期的工具调用；此模型暂不能确认适用于 Codex。')
    json.loads(calls[0].get('arguments', '{}'))
    progress('2/3  正在验证工具结果续写…')
    second = stream_response(base, key, {'model': model, 'input': first_input + first['output'] + [
        {'type': 'function_call_output', 'call_id': calls[0]['call_id'], 'output': '{"ok":true}'},
        {'role': 'user', 'content': 'Reply only OK.'}], 'tools': [tool], 'tool_choice': 'none', 'max_output_tokens': 512})
    answer = ''.join(c.get('text', '') for x in second['output'] if x.get('type') == 'message' for c in x.get('content', []) if c.get('type') == 'output_text')
    if not answer.strip():
        raise RuntimeError('工具续写没有返回文本，验证失败。')
    progress('3/3  API 验证通过（流式响应 / 工具调用 / 续写）')
    return {'requested': model, 'reported': second.get('model', '接口未报告'), 'checked_at': time.strftime('%Y-%m-%d %H:%M:%S')}

def read_config(path):
    path = Path(path)
    raw = path.read_bytes() if path.exists() else b''
    return raw, tomlkit.parse(raw.decode('utf-8-sig'))

def selected_config(doc):
    active = doc.get('profiles', {}).get(doc.get('profile', ''), {})
    return active.get('model', doc.get('model', '默认')), active.get('model_provider', doc.get('model_provider', 'openai'))

def apply_config(path, base, model, key, root=None):
    root = Path(root or data_path())
    path = Path(path).resolve()
    base = normalize_url(base)
    before, doc = read_config(path)
    credential = root / 'credentials' / (uuid.uuid4().hex + '.bin')
    atomic_write(credential, crypt(key.encode('utf-8')))
    auth = credential_command(credential)
    verify_credential(auth, key)
    for target in [doc] + ([doc['profiles'][doc['profile']]] if doc.get('profile') in doc.get('profiles', {}) else []):
        target['model'] = model
        target['model_provider'] = PROVIDER
        target['web_search'] = 'disabled'
        for field in ('model_reasoning_effort', 'model_reasoning_summary', 'model_verbosity', 'service_tier'):
            target.pop(field, None)
    if 'model_providers' not in doc:
        doc['model_providers'] = tomlkit.table()
    doc['model_providers'][PROVIDER] = {'name': 'Model Switch · ' + urlsplit(base).hostname,
        'base_url': base, 'wire_api': 'responses', 'supports_websockets': False, 'auth': auth}
    after = tomlkit.dumps(doc).encode('utf-8')
    parsed = tomlkit.parse(after.decode())
    if selected_config(parsed) != (model, PROVIDER):
        raise RuntimeError('配置生成校验失败。')
    return commit_config(path, before, after, root, credential=str(credential))

def commit_config(path, before, after, root, **metadata):
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()) + '-' + uuid.uuid4().hex[:8]
    backup = root / 'backups' / (stamp + '.bin')
    # Backups may contain pre-existing secrets; encrypt the entire original file.
    atomic_write(backup, crypt(before))
    after_backup = root / 'backups' / (stamp + '.after.bin')
    atomic_write(after_backup, crypt(after))
    record = {'path': str(path), 'backup': str(backup), 'existed': path.exists(),
              'after_hash': hashlib.sha256(after).hexdigest(), 'after_backup': str(after_backup),
              'status': 'pending', **metadata}
    journal = root / 'backups' / (stamp + '.json')
    atomic_write(journal, json.dumps(record).encode())
    event('加密备份完成，事务记录：' + journal.name)
    if (path.read_bytes() if path.exists() else b'') != before:
        record['status'] = 'aborted'
        atomic_write(journal, json.dumps(record).encode())
        raise RuntimeError('配置在操作期间发生变化，本次切换已取消，请重试。')
    atomic_write(path, after)
    if path.read_bytes() != after:
        raise RuntimeError('配置回读不一致，请检查备份。')
    record['status'] = 'committed'
    atomic_write(journal, json.dumps(record).encode())
    event('配置写入与回读校验通过，事务已提交')
    return str(journal)

def reset_codex_default(path, root=None):
    """Restore built-in model selection, not a destructive factory reset."""
    root = Path(root or data_path())
    path = Path(path).resolve()
    before, doc = read_config(path)
    if not path.exists():
        return False
    targets = [doc]
    if doc.get('profile') in doc.get('profiles', {}):
        targets.append(doc['profiles'][doc['profile']])
    for target in targets:
        target['model_provider'] = 'openai'
        for field in ('model', 'review_model', 'model_reasoning_effort', 'model_reasoning_summary',
                      'model_supports_reasoning_summaries', 'model_verbosity', 'service_tier',
                      'model_context_window', 'model_auto_compact_token_limit', 'web_search'):
            target.pop(field, None)
    after = tomlkit.dumps(doc).encode('utf-8')
    if selected_config(tomlkit.parse(after.decode())) != ('默认', 'openai'):
        raise RuntimeError('默认配置生成校验失败，未写入。')
    if after == before:
        return False
    commit_config(path, before, after, root, operation='reset_default')
    return True

def legacy_after(record, original, current, root):
    """Recover old write snapshots only when their original SHA256 proves a match."""
    providers = []
    models = [selected_config(current)[0]]
    if PROVIDER in current.get('model_providers', {}):
        providers.append(current['model_providers'][PROVIDER].unwrap())
    try:
        last = json.loads((root / 'last.json').read_text())
        models.append(last['model'])
        providers.append({'name': 'Model Switch · ' + urlsplit(last['base']).hostname,
                          'base_url': last['base'], 'wire_api': 'responses', 'supports_websockets': False,
                          'auth': credential_command(record['credential'])})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for model in models:
        for provider in providers:
            doc = tomlkit.parse(original.decode('utf-8-sig'))
            targets = [doc]
            if doc.get('profile') in doc.get('profiles', {}):
                targets.append(doc['profiles'][doc['profile']])
            for target in targets:
                target['model'] = model
                target['model_provider'] = PROVIDER
                target['web_search'] = 'disabled'
                for field in ('model_reasoning_effort', 'model_reasoning_summary', 'model_verbosity', 'service_tier'):
                    target.pop(field, None)
            if 'model_providers' not in doc:
                doc['model_providers'] = tomlkit.table()
            doc['model_providers'][PROVIDER] = copy.deepcopy(provider)
            raw = tomlkit.dumps(doc).encode('utf-8')
            if hashlib.sha256(raw).hexdigest() == record['after_hash']:
                return raw
    raise RuntimeError('旧版备份缺少切换后快照，无法安全识别改动。原备份仍保留，未覆盖当前配置。')

_MISSING = object()

def merge_undo(before, after, current, prefix=''):
    if before == after or current == before:
        return current
    if all(isinstance(x, dict) or x is _MISSING for x in (before, after, current)) and current is not _MISSING:
        result = copy.deepcopy(current)
        b = {} if before is _MISSING else before
        a = {} if after is _MISSING else after
        for key in dict.fromkeys([*b, *a]):
            value = merge_undo(b.get(key, _MISSING), a.get(key, _MISSING), current.get(key, _MISSING), prefix + key + '.')
            if value is _MISSING:
                result.pop(key, None)
            else:
                result[key] = value
        return _MISSING if not result and before is _MISSING else result
    if current == after:
        return copy.deepcopy(before) if before is not _MISSING else _MISSING
    raise RuntimeError('回滚存在同字段冲突：' + prefix.rstrip('.') + '。该字段在切换后被修改，未覆盖当前配置。')

def plan_restore(path, root=None):
    root = Path(root or data_path())
    path = Path(path).resolve()
    current = path.read_bytes() if path.exists() else b''
    digest = hashlib.sha256(current).hexdigest()
    for j in sorted((root / 'backups').glob('*.json'), reverse=True):
        record = json.loads(j.read_text())
        if os.path.normcase(record['path']) != os.path.normcase(str(path)) or record.get('restored') or record.get('status') == 'aborted':
            continue
        if record.get('status') == 'pending' and record['after_hash'] != digest:
            event('跳过未完成事务：' + j.name, 'WARNING')
            continue
        event('选中回滚记录：' + j.name)
        original = crypt(Path(record['backup']).read_bytes(), True)
        before_doc = tomlkit.parse(original.decode('utf-8-sig'))
        if record['after_hash'] == digest:
            event('当前配置与快照一致，执行完整回滚')
            result = original
            delete = not record['existed']
        else:
            event('当前配置有后续修改，执行字段合并回滚')
            current_doc = tomlkit.parse(current.decode('utf-8-sig'))
            expected = crypt(Path(record['after_backup']).read_bytes(), True) if record.get('after_backup') else legacy_after(record, original, current_doc, root)
            event('切换后快照已读取' if record.get('after_backup') else '旧版备份重建与哈希校验通过')
            if hashlib.sha256(expected).hexdigest() != record['after_hash']:
                raise RuntimeError('切换后快照校验失败，未修改配置。')
            merged = merge_undo(before_doc, tomlkit.parse(expected.decode('utf-8-sig')), current_doc)
            result = tomlkit.dumps(merged).encode('utf-8')
            # TOML associates trailing comments with the last table; keep them
            # even when undo removes a provider table created by this tool.
            comments = Counter(line for line in result.decode().splitlines() if line.lstrip().startswith('#'))
            missing_comments = []
            for line in current.decode('utf-8-sig').splitlines():
                if line.lstrip().startswith('#'):
                    if comments[line]:
                        comments[line] -= 1
                    else:
                        missing_comments.append(line)
            if missing_comments:
                result += ('\n' + '\n'.join(missing_comments) + '\n').encode('utf-8')
            delete = False
        return j, record, current, result, delete
    raise RuntimeError('当前配置没有可恢复的切换记录。')

def restore_config(path, root=None):
    root = Path(root or data_path())
    path = Path(path).resolve()
    j, record, current, result, delete = plan_restore(path, root)
    # Keep the complete pre-undo state as a recovery file, outside the undo stack.
    safety = root / 'backups' / (j.stem + '.pre-restore.bin')
    atomic_write(safety, crypt(current))
    event('回滚前安全备份完成：' + safety.name)
    if (path.read_bytes() if path.exists() else b'') != current:
        raise RuntimeError('恢复期间配置发生变化，请重试。')
    if delete:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, result)
    if (path.read_bytes() if path.exists() else b'') != (b'' if delete else result):
        raise RuntimeError('回滚配置回读不一致，请检查备份。')
    record['restored'] = True
    atomic_write(j, json.dumps(record).encode())
    event('回滚写入与回读校验通过，记录已标记为已恢复')
