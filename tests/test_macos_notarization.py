"""Exercise notarization gates without Apple credentials or macOS tools."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "notarize_macos", Path(__file__).resolve().parents[1] / "macos/notarize/notarize.py")
notarize_macos = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notarize_macos)


class MacOSNotarizationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "Carnitas UI.pkg"
        self.package.write_bytes(b"signed installer")
        self.diagnostics = self.root / "diagnostics"
        self.response = json.dumps({"id": "test-submission", "status": "Accepted"})
        self.submit_exit = 0
        self.log_exit = 0
        self.fail_command = None
        self.commands = []
        mock = patch.object(notarize_macos.subprocess, "run", side_effect=self.run_command)
        mock.start()
        self.addCleanup(mock.stop)

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        if command[:len(self.fail_command or [])] == self.fail_command:
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ["xcrun", "notarytool", "submit"]:
            return subprocess.CompletedProcess(command, self.submit_exit, self.response, "submission stderr")
        if command[:3] == ["xcrun", "notarytool", "log"]:
            if not self.log_exit:
                Path(command[-1]).write_text('{"issues": []}')
            return subprocess.CompletedProcess(command, self.log_exit, "", "log diagnostics")
        return subprocess.CompletedProcess(command, 0)

    def notarize(self):
        notarize_macos.notarize(
            self.root, "test-profile", self.root / "temporary.keychain-db", self.diagnostics, "60m")

    def assert_not_stapled(self):
        self.assertFalse(any(command[:2] == ["xcrun", "stapler"] for command in self.commands))
        self.assertFalse(any(command[0] == "spctl" for command in self.commands))

    def test_accepted_package_is_stapled_validated_and_assessed(self):
        self.notarize()
        self.assertEqual([command[:3] for command in self.commands[1:]], [
            ["xcrun", "notarytool", "submit"], ["xcrun", "notarytool", "log"],
            ["xcrun", "stapler", "staple"], ["xcrun", "stapler", "validate"],
            ["spctl", "--assess", "--type"],
        ])
        self.assertIn("--wait", self.commands[1])
        self.assertIn("60m", self.commands[1])
        self.assertIn(str(self.package), self.commands[1])
        self.assertEqual((self.diagnostics / "submission.json").read_text(), self.response)
        self.assertTrue((self.diagnostics / "notary-log.json").exists())

    def test_rejected_and_timed_out_submissions_never_reach_stapling(self):
        for status, code in (("Invalid", 0), ("Rejected", 1), ("In Progress", 124), ("Accepted", 1)):
            with self.subTest(status=status, code=code):
                self.commands.clear()
                self.response = json.dumps({"id": "test-submission", "status": status})
                self.submit_exit = code
                with self.assertRaisesRegex(RuntimeError, "did not succeed"):
                    self.notarize()
                self.assert_not_stapled()
                self.assertTrue((self.diagnostics / "submission.stderr.log").exists())

    def test_malformed_responses_are_preserved_and_fail(self):
        for response in ("", "not JSON", "[]", "{}"):
            with self.subTest(response=response):
                self.commands.clear()
                self.response = response
                with self.assertRaises(RuntimeError):
                    self.notarize()
                self.assert_not_stapled()
                self.assertEqual((self.diagnostics / "submission.json").read_text(), response)

    def test_log_download_failure_does_not_hide_rejection(self):
        self.response = json.dumps({"id": "test-submission", "status": "Invalid"})
        self.log_exit = 1
        with self.assertRaisesRegex(RuntimeError, "status=Invalid"):
            self.notarize()
        self.assert_not_stapled()
        self.assertEqual((self.diagnostics / "notary-log-command.log").read_text(), "log diagnostics")

    def test_signature_stapling_and_gatekeeper_failures_propagate(self):
        for prefix in (["pkgutil"], ["xcrun", "stapler", "staple"],
                       ["xcrun", "stapler", "validate"], ["spctl"]):
            with self.subTest(command=prefix):
                self.commands.clear()
                self.fail_command = prefix
                with self.assertRaises(subprocess.CalledProcessError):
                    self.notarize()
                self.assertEqual(self.commands[-1][:len(prefix)], prefix)

    def test_ambiguous_or_missing_package_fails_before_submission(self):
        self.package.unlink()
        with self.assertRaises(ValueError):
            self.notarize()
        self.package.touch()
        (self.root / "extra.pkg").touch()
        with self.assertRaises(ValueError):
            self.notarize()
        self.assertEqual(self.commands, [])
