#!/usr/bin/env python3
"""Install or uninstall Splendid Url Context as a native Zen Mod."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile

try:
    import fcntl
except ImportError:
    fcntl = None

OWNER = "zen-mod-url-context native installer v1\n"
FILES = {
    "chrome.css": "zen-url-context.css",
    "readme.md": "README.md",
}
LEGACY_CSS = "zen-url-context.css"
LEGACY_CSS_START = "/* BEGIN zen-url-context managed block */"
LEGACY_CSS_END = "/* END zen-url-context managed block */"
LEGACY_PREF_START = "// BEGIN zen-url-context managed block"
LEGACY_PREF_END = "// END zen-url-context managed block"
LEGACY_IMPORT = '@import url("zen-url-context.css");'


def safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Refusing symlink: {part}")


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(data):
    def invalid(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=invalid)


def atomic_write(path, data):
    safe(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_registry(path, registry, original):
    data = (json.dumps(registry, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if original is not None and load_json(original) == registry:
        return
    if original is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        fd, name = tempfile.mkstemp(prefix=f"{path.name}.backup-{stamp}-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    atomic_write(path, data)


def stale_local_lock(path):
    match = re.fullmatch(r"(.+):\+([1-9][0-9]*)", os.readlink(path))
    if not match:
        return False
    host, pid = match.groups()
    hostname = socket.gethostname()
    local_hosts = {hostname.lower(), socket.getfqdn().lower()}
    try:
        local_hosts.update(
            result[4][0].lower()
            for result in socket.getaddrinfo(hostname, None)
        )
    except OSError:
        return False
    if host.lower() not in local_hosts:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return True
    except OSError:
        pass
    return False


@contextmanager
def profile_locks(profile):
    with ExitStack() as stack:
        for name in ("parent.lock", ".parentlock", "lock"):
            path = profile / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                if fcntl is None or not stale_local_lock(path):
                    raise ValueError(f"Refusing active or unverifiable profile lock: {path}")
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"Refusing non-regular profile lock: {path}")
            if fcntl is None:
                raise ValueError(f"Cannot verify existing profile lock on this platform: {path}")
            try:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
                stack.callback(os.close, fd)
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                    info.st_dev, info.st_ino
                ):
                    raise ValueError(f"Profile lock changed during inspection: {path}")
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError(f"Profile lock is active or cannot be verified: {path}") from error
        yield


def remove_managed_block(content, start, end, path):
    pattern = re.compile(
        rf"(?m)^{re.escape(start)}\r?\n.*?^{re.escape(end)}(?:\r?\n)?",
        re.DOTALL,
    )
    matches = list(pattern.finditer(content))
    if len(matches) > 1:
        raise ValueError(f"Multiple managed blocks found in {path}")
    if matches:
        match = matches[0]
        content = content[:match.start()] + content[match.end():]
    elif start in content or end in content:
        raise ValueError(f"Incomplete managed block found in {path}")
    return content


def update(profile, action, source=None):
    if action not in ("install", "uninstall"):
        raise ValueError("Action must be install or uninstall")
    try:
        profile = Path(profile).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot resolve PROFILE: {profile}: {error}") from error
    safe(profile)
    safe(profile / "prefs.js")
    if not profile.is_dir() or not (profile / "prefs.js").is_file():
        raise ValueError("PROFILE must be an existing Zen profile containing prefs.js")
    with profile_locks(profile):
        _update(profile, action, Path(source) if source else Path(__file__).parent)


def _update(profile, action, source):
    safe(source)
    source = Path(os.path.abspath(source))
    manifest_path = source / "manifest.json"
    safe(manifest_path)
    manifest = load_json(manifest_path.read_bytes())
    fields = ("id", "name", "description", "version", "author")
    if not isinstance(manifest, dict) or any(
        not isinstance(manifest.get(key), str) or not manifest[key].strip()
        for key in fields
    ):
        raise ValueError("Manifest requires nonempty string id, name, description, version, author")
    mod_id = manifest["id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", mod_id) or mod_id in (".", ".."):
        raise ValueError("Manifest id must be a safe, stable directory name")

    chrome = profile / "chrome"
    target = chrome / "zen-themes" / mod_id
    marker = target / ".zen-url-context-owner"
    registry_path = profile / "zen-themes.json"
    for path in (chrome, target, marker, registry_path, *(target / name for name in FILES)):
        safe(path)
        if path.exists() and path not in (chrome, target) and not path.is_file():
            raise ValueError(f"Expected a regular file: {path}")
    for path in (chrome, target.parent, target):
        if path.exists() and not path.is_dir():
            raise ValueError(f"Expected a directory: {path}")

    original = registry_path.read_bytes() if registry_path.exists() else None
    registry = load_json(original) if original is not None else {}
    if not isinstance(registry, dict) or any(
        not isinstance(entry, dict)
        or ("id" in entry and entry["id"] != key)
        or ("enabled" in entry and not isinstance(entry["enabled"], bool))
        for key, entry in registry.items()
    ):
        raise ValueError("zen-themes.json must be an object keyed by mod id with object entries")

    owned = marker.is_file() and marker.read_text(encoding="utf-8") == OWNER + mod_id + "\n"
    urls = {
        "style": (target / "chrome.css").as_uri(),
        "readme": (target / "readme.md").as_uri(),
    }
    entry = registry.get(mod_id)
    if target.exists() and not owned:
        raise ValueError(f"Refusing unmanaged mod directory: {target}")
    if entry is not None and (
        not owned or entry.get("id") != mod_id
        or any(entry.get(key) != value for key, value in urls.items())
    ):
        raise ValueError("Refusing unmanaged or changed registry entry")

    if action == "uninstall":
        if entry is not None:
            del registry[mod_id]
            write_registry(registry_path, registry, original)
        if owned:
            for name in FILES:
                (target / name).unlink(missing_ok=True)
            if set(target.iterdir()) == {marker}:
                marker.unlink()
                target.rmdir()
        print("Splendid Url Context uninstalled; unrelated files and preferences left unchanged.")
        return

    payload = {}
    for destination, filename in FILES.items():
        source_file = source / filename
        safe(source_file)
        payload[destination] = source_file.read_bytes()
    user_css = chrome / "userChrome.css"
    user_js = profile / "user.js"
    legacy_css = chrome / LEGACY_CSS
    for path in (user_css, user_js, legacy_css):
        safe(path)
    old_css = user_css.read_bytes() if user_css.exists() else b""
    old_js = user_js.read_bytes() if user_js.exists() else b""
    css_text = remove_managed_block(old_css.decode("utf-8"), LEGACY_CSS_START, LEGACY_CSS_END, user_css)
    js_text = remove_managed_block(old_js.decode("utf-8"), LEGACY_PREF_START, LEGACY_PREF_END, user_js)
    if LEGACY_IMPORT in css_text:
        raise ValueError("Found an unmanaged URL Context import; remove it manually first")
    if legacy_css.exists() and "Zen Mod: URL Context Quick Actions" not in legacy_css.read_text(encoding="utf-8"):
        raise ValueError(f"Refusing to overwrite unrelated file: {legacy_css}")

    target.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        atomic_write(target / name, data)
    atomic_write(marker, (OWNER + mod_id + "\n").encode("utf-8"))
    metadata = dict(entry or {})
    metadata.update({key: manifest[key] for key in fields})
    metadata.update(urls)
    metadata.setdefault("enabled", True)
    registry[mod_id] = metadata
    try:
        if css_text != old_css.decode("utf-8"):
            atomic_write(user_css, css_text.encode("utf-8"))
        if js_text != old_js.decode("utf-8"):
            if js_text:
                atomic_write(user_js, js_text.encode("utf-8"))
            else:
                user_js.unlink(missing_ok=True)
        write_registry(registry_path, registry, original)
    except (OSError, ValueError):
        if css_text != old_css.decode("utf-8"):
            atomic_write(user_css, old_css)
        if js_text != old_js.decode("utf-8"):
            if old_js:
                atomic_write(user_js, old_js)
            else:
                user_js.unlink(missing_ok=True)
        raise
    print(f"{manifest['name']} installed in {target}. Restart Zen.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--profile", default=os.environ.get("PROFILE"), type=Path)
    args = parser.parse_args()
    if args.profile is None:
        parser.error("Set PROFILE or pass --profile")
    try:
        update(args.profile, args.action)
    except (OSError, ValueError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
