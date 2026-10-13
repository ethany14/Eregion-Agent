import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the active chat polling function with responses arriving out of order.
const source = fs.readFileSync(new URL('../frontend/web_app/apply.js', import.meta.url), 'utf8');
const start = source.indexOf('async function refresh('), end = source.indexOf('const PAGE_VIEWS=', start);
assert.ok(start >= 0 && end > start);
const refreshSource = source.slice(start, end);

for (const background of [false, true]) for (const failure of [false, true]) {
  test(`${background ? 'background' : 'full'} stale refresh ${failure ? 'failure' : 'response'} cannot replace the selected conversation`, async () => {
    let settleOld, requests = 0, timers = 0;
    const second = {run_id: 'B', version: 22, status: 'completed'};
    const context = vm.createContext({
      selected: 'A', current: null, attempts: [{run_id: 'A'}, second], groups: [],
      serial: 0, poll: null, careerMode: true, historyRefreshedAt: Date.now(),
      busyStatuses: new Set(['running']), clearTimeout() {},
      setTimeout() {timers++; return timers;},
      request: async () => ++requests === 1
        ? new Promise((resolve, reject) => {settleOld = failure ? reject : resolve;})
        : background ? second : {attempts: [second], groups: [{group_id: 'new'}]},
      render() {}, $: () => ({hidden: true}),
      error() {throw new Error('A stale request displayed an error');},
    });
    vm.runInContext(refreshSource, context);
    const old = context.refresh({background});
    context.selected = 'B';
    await context.refresh({background});
    settleOld(failure ? new Error('Old request failed') : background
      ? {run_id: 'A', version: 1} : {attempts: [{run_id: 'A', version: 1}], groups: []});
    await old;
    assert.equal(context.current.run_id, 'B');
    assert.equal(context.current.version, 22);
    assert.equal(timers, 1);
    if (!background) assert.equal(context.groups[0].group_id, 'new');
  });
}
