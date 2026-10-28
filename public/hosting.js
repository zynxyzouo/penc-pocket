// SPDX-License-Identifier: GPL-3.0-or-later
// Static hosting adaptation, 2026-10-28. See LICENSE and MODIFICATIONS.md.
// Operator configuration: full endpoint of this project's Cloudflare Free native packet Worker.
// GitHub Pages itself cannot provide this API. Never put a secret here.
const configuredRelay = "https://penc-pocket-pairing.penc-pocket-deploy-tools.workers.dev/api/link"; // Live verified 2026-10-28; Workers Free only.
export const relayUnavailable = '此版本尚未設定配對服務；單機養成可以正常使用。';
export function resolveRelayEndpoint(value,base=import.meta.url){
  if(value===null||value===undefined||value==='')return null;
  const u=new URL(value,base);
  const local=['localhost','127.0.0.1','[::1]'].includes(u.hostname);
  if(!(u.protocol==='https:'||u.protocol==='http:'&&local)||u.username||u.password||u.search||u.hash)throw Error('配對服務網址必須使用 HTTPS，且不能包含密碼、查詢參數或片段。');
  return u.href;
}
export const relayEndpoint=resolveRelayEndpoint(configuredRelay);
export const relayAvailable=relayEndpoint!==null;
