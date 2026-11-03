const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const directory = process.env.STATE_signing_directory;
if (directory && fs.existsSync(directory)) {
  try {
    const keychains = JSON.parse(fs.readFileSync(path.join(directory, 'keychains.json'), 'utf8'));
    const result = spawnSync('security', ['list-keychains', '-d', 'user', '-s', ...keychains], { stdio: 'inherit' });
    if (result.error || result.status !== 0) throw new Error('Could not restore keychain search list');
  } catch (error) {
    console.error(`::error::${error.message}`);
    process.exitCode = 1;
  } finally {
    const keychain = path.join(directory, 'signing.keychain-db');
    if (fs.existsSync(keychain)) {
      const result = spawnSync('security', ['delete-keychain', keychain], { stdio: 'inherit' });
      if (result.error || result.status !== 0) {
        console.error('::error::Could not delete signing keychain through security');
        process.exitCode = 1;
      }
    }
    fs.rmSync(directory, { recursive: true, force: true });
  }
}
