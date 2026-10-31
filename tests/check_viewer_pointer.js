// Offline browser event simulation. No firmware, browser, external services or
// running QEMU needed. Confirm that cancelled/abandoned touch gestures always
// send one release and cannot leave the iOS tablet indefinitely pressed.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'tools', 'qemu-viewer.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0]
  .replace('inputEnabled=INPUT_ENABLED', 'inputEnabled=true')
  .replace(/^poll\(\);$/m, '/* no continuous screenshot polling during event tests */');

async function test(name, action) {
  const listeners = {img: {}, window: {}, document: {}};
  const sends = [], gestures = [];
  const img = {
    src: '', disabled: false,
    addEventListener: (event, fn) => {listeners.img[event] = fn;},
    setPointerCapture: () => {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 200, height: 400}),
  };
  const home = {disabled: false, addEventListener: () => {}};
  const swipeButtons = ['up', 'down', 'left', 'right'].map(swipe => ({
    dataset: {swipe}, disabled: false,
    addEventListener(event, handler) {if(event === 'click')this.click = handler;},
  }));
  const elements = {frame: img, state: {textContent: ''}, runtime: {textContent: ''},
    swipehome: home, perfDetails: {addEventListener: () => {}},
    perfRefresh: {addEventListener: () => {}}, perfStats: {textContent: ''}};
  const document = {hidden: false, getElementById: id => elements[id],
    querySelectorAll: selector => selector === '[data-swipe]' ? swipeButtons : [],
    addEventListener: (event, fn) => {listeners.document[event] = fn;}};
  const window = {addEventListener: (event, fn) => {listeners.window[event] = fn;}};
  const fetch = async (url, options) => {
    if(url === '/status.json')return {json: async () => ({mode: 'QEMU', cores: 2})};
    if(url === '/touch'){
      sends.push({event: JSON.parse(options.body), keepalive: options.keepalive});
      return {ok: true};
    }
    if(url === '/gesture'){
      gestures.push(JSON.parse(options.body));
      return {ok: true};
    }
    throw new Error('Unexpected network request: ' + url);
  };
  // Simulate scheduling without running the image refresh loop. This test
  // exercises touch behavior only; the polling policy has its own test.
  const context = vm.createContext({document, window, fetch, console,
    setTimeout: () => 1, clearTimeout: () => {}, Date, Promise, URL});
  vm.runInContext(script, context);
  const pointer = (pointerId, x, y) => ({pointerId, clientX: x, clientY: y,
    preventDefault() {}});
  const flush = async () => {await vm.runInContext('touchQueue', context);};
  await action({listeners, pointer, flush, sends, document, swipeButtons, gestures});
  console.log('PASS pointer release:', name);
}

(async () => {
  await test('cancelled outside view', async ({listeners, pointer, flush, sends}) => {
    listeners.img.pointerdown(pointer(9, 100, 300));
    listeners.img.pointermove(pointer(15, 145, 340)); // different pointer, ignore
    listeners.img.pointercancel(pointer(9, 100, 300));
    listeners.img.lostpointercapture(pointer(9, 100, 300)); // no double release
    await flush();
    assert.deepEqual(sends.map(x => x.event.down), [true, false]);
    assert.deepEqual(sends.map(x => x.keepalive), [false, true]);
  });
  await test('window loses focus mid-drag', async ({listeners, pointer, flush, sends}) => {
    listeners.img.pointerdown(pointer(1, 50, 330));
    listeners.img.pointermove(pointer(1, 85, 260));
    listeners.window.blur();
    listeners.img.pointerup(pointer(1, 85, 260));
    await flush();
    assert.deepEqual(sends.map(x => x.event.down), [true, true, false]);
  });
  await test('page closes mid-touch', async ({listeners, pointer, flush, sends}) => {
    listeners.img.pointerdown(pointer(1, 50, 330));
    listeners.window.pagehide();
    await flush();
    assert.deepEqual(sends.map(x => x.event.down), [true, false]);
  });
  await test('hidden tab releases pointer', async ({listeners, pointer, flush, sends, document}) => {
    listeners.img.pointerdown(pointer(1, 50, 330));
    document.hidden = true;
    listeners.document.visibilitychange();
    await flush();
    assert.deepEqual(sends.map(x => x.event.down), [true, false]);
  });
  await test('navigation buttons use one gesture each', async ({swipeButtons, gestures, sends}) => {
    for(const button of swipeButtons){
      assert.equal(button.disabled, false);
      await button.click();
      assert.equal(button.disabled, false);
    }
    assert.deepEqual(gestures, [
      {action:'swipe-up'}, {action:'swipe-down'},
      {action:'swipe-left'}, {action:'swipe-right'},
    ]);
    assert.equal(sends.length, 0, 'Do not use separate HTTP touch requests for a swipe');
  });
})().catch(error => {console.error(error);process.exitCode = 1;});
