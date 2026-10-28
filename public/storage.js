// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
const NAME = 'penc-pocket-local-v1';
let opening;
function db() {
  return opening ||= new Promise((resolve, reject) => {
    const r = indexedDB.open(NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore('records');
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.onblocked = () => reject(new Error('請關閉其他舊版網頁後再試。'));
  });
}
export async function read(key) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const r = d.transaction('records').objectStore('records').get(key);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function writeMany(entries) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction('records', 'readwrite');
    for (const [key, value] of entries) tx.objectStore('records').put(value, key);
    tx.oncomplete = () => resolve();
    tx.onabort = tx.onerror = () => reject(tx.error || new Error('無法寫入瀏覽器儲存區。'));
  });
}
export async function erase(keys) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction('records', 'readwrite');
    keys.forEach(k => tx.objectStore('records').delete(k));
    tx.oncomplete = resolve;
    tx.onabort = tx.onerror = () => reject(tx.error);
  });
}
