import io
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_portability import audit, inspect, source_files, unchanged_upstream_binary, verified_runtime_hashes
from build_package import find_compiler


class PortabilityTests(unittest.TestCase):
    def test_worktree_metadata_is_excluded_like_git_directories(self):
        with patch('audit_portability.os.walk', return_value=[(ROOT, [], ['.git', 'README.md'])]):
            self.assertEqual(list(source_files()), [ROOT / 'README.md'])

    def test_distributable_source_has_no_machine_paths(self):
        self.assertGreater(audit(), 0)

    def test_detects_paths_in_source_and_binaries(self):
        path = "Q" + ":/" + "/".join(["Users", "example", "project"])
        self.assertIsNotNone(inspect("test.py", io.BytesIO(path.encode())))
        self.assertIsNotNone(inspect("test.exe", io.BytesIO(str(ROOT).encode("utf-16-le"))))
        self.assertIsNone(inspect("test.py", io.BytesIO(b'Path(__file__).parent / "runtime"')))

    def test_only_exact_upstream_binary_bytes_are_exempt(self):
        name = "STEVE/runtime/bin/vendor"
        payload = str(ROOT).encode("utf-16-le")
        hashes = {name: hashlib.sha256(payload).hexdigest()}
        self.assertTrue(unchanged_upstream_binary(name, io.BytesIO(payload), hashes))
        self.assertFalse(unchanged_upstream_binary(name, io.BytesIO(payload + b"modified"), hashes))
        self.assertFalse(unchanged_upstream_binary("Install STEVE.command", io.BytesIO(payload), hashes))
        self.assertFalse(unchanged_upstream_binary(name, io.BytesIO(payload), {}))

    def test_rejects_unverified_upstream_archive(self):
        for target in ("x86_64-pc-windows-msvc", "aarch64-apple-darwin"):
            with patch.object(Path, "is_file", return_value=True), \
                    patch.object(Path, "open", return_value=io.BytesIO(b"untrusted archive")):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    verified_runtime_hashes(target)

    def test_installer_script_is_scanned_for_absolute_paths(self):
        self.assertIsNotNone(inspect("Install STEVE.command", io.BytesIO(b'cp "/' + b'Users/example/STEVE" target')))
        self.assertIsNone(inspect("Install STEVE.command", io.BytesIO(b'ADDINS="$HOME/Library/Application Support"')))

    def test_compiler_follows_system_root(self):
        windows = ROOT / ".cache" / "alternate-windows"
        compiler = windows / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        with patch.dict(os.environ, {"SystemRoot": str(windows)}), patch("build_package.shutil.which", return_value=None), \
                patch.object(Path, "is_file", lambda candidate: candidate == compiler):
            self.assertEqual(find_compiler(), compiler)

    def test_compiler_uses_path_when_available(self):
        candidate = ROOT / ".cache/compiler/csc.exe"
        with patch("build_package.shutil.which", return_value=str(candidate)):
            self.assertEqual(find_compiler(), candidate)


if __name__ == "__main__":
    unittest.main()
