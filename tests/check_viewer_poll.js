// No browser, VM, npm modules or private firmware required.
// Validate the viewer's actual adaptive scheduling function against a
// controlled clock, and guard the hidden-tab no-polling contract.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const code = fs.readFileSync(path.join(__dirname, '..', 'tools', 'qemu-viewer.html'), 'utf8');
const match = code.match(/function nextPollInterval\(\)\{[\s\S]*?\n\}/);
assert.ok(match, 'Adaptive policy function must exist in the real browser source');
const sample = (now, lastInteraction, lastChange) => vm.runInNewContext(
  match[0] + '\nnextPollInterval();',
  {lastInteraction, lastChange, Date: {now: () => now}});

assert.equal(sample(10000, 9900, 1000), 350, 'Recent input should get quick refresh');
assert.equal(sample(10000, 0, 9500), 350, 'Changed pixels should get quick refresh');
assert.equal(sample(10000, 3000, 1000), 1000, 'Seven idle seconds');
assert.equal(sample(40000, 9000, 10000), 2500, 'Thirty idle seconds');
assert.equal(sample(120000, 10000, 20000), 6000, 'Long unchanged session');
assert.match(code, /if\(document\.hidden\|\|polling\)return;/,
  'Never sample a hidden tab');
assert.match(code, /if\(document\.hidden\)\{if\(pollTimer!==null\)clearTimeout\(pollTimer\);pollTimer=null;/,
  'Cancel pending timer as soon as tab becomes hidden');
assert.match(code, /window\.addEventListener\("focus".*wakeViewer/,
  'Focus must trigger a prompt refresh');
assert.match(code, /if\(!polling && \(!down \|\| pollTimer===null\)\)schedulePoll\(100\)/,
  'Pointer moves must not continually postpone screen refreshes');

console.log('PASS adaptive viewer: active=350ms, idle=1/2.5/6s, hidden=0, focus wake');
