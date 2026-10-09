import test from 'node:test';
import assert from 'node:assert/strict';
import {safeMarkdownLink} from '../web_app/chat-markdown.js';

test('Markdown links preserve job query parameters and local document downloads',()=>{
  assert.equal(safeMarkdownLink('https://example.com/jobs?a=1&amp;b=2'),'https://example.com/jobs?a=1&b=2');
  assert.equal(safeMarkdownLink('/api/packs/example/resume.pdf'),'/api/packs/example/resume.pdf');
  assert.equal(safeMarkdownLink('mailto:jobs@example.com'),'mailto:jobs@example.com');
  assert.equal(safeMarkdownLink('https://example.com/?label=&constructor;'),'https://example.com/?label=&constructor;');
});

test('Untrusted Markdown cannot make executable or disguised protocol links',()=>{
  for(const value of ['javascript:alert(1)','&#106;avascript:alert(1)','java&#x0a;script:alert(1)',
    'data:text/html,hello','file:///private.pdf','//example.com','/\\example.com','javascript:\talert(1)'])
    assert.equal(safeMarkdownLink(value),null,value);
});
