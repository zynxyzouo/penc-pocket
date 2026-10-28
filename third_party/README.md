# Third-party preferred sources and provenance

This directory contains production sources and notices for the QR components
used by the standalone browser application. Third-party files retain their
upstream licenses. The source manifest records exact download URLs, Git commits,
SHA-256 hashes, npm package integrity values, and byte comparisons.

No firmware, game artwork, audio, save files, test fixtures, test images,
`node_modules`, or Pyodide runtime binaries are included in this directory.

## jsQR 1.4.0

- Upstream: <https://github.com/cozmo/jsQR>
- License: Apache-2.0; see [jsqr-1.4.0/LICENSE](jsqr-1.4.0/LICENSE).
- npm metadata: <https://registry.npmjs.org/jsqr/1.4.0>
- Published npm `gitHead`: `49a9633931fb8030ac2fc9cecc121d6e5a19f9a3`.
- Pinned source: <https://github.com/cozmo/jsQR/tree/49a9633931fb8030ac2fc9cecc121d6e5a19f9a3>.
- Included: all 14 production `.ts` files reachable from `src/index.ts`, plus
  the unmodified upstream `package.json`, `tsconfig.json`, `webpack.config.js`,
  `tslint.json`, and `LICENSE`.
- Excluded: upstream tests and fixtures, including their PNG and BIN files.
- The upstream commit has no `yarn.lock`, `package-lock.json`, or
  `npm-shrinkwrap.json`. No substitute historical lockfile has been invented.

The pinned commit's `dist/jsQR.js`, the integrity-verified npm tarball's
`package/dist/jsQR.js`, and the reference project's installed `jsqr@1.4.0`
distribution were byte-identical when this source set was prepared:

```text
SHA-256 bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859
```

The browser module `public/vendor/jsqr-1.4.0.mjs` uses the upstream UMD
distribution with a local `module.exports` object before it and an ES-module
default export after it. The QR decoding implementation is unchanged; the
browser file's own modification notice identifies this packaging change.

### Rebuilding jsQR

The unchanged upstream `tsconfig.json` selects `src/index.ts`; production
imports bring in the other included sources. The upstream Webpack configuration
produces `dist/jsQR.js` and a second documentation copy at `docs/jsQR.js`.

In a development checkout with a Node/npm environment compatible with the
legacy Webpack 3 toolchain, run:

```sh
cd third_party/jsqr-1.4.0
npm install --ignore-scripts --no-package-lock
npm run build
```

For the browser ESM adaptation, preserve the application's modification notice,
prepend the following line to the generated UMD distribution, and append the
export line shown below it:

```javascript
const module={exports:{}}; const exports=module.exports;
// ...the complete generated dist/jsQR.js content...
export default module.exports;
```

Keep locally installed dependencies and generated `dist/` and `docs/` outputs
out of the clean source release. No dependency installation or independent
compiler rebuild was performed during preparation. The commit, npm package,
and shipped upstream distribution match is verified; bit-for-bit reproduction
by a fresh toolchain is not claimed. The absent upstream lockfile means the
historical dependency resolution is not reproduced by the commands above.

## qrcode-generator 2.0.4

- Upstream: <https://github.com/kazuhikoarase/qrcode-generator>
- Copyright: Copyright (c) 2009 Kazuhiko Arase.
- License: MIT; see [qrcode-generator-2.0.4/LICENSE](qrcode-generator-2.0.4/LICENSE)
  and `public/vendor/qrcode-generator-LICENSE.txt`.
- npm metadata: <https://registry.npmjs.org/qrcode-generator/2.0.4>
- Published npm `gitHead`: `83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8`.
- Preferred readable JavaScript source already supplied with this release:
  `public/vendor/qrcode-generator-2.0.4.mjs`.
- Exact upstream file:
  <https://github.com/kazuhikoarase/qrcode-generator/blob/83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8/js/dist/qrcode.mjs>.

The browser module, that pinned upstream source file, and the integrity-verified
npm tarball's `package/dist/qrcode.mjs` are byte-identical:

```text
SHA-256 ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0
```

This is directly editable JavaScript and needs no transpilation for this
application. Its original notice is retained in the browser module.

## External Python runtime notices

The application loads the unmodified Pyodide 0.27.7 runtime from
`https://cdn.jsdelivr.net/pyodide/v0.27.7/full/`. Its binaries are not included in
this source release. The following upstream license texts are included:

- `public/licenses/PYODIDE-MPL-2.0.txt`:
  <https://github.com/pyodide/pyodide/blob/0.27.7/LICENSE>.
- `public/licenses/CPYTHON-LICENSE.txt`:
  <https://github.com/python/cpython/blob/v3.12.7/LICENSE>.
- `public/licenses/EMSCRIPTEN-LICENSE.txt`:
  <https://github.com/emscripten-core/emscripten/blob/3.1.58/LICENSE>.

Pyodide's exact source and build inputs are available at
<https://github.com/pyodide/pyodide/tree/0.27.7>. Its
[Makefile.envs](https://github.com/pyodide/pyodide/blob/0.27.7/Makefile.envs)
identifies CPython 3.12.7 and Emscripten 3.1.58. These notices are not a complete
inventory of all components inside the external runtime. The MPL license does
not replace the separate licenses of CPython, Emscripten, or their components.

## Refreshing and checking provenance

From the release root, `python third_party/prepare_sources.py` downloads the
same pinned public versions, checks npm tarball integrity, compares the
published QR artifacts, and rewrites the downloaded source and license files
with a fresh `third_party/SOURCE-MANIFEST.json`. It does not run upstream code,
install dependencies, download runtime binaries, or publish anything. Its
optional `--reference-jsqr-dist PATH` also compares an existing installed
`jsqr@1.4.0/dist/jsQR.js` without recording that local path in the manifest.

The project-level GNU GPLv3 text is in `LICENSE`; the application licensing
scope is documented separately by the main release README and notices.
