from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_UPLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024


def unsafe_component(name):
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}
    return (not name or name.endswith(('.', ' ')) or name.split('.')[0].upper() in reserved
            or any(char in name for char in '<>:"|?*\x00') or any(ord(char) < 32 for char in name))


def save_upload(name: str, data: bytes, target: Path) -> Path:
    if len(data) > MAX_UPLOAD:
        raise ValueError('上传超过 20 MB 限制')
    if not name or '/' in name or '\\' in name or unsafe_component(name):
        raise ValueError('文件名无效')
    suffix = Path(name).suffix.lower()
    if suffix not in {'.py', '.zip'}:
        raise ValueError('请选择 .py 文件或 ZIP 项目')
    target.mkdir(parents=True, exist_ok=False)
    if suffix == '.py':
        source = target / name
        source.write_bytes(data)
        return source
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(item.file_size for item in entries) > MAX_EXPANDED:
            raise ValueError('ZIP 解压后的内容过大')
        seen = set()
        for item in entries:
            name = item.orig_filename
            path = PurePosixPath(name)
            if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts
                    or any(unsafe_component(part) for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('ZIP 包含不安全路径')
            dest = target.joinpath(*path.parts)
            if not dest.resolve().is_relative_to(target.resolve()):
                raise ValueError('ZIP 路径越界')
            key = str(dest).lower()
            if key in seen:
                raise ValueError('ZIP 包含重复路径')
            seen.add(key)
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(item))
    children = list(target.iterdir())
    return children[0] if len(children) == 1 and children[0].is_dir() else target
