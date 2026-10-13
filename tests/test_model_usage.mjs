import assert from 'node:assert/strict';
import {usageText} from '../frontend/web_app/model-usage.js';

assert.equal(usageText({calls:0}), '');
assert.match(usageText({calls:2,input_tokens:0,output_tokens:0,unknown_usage_calls:2}), /Token counts unavailable/);
assert.doesNotMatch(usageText({calls:2,input_tokens:0,output_tokens:0,unknown_usage_calls:2}), /0 input/);
assert.match(usageText({calls:2,input_tokens:1000,output_tokens:50,unknown_usage_calls:1,discarded:1}), /1,000 input.*1 call without complete usage.*1 discarded/);
console.log('Model usage presentation checks passed.');
