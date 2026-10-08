import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../web_app/app.js', import.meta.url), 'utf8');
const select = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));

test('saving a job survives the real event lifetime and refreshes the workspace', async () => {
  const result = {};
  const form = new EventTarget();
  form.reset = () => { result.reset = true; };
  const context = vm.createContext({
    FormData: class { get(name) { return name === 'job_description' ? 'Requires Python' : ''; } },
    api: { saveJob: async () => ({ application: { application_id: 'new-job' } }) },
    $: () => ({ close() { result.closed = true; } }), state: {},
    localStorage: { setItem(key, value) { result.selected = value; } },
    loadApplications: async () => { result.refreshed = true; },
    toast: (message, kind) => { if (kind === 'error') throw new Error(message); }, URL,
  });
  vm.runInContext(select('async function saveJob(', 'async function loadSessionHistory('), context);
  let pending;
  form.addEventListener('submit', event => { pending = context.saveJob(event); });
  form.dispatchEvent(new Event('submit'));
  await pending;
  assert.deepEqual(result, { closed: true, reset: true, selected: 'new-job', refreshed: true });
});

test('manual evidence preserves the source quote and resets after asynchronous submission', async () => {
  const form = new EventTarget(), result = {};
  form.reset = () => { result.reset = true; };
  const context = vm.createContext({
    FormData: class { get(key) { return { category: 'experience', claim_text: ' Built Python APIs. ' }[key]; } },
    $: selector => selector === '#evidence-form' ? form : { close() {} },
    api: { createEvidence: async payload => { result.payload = payload; } },
    loadEvidence: async () => { result.refreshed = true; },
    toast: (message, kind) => { if (kind === 'error') throw new Error(message); },
  });
  // Capture the promise while retaining native EventTarget/currentTarget behavior.
  let pending;
  const original = form.addEventListener.bind(form);
  form.addEventListener = (type, handler) => original(type, event => { pending = handler(event); });
  vm.runInContext(select('$("#evidence-form").addEventListener', '\nshowView(location.hash'), context);
  form.dispatchEvent(new Event('submit'));
  await pending;
  assert.equal(result.payload.exact_quote, 'Built Python APIs.');
  assert.equal(result.payload.claim_text, result.payload.exact_quote);
  assert.equal(result.reset && result.refreshed, true);
});

for (const failure of [false, true]) test(`stale session ${failure ? 'failure' : 'response'} cannot overwrite the selected session`, async () => {
  const nodes = new Map();
  const element = () => ({ children: [], replaceChildren() { this.children = []; }, append(...items) { this.children.push(...items); }, scrollHeight: 0 });
  let settleA;
  const state = { session: 'A', sessionVersion: null };
  const session = (id, version) => ({ session: { title: id, version, status: 'active', total_input_tokens: 0, total_output_tokens: 0, executed_tool_calls: 0 } });
  const context = vm.createContext({ state,
    api: { getSession: id => id === 'A' ? new Promise((resolve, reject) => { settleA = failure ? reject : resolve; }) : Promise.resolve(session('B', 22)),
      messages: async () => ({ messages: [] }) },
    $: selector => { if (!nodes.has(selector)) nodes.set(selector, element()); return nodes.get(selector); },
    clear: value => value.replaceChildren(), label: value => value, node: element,
    localStorage: { removeItem() { throw new Error('stale response removed active session'); } },
    toast() { throw new Error('stale response produced a toast'); },
  });
  vm.runInContext(select('let sessionRenderRequest', 'async function sendMessage('), context);
  const oldRequest = context.renderSession();
  state.session = 'B';
  await context.renderSession();
  settleA(failure ? { status: 404 } : session('A', 11));
  await oldRequest;
  assert.equal(state.session, 'B');
  assert.equal(nodes.get('#conversation-title').textContent, 'B');
  assert.equal(state.sessionVersion, 22);
});
