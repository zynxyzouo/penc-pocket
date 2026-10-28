import test from 'node:test';
import assert from 'node:assert/strict';
import {pairUrl,parsePairCode,qrMatrix} from '../public/link-qr.js';
import decode from '../public/vendor/jsqr-1.4.0.mjs';

test('QR remains inside the project and round-trips through the decoder',()=>{
  const base='https://example.github.io/penc-pocket/',code='AB23CD45';
  const url=pairUrl(code,base);
  assert.equal(url,base+'#link='+code);
  assert.equal(parsePairCode(url,base),code);
  assert.equal(pairUrl(code,base+'index.html'),url);
  for(const bad of ['https://example.github.io/#link='+code,'https://example.github.io/other/#link='+code,'https://evil.example/penc-pocket/#link='+code,base+'?key=x#link='+code,base+'#link='+code+'&token=x'])assert.throws(()=>parsePairCode(bad,base));
  const matrix=qrMatrix(url),scale=5,quiet=4,n=matrix.length,size=(n+quiet*2)*scale;
  const pixels=new Uint8ClampedArray(size*size*4).fill(255);
  for(let y=0;y<n;y++)for(let x=0;x<n;x++)if(matrix[y][x])for(let dy=0;dy<scale;dy++)for(let dx=0;dx<scale;dx++){const p=(((y+quiet)*scale+dy)*size+(x+quiet)*scale+dx)*4;pixels[p]=pixels[p+1]=pixels[p+2]=0;}
  assert.equal(decode(pixels,size,size).data,url);
});

test('relay endpoint rejects unsafe URLs and stays disabled by default',async()=>{
  const {resolveRelayEndpoint,relayEndpoint}=await import('../public/hosting.js');
  assert.equal(relayEndpoint,null);
  assert.equal(resolveRelayEndpoint(null,'https://example.org/repo/'),null);
  assert.equal(resolveRelayEndpoint('./api/native-link','https://example.org/repo/'),'https://example.org/repo/api/native-link');
  for(const bad of ['http://relay.example/api','https://user:pass@relay.example/api','javascript:alert(1)','https://relay.example/api?token=x','https://relay.example/api#x'])assert.throws(()=>resolveRelayEndpoint(bad,'https://example.org/'));
});

test('missing relay does not pause, create a session, access camera or call network',async()=>{
  const {LinkRoom}=await import('../public/native-link.js');
  let calls=0;const nodes=new Map();
  globalThis.document={addEventListener(){},getElementById(id){if(!nodes.has(id))nodes.set(id,{textContent:'',setAttribute(){},addEventListener(){}});return nodes.get(id);}};
  globalThis.location={href:'https://example.org/repo/#link=AB23CD45',hash:'#link=AB23CD45',origin:'https://example.org'};
  const originalFetch=globalThis.fetch;globalThis.fetch=async()=>{calls++;throw Error('unexpected network');};
  try{
    const room=new LinkRoom({endpoint:null,rpc:async()=>{calls++;},prepare:async()=>{calls++;},resume(){calls++;},display(){},scanner:{stop(){calls++;}}});
    await room.open();await room.followInvite();await room.enter();await room.pair('AB23CD45');
    await assert.rejects(room.request('create'),/配對服務/);
    assert.equal(calls,0);assert.equal(room.session,null);
    assert.match(nodes.get('link-status').textContent,/配對服務/);
  }finally{globalThis.fetch=originalFetch;}
});
