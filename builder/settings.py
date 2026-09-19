"""Local configuration. Explicit environment overrides > SQLite > defaults."""
from __future__ import annotations

import argparse
import base64
import getpass
import ctypes
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from .urls import normalize_base_url, local_base_url

DEFAULTS = dict(allowed_hosts='127.0.0.1,localhost,testserver', retention_days=7,
                ai_enabled=False, ai_provider='openai-compatible',
                ai_base_url='https://api.openai.com/v1', ai_model='', ai_api_key='',
                feishu_enabled=False, feishu_webhook='', cookie_secure=False,
                base_url='http://127.0.0.1:8000', admin_token='')
SECRET_FIELDS = {'ai_api_key', 'feishu_webhook', 'admin_token'}
EDITABLE = set(DEFAULTS) - {'cookie_secure', 'admin_token'}
MASK = '********'


def notification_secrets(values):
    return [values.get(key, '') for key in SECRET_FIELDS] + [os.environ.get('BUILDER_ADMIN_PASSWORD', '')]


def allowed_hosts(raw):
    hosts = list(dict.fromkeys(h.strip().lower() for h in raw.split(',') if h.strip()))
    if not hosts:
        raise ValueError('Allowed Hosts 不能为空')
    for host in hosts:
        if host != '*' and not re.fullmatch(r'(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host):
            raise ValueError('Allowed Hosts 只接受主机名或 IPv4，不含协议、端口或路径')
        if '..' in host:
            raise ValueError('Allowed Hosts 格式无效')
    return hosts


def validate(values):
    values = dict(values)
    values['base_url'] = normalize_base_url(values['base_url'])
    values['allowed_hosts'] = ','.join(allowed_hosts(values['allowed_hosts']))
    if type(values['retention_days']) is not int or not 1 <= values['retention_days'] <= 3650:
        raise ValueError('保留天数必须为 1–3650 的整数')
    for key in ('ai_enabled', 'feishu_enabled', 'cookie_secure'):
        if type(values[key]) is not bool:
            raise ValueError('开关必须为布尔值')
    if values['ai_provider'] != 'openai-compatible':
        raise ValueError('目前支持 OpenAI compatible Provider')
    for key in ('ai_base_url', 'feishu_webhook'):
        value = values[key]
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('服务地址必须是有效 HTTP(S) URL，不能包含用户名或密码')
            if key == 'ai_base_url' and parsed.query:
                raise ValueError('AI Base URL 不能包含查询参数')
    for key, value in values.items():
        if isinstance(value, str) and (len(value) > 4096 or any(c in value for c in '\r\n\x00')):
            raise ValueError('配置长度或格式无效')
    return values


def environment_settings(saved=None):
    values = DEFAULTS | (saved or {})
    overridden = []
    for key, default in DEFAULTS.items():
        name = 'BUILDER_' + key.upper()
        if name not in os.environ:
            continue
        raw = os.environ[name].strip()
        if isinstance(default, bool):
            if raw.lower() not in {'1', '0', 'true', 'false'}:
                raise ValueError(name + ' must be true/false')
            raw = raw.lower() in {'1', 'true'}
        elif isinstance(default, int):
            raw = int(raw)
        values[key] = raw
        overridden.append(key)
    # Preserve pre-settings deployments that configured credentials alone.
    for flag, required in [('ai_enabled', ('ai_api_key', 'ai_model')), ('feishu_enabled', ('feishu_webhook',))]:
        if flag not in overridden and flag not in (saved or {}):
            values[flag] = all(values[key] for key in required)
    return validate(values), overridden


def protect(value, decrypt=False):
    """Windows user-scoped DPAPI; POSIX relies on private directory/file modes."""
    if os.name != 'nt':
        return value
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    api.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('Windows credential protection failed')
    try:
        result = ctypes.string_at(output.data, output.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL)')
        if os.name != 'nt':
            self.path.chmod(0o600)
        password = os.environ.get('BUILDER_ADMIN_PASSWORD')
        if password and not self.initialized():
            if len(password) > 1024:
                raise ValueError('BUILDER_ADMIN_PASSWORD must not exceed 1024 characters')
            salt = secrets.token_bytes(16)
            digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
            with self.connect() as db:
                db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('password_hash', salt.hex() + ':' + digest))

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def saved(self):
        with self.connect() as db:
            rows = db.execute("SELECT key,value FROM settings WHERE key != 'password_hash'").fetchall()
        return {key: json.loads(protect(value, True) if key in SECRET_FIELDS else value) for key, value in rows}

    def effective(self):
        return environment_settings(self.saved())[0]

    def public(self):
        values, overridden = environment_settings(self.saved())
        result = {key: (MASK if values[key] else '') if key in SECRET_FIELDS else values[key] for key in EDITABLE}
        result['overridden'] = [key for key in overridden if key in EDITABLE]
        result['base_url_local'] = local_base_url(values['base_url'])
        return result

    def merged(self, payload):
        if set(payload) - EDITABLE:
            raise ValueError('包含不支持的配置字段')
        changes = {}
        for key, value in payload.items():
            if key in SECRET_FIELDS and value in ('', MASK, None):
                continue
            if isinstance(DEFAULTS[key], str) and not isinstance(value, str):
                raise ValueError('配置必须为文本')
            changes[key] = value.strip() if isinstance(value, str) else value
        values = validate(DEFAULTS | self.saved() | changes)
        return values, changes

    def save(self, payload):
        values, changes = self.merged(payload)
        effective = environment_settings(self.saved() | {key: values[key] for key in changes})[0]
        if effective['ai_enabled'] and not all(effective[key] for key in ('ai_api_key', 'ai_base_url', 'ai_model')):
            raise ValueError('启用 AI 需要 API 地址、模型和密钥')
        if effective['feishu_enabled'] and not effective['feishu_webhook']:
            raise ValueError('启用飞书需要 Webhook')
        with self.connect() as db:
            for key in changes:
                value = json.dumps(values[key])
                if key in SECRET_FIELDS:
                    value = protect(value)
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, value))
        return self.public()

    def preview(self, payload):
        values, changes = self.merged(payload)
        return environment_settings(self.saved() | {key: values[key] for key in changes})[0]

    def initialized(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM settings WHERE key='password_hash'").fetchone() is not None

    def set_admin_password(self, password):
        if not isinstance(password, str) or not 8 <= len(password) <= 1024:
            raise ValueError('管理员密码长度需要 8–1024 个字符')
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",
                ('password_hash', salt.hex() + ':' + digest),
            )
            db.execute('DELETE FROM sessions')
        return True

    def authenticate(self, password):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone()
        if not row or len(password) > 1024:
            return False
        salt, digest = row[0].split(':')
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return secrets.compare_digest(actual, digest)

    def new_session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 28800))
        return token

    def session(self, token):
        with self.connect() as db:
            row = db.execute('SELECT csrf FROM sessions WHERE token=? AND expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row[0] if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))


def _cli() -> int:
    parser = argparse.ArgumentParser(description='Smart Python Builder settings administration')
    parser.add_argument(
        '--database',
        default='web-data/settings.sqlite3',
        help='Settings SQLite path (default: web-data/settings.sqlite3)',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('reset-admin-password', help='Interactively reset the administrator password')
    args = parser.parse_args()

    if args.command == 'reset-admin-password':
        first = getpass.getpass('New admin password: ')
        second = getpass.getpass('Confirm admin password: ')
        if first != second:
            parser.error('两次输入的管理员密码不一致')
        try:
            SettingsStore(args.database).set_admin_password(first)
        except ValueError as exc:
            parser.error(str(exc))
        print('Administrator password updated; existing admin sessions were logged out.')
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(_cli())
