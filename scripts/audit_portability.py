"""Check distributable source or a release zip for machine-specific paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
EXCLUDED = {".git", ".cache", "dist", "node_modules", ".venv", ".vscode", "__pycache__", "runtime", ".codex", ".agents"}
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".json", ".md", ".txt", ".html", ".css", ".cs", ".manifest", ".svg", ".yml", ".yaml", ".toml",
                 ".sh", ".command"}
ABSOLUTE_PATH = re.compile(r"(?i)\b[a-z]:[\\/]|/(?:Users|home)/[\w.-]+/|file:/{3}")


def source_files():
    for directory, subdirs, files in os.walk(ROOT):
        subdirs[:] = [name for name in subdirs if name not in EXCLUDED]
        for name in files:
            if name in EXCLUDED:  # Git worktrees use a .git file rather than a directory.
                continue
            path = Path(directory) / name
            if path.suffix not in {".pyc", ".pyo"}:
                yield path


def local_markers():
    markers = set()
    for path in (ROOT, Path.home()):
        for spelling in (str(path), path.as_posix(), str(path).replace("\\", "\\\\")):
            markers.add(spelling.encode("utf-8").lower())
            markers.add(spelling.encode("utf-16-le").lower())
    return markers


def inspect(name, stream):
    """Stream binaries too: an installer must not embed the build user's path."""
    markers = local_markers()
    overlap = max(map(len, markers))
    tail = b""
    while chunk := stream.read(1024 * 1024):
        data = tail + chunk
        if any(marker in data.lower() for marker in markers):
            return f"{name}: contains this machine's checkout or profile path"
        if Path(name).suffix.lower() in TEXT_SUFFIXES:
            if ABSOLUTE_PATH.search(data.decode("utf-8", errors="replace")):
                return f"{name}: contains a literal absolute filesystem path"
        tail = data[-max(overlap, 512):]
    return None


def verified_runtime_hashes(target=None):
    """Identify upstream runtime files by bytes, never by an allowlisted path alone."""
    from fetch_runtime import archive_digest, cached_archive
    from steve.transport import host_target
    target = target or host_target()
    archive = cached_archive(target)
    if not archive.is_file():
        return {}
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != archive_digest(target):
            raise RuntimeError("Upstream runtime archive checksum mismatch")
    hashes = {}
    with tarfile.open(archive) as package:
        for member in package:
            if member.isfile():
                with package.extractfile(member) as stream:
                    hashes["STEVE/runtime/" + Path(member.name).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashes


def packaged_runtime_target(package):
    try:
        return json.loads(package.read("STEVE/runtime/steve-runtime.json")).get("target")
    except (KeyError, ValueError, AttributeError):
        return None


def unchanged_upstream_binary(name, stream, hashes):
    expected = hashes.get(name)
    return expected is not None and hashlib.file_digest(stream, "sha256").hexdigest() == expected


def audit(archive=None):
    failures = []
    count = 0
    upstream_hashes = None
    if archive:
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if entry.is_dir():
                    continue
                if {".vscode", "__pycache__"}.intersection(Path(entry.filename).parts) or Path(entry.filename).suffix in {".pyc", ".pyo"}:
                    failures.append(f"{entry.filename}: local debugger or bytecode artifact")
                with package.open(entry) as stream:
                    failure = inspect(entry.filename, stream)
                if failure and entry.filename.startswith("STEVE/runtime/"):
                    # Vendor debug strings can name the same generic CI profile.
                    # Accept them only when the entire file matches the pinned download.
                    if upstream_hashes is None:
                        upstream_hashes = verified_runtime_hashes(packaged_runtime_target(package))
                    with package.open(entry) as stream:
                        if unchanged_upstream_binary(entry.filename, stream, upstream_hashes):
                            failure = None
                count += 1
                if failure:
                    failures.append(failure)
    else:
        for path in source_files():
            with path.open("rb") as stream:
                failure = inspect(path.relative_to(ROOT).as_posix(), stream)
            count += 1
            if failure:
                failures.append(failure)
    if failures:
        raise RuntimeError("Portability audit failed:\n" + "\n".join(failures))
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    print(f"Portability audit passed: {audit(args.archive)} files")
