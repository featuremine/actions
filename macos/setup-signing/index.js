// Only Node built-ins are used; no bundled dependencies are needed.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

try {
  if (process.platform !== 'darwin') throw new Error('macOS runner required');
  const env = { ...process.env };
  for (const [input, variable] of Object.entries({
    'certificates-p12-base64': 'MACOS_SIGNING_CERTIFICATES_P12_BASE64',
    'certificates-password': 'MACOS_SIGNING_CERTIFICATES_PASSWORD',
    'application-identity': 'MACOS_APPLICATION_IDENTITY',
    'installer-identity': 'MACOS_INSTALLER_IDENTITY',
  })) {
    const value = process.env[`INPUT_${input.toUpperCase()}`];
    if (!value) throw new Error(`Missing required input: ${input}`);
    env[variable] = value;
  }
  const listing = execFileSync('security', ['list-keychains', '-d', 'user'], { encoding: 'utf8' });
  const keychains = [...listing.matchAll(/"([^"]+)"/g)].map(match => match[1]);
  const directory = fs.mkdtempSync(path.join(process.env.RUNNER_TEMP, 'macos-signing-'));
  fs.chmodSync(directory, 0o700);
  // Save cleanup state before any key material is imported, including on failure.
  fs.appendFileSync(process.env.GITHUB_STATE, `signing_directory=${directory}\n`);
  fs.writeFileSync(path.join(directory, 'keychains.json'), JSON.stringify(keychains), { mode: 0o600 });
  execFileSync('/bin/bash', [path.join(__dirname, 'setup.sh')], {
    env: { ...env, SIGNING_DIR: directory }, stdio: 'inherit',
  });
  const keychain = path.join(directory, 'signing.keychain-db');
  execFileSync('security', ['list-keychains', '-d', 'user', '-s', keychain, ...keychains], { stdio: 'inherit' });
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `keychain=${keychain}\n`);
} catch (error) {
  // Do not print child-process error objects: they may contain secret arguments.
  console.error(`::error::Signing setup failed: ${error.message.split('\n')[0]}`);
  process.exitCode = 1;
}
