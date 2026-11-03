# macOS signing and notarization

These actions share the Apple credential and notarization workflow across macOS
applications. Each repository keeps its application-specific build and packaging
commands and decides when to publish the verified artifacts. Both actions require
a macOS runner with Xcode command-line tools. `macos/notarize` also requires Python
3.10 or newer. Use GitHub-hosted runners, or an isolated runner per job: signing
temporarily changes the user's keychain search list.

## Organization configuration

Create these Actions values under **featuremine > Settings > Secrets and variables
> Actions** and grant access to selected application repositories:

| Type | Name | Contents |
| --- | --- | --- |
| Secret | `MACOS_SIGNING_CERTIFICATES_P12_BASE64` | Base64-encoded password-protected P12 containing both Developer ID certificates and private keys |
| Secret | `MACOS_SIGNING_CERTIFICATES_PASSWORD` | P12 export password |
| Secret | `MACOS_NOTARY_APPLE_ID` | Apple developer account email |
| Secret | `MACOS_NOTARY_APP_PASSWORD` | App-specific password for that Apple account |
| Variable | `MACOS_APPLICATION_IDENTITY` | Exact Developer ID Application certificate name |
| Variable | `MACOS_INSTALLER_IDENTITY` | Exact Developer ID Installer certificate name |
| Variable | `MACOS_NOTARY_TEAM_ID` | Apple developer team ID matching both certificates |

For Featuremine, the identity names are
`Developer ID Application: Featuremine Corporation (2Z64TAC23N)` and
`Developer ID Installer: Featuremine Corporation (2Z64TAC23N)`; the team ID is
`2Z64TAC23N`. The identity names and team ID are public selectors, not passwords.

Export both Developer ID identities together from **Keychain Access > My
Certificates**, including their private keys. Use certificates issued by Apple's
Developer ID G2 intermediate. Keep the P12 outside the repository. Its base64
encoding is still secret. Generate the notarization password at
[account.apple.com](https://account.apple.com/) under **Sign-In and Security >
App-Specific Passwords**; do not use the normal account password.

When migrating `carnitas-ui`, rename the two `CARNITAS_MACOS_*_IDENTITY` GitHub
variables to the generic names above. Once all organization values are ready,
remove their old environment/repository copies so they cannot override organization
values. Keep each repository's `macos-signing` environment and configure its
reviewers/protection rules as appropriate. Organization secrets are accessible to
other workflows in each authorized repository; an environment on this example job
does not restrict access elsewhere. Only authorize repositories whose workflow
authors are trusted with the signing keys.

## Usage

Publish these action directories to the `v7` ref before merging consumers that
reference them. The following steps assume the repository has already checked out
its code, configured its build, and installed its dependencies. The build must
sign its app with hardened runtime and a secure timestamp, sign the installer,
and produce exactly one `.pkg` in `build/output/`. Other files in that directory
are ignored by the notarization action.

```yaml
- name: Import Developer ID signing identities
  uses: featuremine/actions/macos/setup-signing@v7
  with:
    certificates-p12-base64: ${{ secrets.MACOS_SIGNING_CERTIFICATES_P12_BASE64 }}
    certificates-password: ${{ secrets.MACOS_SIGNING_CERTIFICATES_PASSWORD }}
    application-identity: ${{ vars.MACOS_APPLICATION_IDENTITY }}
    installer-identity: ${{ vars.MACOS_INSTALLER_IDENTITY }}

# Adapt this step to the application's packaging system. Pass the identities
# above to its codesign/productbuild configuration before building.
- name: Build signed installer
  run: cmake --build build --config Release

- name: Notarize, staple, and assess installer
  uses: featuremine/actions/macos/notarize@v7
  with:
    directory: build/output
    apple-id: ${{ secrets.MACOS_NOTARY_APPLE_ID }}
    app-password: ${{ secrets.MACOS_NOTARY_APP_PASSWORD }}
    team-id: ${{ vars.MACOS_NOTARY_TEAM_ID }}

# Publish build/output only after notarization and other required tests succeed.
```

Signing and notarization can also be separate jobs, as in `carnitas-ui`. Transfer
the signed installer using workflow artifacts from the same run, and make the
notarization job depend on all required build/test jobs. Only the signing job
needs the P12; only the notarization job needs the Apple account credentials.
For a `60m` notarization wait, allow additional job time for credential validation,
submission upload, stapling, diagnostics, and cleanup (Carnitas uses 90 minutes).

Keep release-only conditions, fork/Dependabot exclusions, environment approval,
and release-upload permissions in the calling workflow. Neither action checks
out code or publishes a GitHub release. App packaging, entitlements, and nested
code signing remain the caller's responsibility.

## `macos/setup-signing`

All four inputs in the example are required. The action imports the P12 and
Apple's Developer ID G2 intermediate without changing certificate trust, enables
noninteractive signing, and verifies both configured identities and private keys.
It adds a unique temporary keychain to the existing user search list and exposes
its path as the `keychain` output. The decoded P12 is removed immediately after
setup. A Node action post step restores the original search list and deletes the
keychain at job end, including after setup or build failures. No separate cleanup
step is needed in consumers.

## `macos/notarize`

| Input | Required/default | Meaning |
| --- | --- | --- |
| `directory` | Required | Directory with exactly one signed `.pkg`; stapled in place |
| `apple-id` | Required | Apple account email |
| `app-password` | Required | Apple app-specific password |
| `team-id` | Required | Apple developer team ID |
| `timeout` | `60m` | `notarytool` wait timeout |
| `diagnostics` | `notarization-diagnostics` | Local directory for submission response and logs |
| `diagnostics-artifact` | `macos-notarization-diagnostics-<job>-<attempt>` | Uploaded diagnostic artifact name |

The action creates a temporary credential keychain, checks the installer signature,
submits to Apple, and requires both a successful command exit and `Accepted` status.
It then staples and validates the ticket and assesses the package with Gatekeeper.
Every verification failure fails the action. Credential setup failures also clean
up the keychain. Submission responses and Apple logs, when available, are uploaded
even after failure and retained for 14 days. For multiple invocations in one job,
provide distinct `diagnostics` directories and `diagnostics-artifact` names.

A timeout does not cancel Apple's processing. Inspect the saved submission ID
with `notarytool info`; rerunning the action submits again. Cancellation or runner
loss can prevent diagnostics upload or cleanup; hosted runners are discarded
after each job.

## Tests

Run from the actions repository with Python 3.10+ and Node 24:

```sh
python3 -B -m unittest discover -s tests -p 'test_macos_*.py' -v
```

The tests stub Apple commands and do not use real credentials, access the host
keychain, or submit to Apple. They cover signing setup/cleanup and notarization
acceptance, rejection, timeouts, malformed responses, and verification failures.
