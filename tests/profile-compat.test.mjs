import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const hash=s=>createHash('sha256').update(s).digest('hex');
test('only the audited metadata-only profile transition is eligible',async()=>{
  const {upgradeSnapshotProfile}=await import('../public/profile-compat.js');
  const text='{"sha256":"'+'a'.repeat(64)+'"}',firmware='a'.repeat(64),legacy='b'.repeat(64),current=hash(text);
  const records=[{firmware_sha256:firmware,from:legacy,to:current}];
  const snapshot={firmware_sha256:firmware,profile_sha256:legacy,core_sha256:'c'.repeat(64),ram:{'0000':1}};
  const result=await upgradeSnapshotProfile(snapshot,text,records);
  assert.equal(result.profile_sha256,current);assert.equal(snapshot.profile_sha256,legacy);
  assert.deepEqual(result.ram,snapshot.ram);assert.equal(result.core_sha256,snapshot.core_sha256);
  assert.equal(await upgradeSnapshotProfile(snapshot,text+' ',records),snapshot);
  const wrongFirmware={...snapshot,firmware_sha256:'d'.repeat(64)};
  assert.equal(await upgradeSnapshotProfile(wrongFirmware,text,records),wrongFirmware);
  const unknown={...snapshot,profile_sha256:'e'.repeat(64)};
  assert.equal(await upgradeSnapshotProfile(unknown,text,records),unknown);
});
