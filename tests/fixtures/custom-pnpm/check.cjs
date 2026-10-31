const assert = require('node:assert/strict');
const fs = require('node:fs');

const expected = ['format', 'lint', 'typecheck', 'test'];
const completed = fs.existsSync('checks.json') ? JSON.parse(fs.readFileSync('checks.json')) : [];
const step = process.argv[2];
assert.deepEqual(completed, expected.slice(0, expected.indexOf(step)));
assert.equal(step, expected[completed.length]);
completed.push(step);
fs.writeFileSync('checks.json', JSON.stringify(completed));
if (step === 'test') assert.deepEqual(completed, expected);
