import test from 'node:test';
import assert from 'node:assert/strict';
import {health, saveWorkspace, analyzeApplication, ApiError} from '../frontend/chrome_extension/api-client.js';

test('Lens saves the selected job and analyzes the returned application version', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({url, body: options.body ? JSON.parse(options.body) : null});
    return {ok: true, json: async () => url.endsWith('/api/workspaces')
      ? {application: {application_id: 'job/a', version: 7}} : {status: 'ok'}};
  });
  await health();
  const job = {source_url: 'https://example.org/job', cleaned_job_description: 'Requires Python'};
  const saved = await saveWorkspace(job);
  await analyzeApplication(saved.application.application_id, saved.application.version);
  assert.deepEqual(requests, [
    {url: 'http://localhost:8000/health', body: null},
    {url: 'http://localhost:8000/api/workspaces', body: {...job, reopen_existing: true}},
    {url: 'http://localhost:8000/api/applications/job%2Fa/analyze-with-resume', body: {expected_version: 7, resume_id: null}},
  ]);
});

test('Lens preserves actionable server errors and handles missing resumes', async t => {
  t.mock.method(globalThis, 'fetch', async () => ({ok: false, status: 409, json: async () => ({})}));
  await assert.rejects(analyzeApplication('job', 1), e => e instanceof ApiError && e.status === 409 && /Upload a PDF/.test(e.message));
  t.mock.method(globalThis, 'fetch', async () => ({ok: false, status: 422, json: async () => ({detail: {message: 'Job description is empty'}})}));
  await assert.rejects(saveWorkspace({}), /Job description is empty/);
});

test('Lens reports transport failure without exposing the underlying error', async t => {
  t.mock.method(globalThis, 'fetch', async () => {throw new Error('private transport details');});
  await assert.rejects(health(), e => e instanceof ApiError && /Cannot reach/.test(e.message) && !e.message.includes('private'));
});
