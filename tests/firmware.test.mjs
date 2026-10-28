import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {builtinProfile} from '../public/firmware.js';

test('R23 BIN resolves its exact bundled profile; stock and DMC remain available', async t => {
  t.mock.method(globalThis, 'fetch', async path => new Response(
    await readFile(new URL('../public/'+path.replace(/^\.\//,''), import.meta.url))));
  const hash='0c7953432d89c924221ee8b30054a25fd7c954ec35565b32bd499a5ac2daf882';
  const result=await builtinProfile(hash);
  assert.ok(result, 'R23 must work without selecting a separate JSON');
  assert.equal(JSON.parse(result.text).sha256,hash);
  for(const other of ['a21e573ba40741603b8b4068817c789c625196ab5e53ddb188b1f57c63c612a1',
    '3457140c5f07211abdd756462693c67c824c4c45c26a7ca91e4323df476701dc'])
    assert.ok(await builtinProfile(other));
  assert.equal(await builtinProfile('78a066bf272712aee1bf1868522dbcccbca0ee6586963940bdc61ca111c4809d'),null);
});
