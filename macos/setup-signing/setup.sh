#!/bin/bash
set -euo pipefail
: "${MACOS_SIGNING_CERTIFICATES_P12_BASE64:?Set the certificate secret as an action input}"
: "${MACOS_SIGNING_CERTIFICATES_PASSWORD:?Set the P12 password secret as an action input}"
: "${MACOS_APPLICATION_IDENTITY:?Set the application identity variable as an action input}"
: "${MACOS_INSTALLER_IDENTITY:?Set the installer identity variable as an action input}"

umask 077
: "${SIGNING_DIR:?Missing temporary signing directory}"
signing_dir="$SIGNING_DIR"
keychain_path="$signing_dir/signing.keychain-db"
certificate_path="$signing_dir/identities.p12"
trap 'rm -f "$certificate_path"' EXIT
printf '%s' "$MACOS_SIGNING_CERTIFICATES_P12_BASE64" | base64 --decode > "$certificate_path"

keychain_password=$(openssl rand -hex 32)
echo "::add-mask::$keychain_password"
security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 21600 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
security import "$certificate_path" -k "$keychain_path" \
  -P "$MACOS_SIGNING_CERTIFICATES_PASSWORD" -f pkcs12 \
  -T /usr/bin/codesign -T /usr/bin/productbuild -T /usr/bin/productsign

# Install Apple's intermediate without overriding system trust settings.
curl --fail --silent --show-error --location --retry 3 \
  https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer \
  --output "$signing_dir/DeveloperIDG2CA.cer"
security verify-cert -c "$signing_dir/DeveloperIDG2CA.cer"
# A P12 export can already include this intermediate. Compare the exact
# certificate, since Apple's G1 and G2 intermediates share a name.
intermediate_sha256=$(openssl x509 -inform DER -in "$signing_dir/DeveloperIDG2CA.cer" \
  -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')
installed_certificates=$(security find-certificate -a -Z "$keychain_path")
if ! grep -Fxq "SHA-256 hash: $intermediate_sha256" <<< "$installed_certificates"; then
  security import "$signing_dir/DeveloperIDG2CA.cer" -k "$keychain_path"
fi
security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "$keychain_password" "$keychain_path" > /dev/null

# Check certificates AND their private keys before starting the build.
identities=$(security find-identity -v "$keychain_path")
for identity in "$MACOS_APPLICATION_IDENTITY" "$MACOS_INSTALLER_IDENTITY"; do
  if ! printf '%s\n' "$identities" | grep -Fq -- "\"$identity\""; then
    echo "::error::The P12 must contain both configured Developer ID identities and their private keys."
    exit 1
  fi
done
