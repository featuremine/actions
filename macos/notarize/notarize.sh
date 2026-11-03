#!/bin/bash
set -euo pipefail
[[ "$RUNNER_OS" == macOS ]] || { echo '::error::macOS runner required'; exit 1; }
: "${MACOS_NOTARY_APPLE_ID:?Missing apple-id input}"
: "${MACOS_NOTARY_APP_PASSWORD:?Missing app-password input}"
: "${MACOS_NOTARY_TEAM_ID:?Missing team-id input}"
: "${PACKAGE_DIRECTORY:?Missing directory input}"
umask 077
notary_dir=$(mktemp -d "$RUNNER_TEMP/macos-notary.XXXXXX")
keychain_path="$notary_dir/notary.keychain-db"
cleanup() {
  result=$?
  trap - EXIT
  if [[ -f "$keychain_path" ]]; then
    security delete-keychain "$keychain_path" || result=1
  fi
  rm -rf "$notary_dir" || result=1
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
keychain_password=$(openssl rand -hex 32)
echo "::add-mask::$keychain_password"
security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 7200 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
xcrun notarytool store-credentials macos-notary \
  --keychain "$keychain_path" \
  --apple-id "$MACOS_NOTARY_APPLE_ID" \
  --team-id "$MACOS_NOTARY_TEAM_ID" \
  --password "$MACOS_NOTARY_APP_PASSWORD"
python3 "$ACTION_PATH/notarize.py" "$PACKAGE_DIRECTORY" \
  --keychain-profile macos-notary --keychain "$keychain_path" \
  --diagnostics "$NOTARY_DIAGNOSTICS" --timeout "$NOTARY_TIMEOUT"
