"""InstallSkill 核心逻辑：下载 zip、校验路径、解压与热重载。"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
MAX_ZIP_SIZE = 50 * 1024 * 1024


async def install_from_url(source: str, catalog, work_dir: Path, on_reloaded=None) -> str:
    """从 URL（或本地 zip 路径）安装 Skill 并热重载 Catalog。"""
    data = await asyncio.to_thread(_download, source)
    return install_from_zip_bytes(data, catalog, work_dir, on_reloaded=on_reloaded)


def install_from_zip_bytes(data: bytes, catalog, work_dir: Path, on_reloaded=None) -> str:
    """从 zip 字节安装 Skill，供单测直接调用。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            top = _validate_zip_names(names)
            target_root = Path.home() / ".forgecode" / "skills"
            target = (target_root / top).resolve()
            root = target_root.resolve()
            if not _is_within(target, root):
                raise ValueError(f"unsafe path in zip: {top}")
            target.mkdir(parents=True, exist_ok=True)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = PurePosixPath(info.filename).parts[1:]
                dest = target.joinpath(*parts)
                if not _is_within(dest.resolve(), root):
                    raise ValueError(f"unsafe path in zip: {info.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid zip: {e}") from e

    catalog.reload(work_dir)
    if on_reloaded is not None:
        on_reloaded()
    return top


def _download(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "forgecode"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP_SIZE:
                    raise ValueError("zip too large")
                chunks.append(chunk)
            return b"".join(chunks)
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"source not found: {source}")
    data = path.read_bytes()
    if len(data) > MAX_ZIP_SIZE:
        raise ValueError("zip too large")
    return data


def _validate_zip_names(names: list[str]) -> str:
    if not names:
        raise ValueError("empty zip")
    top: str | None = None
    for name in names:
        normalized = name.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if not parts or parts[0] in ("", ".", "..") or ".." in parts:
            raise ValueError(f"unsafe path in zip: {name}")
        if normalized.startswith("/") or normalized.startswith("\\"):
            raise ValueError(f"unsafe path in zip: {name}")
        if top is None:
            top = parts[0]
        elif parts[0] != top:
            raise ValueError(f"unsafe path in zip: {name}")
    assert top is not None
    if not _NAME_RE.fullmatch(top):
        raise ValueError(f"invalid skill name in zip: {top}")
    return top


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
