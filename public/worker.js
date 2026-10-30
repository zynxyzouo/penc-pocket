// SPDX-License-Identifier: GPL-3.0-or-later
// Public hosting adaptation, 2026-10-28. See MODIFICATIONS.md.
let py, dispatch, projectWide, projectHud, projectClock, config;
let serial = Promise.resolve();
let executionCore='python';
async function boot() {
  postMessage({kind:'progress', text:'正在下載瀏覽器執行核心，首次約需十多 MB…'});
  const {loadPyodide} = await import('https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.mjs');
  py = await loadPyodide({indexURL:'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/'});
  config = await (await fetch('./core-config.json',{cache:'no-cache'})).json();
  py.FS.mkdirTree('/penc/core');
  py.FS.mkdirTree('/penc/session');
  await Promise.all([...config.files,...(config.presentation_files||[]),...(config.runtime_files||[]),...(config.family_files||[])].map(async name => {
    const r = await fetch('./core/' + name);
    if (!r.ok) throw new Error('無法下載核心 ' + name);
    const bytes=new Uint8Array(await r.arrayBuffer());
    const expected=config.file_sha256[name]||config.presentation_sha256?.[name]||config.runtime_sha256?.[name]||config.family_sha256?.[name];
    const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    if(actual!==expected)throw new Error('核心版本不一致，請重新整理：'+name);
    py.FS.writeFile('/penc/core/' + name, bytes);
  }));
  py.runPython("import sys; sys.path.insert(0, '/penc/core'); from family_router import dispatch; from view_projection import project_wide, project_hud, project_clock");
  dispatch = py.globals.get('dispatch');
  projectWide = py.globals.get('project_wide');
  projectHud = py.globals.get('project_hud');
  projectClock = py.globals.get('project_clock');
  if(config.compiled_core && new URL(self.location.href).searchParams.get('core')!=='reference') {
    const response=await fetch('./core/'+config.compiled_core.file,{cache:'no-cache'});
    if(!response.ok)throw Error('無法下載加速核心，請重新整理。');
    const bytes=Uint8Array.from(atob((await response.text()).trim()),c=>c.charCodeAt(0));
    const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    if(actual!==config.compiled_core.sha256)throw Error('加速核心版本不一致，請重新整理。');
    const {CompiledEngine}=await import('./compiled-engine.js');
    globalThis.pocketEngine=await CompiledEngine.create(bytes);
    py.runPython('from js import pocketEngine; import compiled_cpu; compiled_cpu.install(pocketEngine)');
    executionCore='pocket-wasm-hybrid';
  }
  return {version:py.version,execution_core:executionCore};
}
self.onmessage = ({data}) => {
  serial = serial.then(async () => {
    try {
      const started=performance.now();
      let result;
      if (data.op === 'boot') result = await boot();
      else {
        if (!py) throw new Error('瀏覽器核心尚未就緒。');
        if (data.op === 'load') {
          py.FS.writeFile('/penc/session/firmware.bin', new Uint8Array(data.bin));
          py.FS.writeFile('/penc/session/profile.json', data.profile);
          result = JSON.parse(dispatch(JSON.stringify({op:'load', bin_path:'/penc/session/firmware.bin',
            profile_path:'/penc/session/profile.json', core_sha256:config.core_sha256,dmc_core_sha256:config.dmc_core_sha256,stock_core_sha256:config.stock_core_sha256})));
        } else result = JSON.parse(dispatch(JSON.stringify(data)));
      }
      if(result.rgba&&result.family==='penc'){result.wide_rgba=projectWide(result.rgba);result.hud_rgba=projectHud(result.rgba);}
      if(result.clock&&result.family==='penc')result.clock_rgba=projectClock(result.clock);
      if(result.clock)result.worker_ms=performance.now()-started;
      if(result.family)result.execution_core=result.family==='penc'?executionCore:'python';
      postMessage({id:data.id, ok:true, result});
    } catch (e) {
      postMessage({id:data.id, ok:false, error:String(e.message || e)});
    }
  });
};
