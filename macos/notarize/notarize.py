"""Notarize and staple a signed CI installer, failing before publication on errors."""

import argparse
import json
from pathlib import Path
import subprocess


def notarize(directory, profile, keychain, diagnostics, timeout):
    packages = sorted(directory.glob("*.pkg"))
    if len(packages) != 1 or not packages[0].is_file():
        raise ValueError("Expected exactly one macOS installer package")
    package = packages[0]
    diagnostics.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pkgutil", "--check-signature", str(package)], check=True)
    credentials = ["--keychain-profile", profile, "--keychain", str(keychain)]
    print(f"Submitting {package} for notarization (timeout: {timeout})", flush=True)
    result = subprocess.run([
        "xcrun", "notarytool", "submit", str(package), *credentials,
        "--wait", "--timeout", timeout, "--output-format", "json",
    ], capture_output=True, text=True)
    (diagnostics / "submission.json").write_text(result.stdout)
    (diagnostics / "submission.stderr.log").write_text(result.stderr)
    try:
        submission = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Notarization returned no valid JSON response; see submission diagnostics") from error
    if not isinstance(submission, dict):
        raise RuntimeError("Unexpected notarization response; see submission diagnostics")
    submission_id = submission.get("id")
    status = submission.get("status")
    print(f"Notarization submission {submission_id}: {status}", flush=True)
    if submission_id:
        # Fetch Apple's report for accepted and rejected submissions. A report
        # may be unavailable on timeout; preserve that error without hiding the
        # original submission result.
        log = subprocess.run([
            "xcrun", "notarytool", "log", submission_id, *credentials,
            str(diagnostics / "notary-log.json"),
        ], capture_output=True, text=True)
        (diagnostics / "notary-log-command.log").write_text(log.stdout + log.stderr)
        if log.returncode:
            print("Apple's notarization log could not be retrieved; see diagnostics", flush=True)
    if result.returncode or status != "Accepted":
        raise RuntimeError(
            f"Notarization did not succeed (status={status}, exit={result.returncode}); "
            "see submission diagnostics")
    subprocess.run(["xcrun", "stapler", "staple", str(package)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(package)], check=True)
    subprocess.run(["spctl", "--assess", "--type", "install", "--verbose", str(package)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing exactly one signed .pkg")
    parser.add_argument("--keychain-profile", required=True)
    parser.add_argument("--keychain", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--timeout", default="60m")
    args = parser.parse_args()
    notarize(args.directory, args.keychain_profile, args.keychain, args.diagnostics, args.timeout)


if __name__ == "__main__":
    main()
