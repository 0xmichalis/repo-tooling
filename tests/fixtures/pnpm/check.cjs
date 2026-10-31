const assert = require('node:assert/strict');
const fs = require('node:fs');

const step = process.argv[2];
const completed = fs.existsSync('checks.json') ? JSON.parse(fs.readFileSync('checks.json')) : [];
assert.deepEqual(completed, {
  lint: [],
  'type-check': ['lint'],
  build: ['lint', 'type-check'],
}[step]);
fs.writeFileSync('checks.json', JSON.stringify([...completed, step]));
