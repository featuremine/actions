"""Run action entrypoints with fake Apple tools; never access a real keychain."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIGNING = ROOT / "macos/setup-signing"
NOTARY = ROOT / "macos/notarize"

# All credential/keychain commands are intercepted, including those in Bash.
TOOL = r'''
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if " ".join([name, *args]).startswith(os.environ.get("FAIL_COMMAND", "never-match")):
    sys.exit(1)
if name == "security":
    if args == ["list-keychains", "-d", "user"]:
        print('    "/Users/test/Library/Keychains/login.keychain-db"')
        print('    "/Users/test/custom keychain.keychain-db"')
    elif args[0] == "create-keychain":
        Path(args[-1]).touch()
    elif args[0] == "delete-keychain":
        Path(args[-1]).unlink()
    elif args[0] == "find-identity":
        print('1) A "Developer ID Application: Test (TEAM)"')
        if not os.environ.get("MISSING_INSTALLER"):
            print('2) B "Developer ID Installer: Test (TEAM)"')
    elif args[0] == "find-certificate" and os.environ.get("INTERMEDIATE_INSTALLED"):
        print('SHA-256 hash: AABB')
elif name == "openssl":
    print("test-random-password" if args[0] == "rand" else "sha256 Fingerprint=AA:BB")
elif name == "curl":
    Path(args[args.index("--output") + 1]).write_bytes(b"test intermediate")
elif name == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        print(json.dumps({"id": "test-submission", "status": os.environ.get("NOTARY_STATUS", "Accepted")}))
    elif args[:2] == ["notarytool", "log"]:
        Path(args[-1]).write_text('{"issues": []}')
'''


class MacOSCredentialsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="macos actions test ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.runner = self.root / "runner temp"
        self.runner.mkdir()
        self.log = self.root / "commands.jsonl"
        for command in ("security", "openssl", "curl", "xcrun", "pkgutil", "spctl"):
            script = self.bin / command
            script.write_text(f"#!{sys.executable}\n" + TOOL)
            script.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "COMMAND_LOG": str(self.log),
            "RUNNER_TEMP": str(self.runner),
            "RUNNER_OS": "macOS",
            "GITHUB_STATE": str(self.root / "state"),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "INPUT_CERTIFICATES-P12-BASE64": base64.b64encode(b"test P12").decode(),
            "INPUT_CERTIFICATES-PASSWORD": "test-P12-password",
            "INPUT_APPLICATION-IDENTITY": "Developer ID Application: Test (TEAM)",
            "INPUT_INSTALLER-IDENTITY": "Developer ID Installer: Test (TEAM)",
            "MACOS_NOTARY_APPLE_ID": "test@example.invalid",
            "MACOS_NOTARY_APP_PASSWORD": "test-app-password",
            "MACOS_NOTARY_TEAM_ID": "TEAM",
            "PACKAGE_DIRECTORY": str(self.root / "packages"),
            "NOTARY_TIMEOUT": "60m",
            "NOTARY_DIAGNOSTICS": str(self.root / "diagnostics"),
            "ACTION_PATH": str(NOTARY),
        }
        packages = Path(self.env["PACKAGE_DIRECTORY"])
        packages.mkdir()
        (packages / "Test App.pkg").write_bytes(b"test installer")

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_node(self, script):
        # Exercise the same macOS path on Linux CI, with every Apple tool mocked.
        return subprocess.run([
            shutil.which("node"), "-e",
            "Object.defineProperty(process, 'platform', {value: 'darwin'}); require(process.argv[1]);",
            str(SIGNING / script),
        ], env=self.env, text=True, capture_output=True)

    def cleanup_signing(self):
        state = (self.root / "state").read_text().strip().split("=", 1)[1]
        self.env["STATE_signing_directory"] = state
        result = self.run_node("cleanup.js")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(state).exists())
        self.assertIn([
            "security", "list-keychains", "-d", "user", "-s",
            "/Users/test/Library/Keychains/login.keychain-db",
            "/Users/test/custom keychain.keychain-db",
        ], self.commands())

    def test_signing_imports_and_restores_existing_search_list(self):
        result = self.run_node("index.js")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        keychain = Path((self.root / "output").read_text().strip().split("=", 1)[1])
        self.assertTrue(keychain.is_file())
        self.assertFalse((keychain.parent / "identities.p12").exists())
        self.assertIn([
            "security", "list-keychains", "-d", "user", "-s", str(keychain),
            "/Users/test/Library/Keychains/login.keychain-db",
            "/Users/test/custom keychain.keychain-db",
        ], self.commands())
        self.cleanup_signing()

    def test_import_failure_still_allows_post_cleanup(self):
        self.env["FAIL_COMMAND"] = "security import"
        result = self.run_node("index.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(self.env["INPUT_CERTIFICATES-PASSWORD"], result.stdout + result.stderr)
        self.assertFalse(list(self.runner.rglob("identities.p12")))
        self.cleanup_signing()

    def test_missing_private_key_identity_fails(self):
        self.env["MISSING_INSTALLER"] = "1"
        result = self.run_node("index.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("both configured Developer ID identities", result.stdout)
        self.cleanup_signing()

    def test_existing_intermediate_is_not_imported_again(self):
        self.env["INTERMEDIATE_INSTALLED"] = "1"
        result = self.run_node("index.js")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        imports = [command for command in self.commands() if command[:2] == ["security", "import"]]
        self.assertEqual(len(imports), 1)
        self.assertTrue(imports[0][2].endswith("identities.p12"))
        self.cleanup_signing()

    def test_missing_input_fails_before_keychain_access(self):
        self.env["INPUT_CERTIFICATES-PASSWORD"] = ""
        result = self.run_node("index.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual(list(self.runner.iterdir()), [])

    def test_notary_cleanup_after_success_rejection_and_credential_failure(self):
        for status, failure in (("Accepted", ""), ("Invalid", ""),
                                ("Accepted", "xcrun notarytool store-credentials")):
            with self.subTest(status=status, failure=failure):
                self.log.write_text("")
                self.env["NOTARY_STATUS"] = status
                self.env["FAIL_COMMAND"] = failure or "never-match"
                result = subprocess.run(["bash", str(NOTARY / "notarize.sh")],
                                        env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, status == "Accepted" and not failure,
                                 result.stdout + result.stderr)
                self.assertNotIn(self.env["MACOS_NOTARY_APP_PASSWORD"], result.stdout + result.stderr)
                self.assertEqual(list(self.runner.iterdir()), [])
                self.assertTrue(any(cmd[:2] == ["security", "delete-keychain"] for cmd in self.commands()))
                if status != "Accepted" or failure:
                    self.assertFalse(any(cmd[:2] == ["xcrun", "stapler"] for cmd in self.commands()))
