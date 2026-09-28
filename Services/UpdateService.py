"""更新源访问与版本比较等纯逻辑,不依赖 Qt,便于单独测试。

更新源为本项目的 GitHub Releases,资产命名约定:

    StudentDataProcessor-<版本>-win64.zip

GitHub 自 2025-06 起会为每个 Release 资产自动计算 SHA256 摘要,
因此无需另外维护 .sha256 文件,直接用 `asset.digest` 校验即可。
"""

import hashlib
import sys
from dataclasses import dataclass

import requests

REPO = "WinkSunYian/StudentDataProcessor"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# 资产文件名前缀,发布脚本据此命名 zip,客户端据此挑资产
ASSET_PREFIX = "StudentDataProcessor-"

USER_AGENT = "StudentDataProcessor-Updater"

# (连接超时, 读取超时),单位秒
HTTP_TIMEOUT = (10, 60)


def is_packaged() -> bool:
    """是否为打包后的 exe 运行。

    源码运行(python main.py)时没有可被替换的 exe,更新功能对其无意义,
    因此入口按钮和启动检查都会隐藏。
    """
    return bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class ReleaseInfo:
    """一个可用于更新的 GitHub Release 摘要。"""

    tag: str  # 原始 tag,如 "v1.1.0"
    notes: str  # Release 正文,当作更新说明展示
    name: str  # 资产文件名
    download_url: str
    size: int  # 字节数,可能为 0
    digest: str  # "sha256:<64位十六进制>",GitHub 可能不给


def parse_release(payload) -> "ReleaseInfo | None":
    """从 GitHub Release 响应里挑出可用的 zip 资产。

    没有 tag 或没有可用 zip 时返回 None。
    """
    if not isinstance(payload, dict):
        return None

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return None

    assets = payload.get("assets") or []
    if not isinstance(assets, list):
        return None

    # 优先取前缀匹配的 zip,否则退回任意 zip
    chosen = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url or not name.lower().endswith(".zip"):
            continue
        if name.startswith(ASSET_PREFIX):
            chosen = asset
            break
        if chosen is None:
            chosen = asset

    if chosen is None:
        return None

    return ReleaseInfo(
        tag=tag,
        notes=str(payload.get("body") or "").strip(),
        name=str(chosen.get("name") or ""),
        download_url=str(chosen.get("browser_download_url") or ""),
        size=int(chosen.get("size") or 0),
        digest=str(chosen.get("digest") or ""),
    )


def fetch_latest_release(timeout=HTTP_TIMEOUT) -> "ReleaseInfo | None":
    """拉取最新 Release 并解析。网络错误/HTTP 错误会抛异常,由调用方兜底。"""
    resp = requests.get(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return parse_release(resp.json())


def _parse_version(text) -> tuple:
    """把 "v1.2.3" / "1.2.3" 解析成可比较的数字元组;解析失败返回 ()。"""
    s = str(text or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]

    parts = []
    for seg in s.split("."):
        seg = seg.strip()
        if not seg.isdigit():
            return ()
        parts.append(int(seg))

    return tuple(parts) if parts else ()


def is_newer(remote_tag, local_version) -> bool:
    """远端版本是否比本地新。

    任一侧解析失败一律不更新(宁可不更新,也不要拿垃圾数据做决定)。
    短的那侧补 0,使 "1.1" 与 "1.1.0" 等价。
    """
    remote = _parse_version(remote_tag)
    local = _parse_version(local_version)
    if not remote or not local:
        return False

    length = max(len(remote), len(local))
    remote = remote + (0,) * (length - len(remote))
    local = local + (0,) * (length - len(local))

    return remote > local


def _parse_digest(digest: str) -> str:
    """从 "sha256:<hex>" 里取出 64 位十六进制;格式不对返回 ""。"""
    text = str(digest or "").strip()
    if ":" not in text:
        return ""
    algo, value = text.split(":", 1)
    if algo.strip().lower() != "sha256":
        return ""
    value = value.strip()
    return value if len(value) == 64 else ""


def verify_sha256(path: str, digest: str) -> bool:
    """校验文件 SHA-256。

    digest 缺失或格式非法时跳过校验直接返回 True —— 校验的意义是防篡改,
    没有可信摘要时不该因此把更新卡死;调用方据此决定是否打日志。
    """
    expected = _parse_digest(digest)
    if not expected:
        return True

    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest().lower() == expected.lower()
