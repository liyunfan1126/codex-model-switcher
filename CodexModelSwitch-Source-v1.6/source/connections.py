"""Connection profiles; each API key is bound to its own endpoint."""
import json
import copy
import uuid
from pathlib import Path
from core import OPENROUTER, atomic_write, crypt, normalize_url

GATEWAY = '聚合 / 中转 · 我的平台'
ROUTER = 'OpenRouter · 专用 Key'
CUSTOM = '自定义 Responses 接口'
MODES = [GATEWAY, ROUTER, CUSTOM]

class PlatformStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'platforms.bin'
        if self.path.exists():
            self.data = json.loads(crypt(self.path.read_bytes(), True).decode('utf-8'))
            if self.data.get('version') != 2 or not isinstance(self.data.get('platforms'), dict):
                raise ValueError('平台配置文件格式无效。')
        else:
            old = load_connections(root)
            self.data = {'version': 2, 'active': None, 'platforms': {}}
            for mode, profile in old['profiles'].items():
                if not profile.get('base'):
                    continue
                ident = uuid.uuid4().hex
                self.data['platforms'][ident] = dict(profile, name='OpenRouter' if mode == ROUTER else mode, mode=mode, models=[], catalog_base='')
                if mode == old['active']:
                    self.data['active'] = ident
            # Persist migration once; deletion of all platforms must not reimport old keys.
            self._commit(self.data)

    def _commit(self, data):
        atomic_write(self.path, crypt(json.dumps(data, ensure_ascii=False).encode('utf-8')))
        self.data = data

    def save(self, ident, profile):
        p = copy.deepcopy(profile)
        p['name'] = p.get('name', '').strip()
        if not p['name'] or len(p['name']) > 48:
            raise ValueError('平台名称需为 1–48 个字符。')
        if any(x['name'].casefold() == p['name'].casefold() for k, x in self.data['platforms'].items() if k != ident):
            raise ValueError('已有同名平台，请换一个名称。')
        p['base'] = connection_base(p['mode'], p['base'])
        if not p.get('key', '').strip():
            raise ValueError('请输入该平台的 API Key。')
        ident = ident or uuid.uuid4().hex
        data = copy.deepcopy(self.data)
        data['platforms'][ident] = p
        data['active'] = ident
        self._commit(data)
        return ident

    def delete(self, ident):
        data = copy.deepcopy(self.data)
        del data['platforms'][ident]
        if data['active'] == ident:
            data['active'] = next(iter(data['platforms']), None)
        self._commit(data)

    def activate(self, ident):
        if ident not in self.data['platforms']:
            raise ValueError('平台记录不存在。')
        data = copy.deepcopy(self.data)
        data['active'] = ident
        self._commit(data)

def load_connections(root):
    path = Path(root) / 'connections.bin'
    if path.exists():
        data = json.loads(crypt(path.read_bytes(), True).decode('utf-8'))
        if data.get('active') not in MODES or not isinstance(data.get('profiles'), dict):
            raise ValueError('接口配置记录格式无效。')
        return data
    old = Path(root) / 'last.json'
    if old.exists():
        d = json.loads(old.read_text(encoding='utf-8'))
        base = normalize_url(d['base'])
        mode = ROUTER if base == OPENROUTER else GATEWAY
        key = crypt(Path(d['credential']).read_bytes(), True).decode('utf-8')
        return {'active': mode, 'profiles': {mode: {'base': base, 'key': key, 'model': d.get('model', '')}}}
    return {'active': GATEWAY, 'profiles': {}}

def save_connections(root, data):
    atomic_write(Path(root) / 'connections.bin', crypt(json.dumps(data, ensure_ascii=False).encode('utf-8')))

def connection_base(mode, base):
    normalized = normalize_url(base)
    if mode == ROUTER and normalized != OPENROUTER:
        raise ValueError('OpenRouter 预设只能使用 OpenRouter 地址。其他平台请选择“聚合 / 中转”。')
    return normalized

def family_matches(model, family):
    if family == '全部': return True
    text = (model.get('id', '') + ' ' + model.get('name', '')).lower()
    tokens = {'Claude': ('claude', 'anthropic'), 'GPT': ('gpt', 'openai/', 'o1', 'o3', 'o4'),
              'Gemini': ('gemini',), 'DeepSeek': ('deepseek',), 'Qwen': ('qwen',),
              'Kimi': ('kimi', 'moonshot'), 'GLM': ('glm', 'z-ai'), 'MiniMax': ('minimax',)}
    return any(t in text for t in tokens.get(family, ()))
