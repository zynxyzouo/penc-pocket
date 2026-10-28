// SPDX-License-Identifier: GPL-3.0-or-later
// Metadata-only public profile migration, 2026-10-28. See MODIFICATIONS.md.
import {profileMigrations} from './profile-migrations.js';
export async function upgradeSnapshotProfile(snapshot,text,records=profileMigrations){
  if(!snapshot||typeof snapshot!=='object'||typeof text!=='string')return snapshot;
  const record=records.find(r=>r.firmware_sha256===snapshot.firmware_sha256&&r.from===snapshot.profile_sha256);
  if(!record)return snapshot;
  const bytes=new TextEncoder().encode(text);
  const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(actual!==record.to)return snapshot;
  let profile;try{profile=JSON.parse(text);}catch{return snapshot;}
  if(profile.sha256!==record.firmware_sha256)return snapshot;
  // All core, BIN, format, RAM and adapter validation still occurs in restore().
  return {...snapshot,profile_sha256:record.to};
}
