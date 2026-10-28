"""Fetch pinned public vendor sources without executing upstream code.

This helper writes only third_party/, LICENSE, and three runtime license texts.
It deliberately excludes vendor tests, fixtures, images, and runtime binaries.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
JSQR_COMMIT = "49a9633931fb8030ac2fc9cecc121d6e5a19f9a3"
QR_COMMIT = "83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8"
LICENSES = {
    "LICENSE": "https://www.gnu.org/licenses/gpl-3.0.txt",
    "public/licenses/PYODIDE-MPL-2.0.txt": "https://raw.githubusercontent.com/pyodide/pyodide/0.27.7/LICENSE",
    "public/licenses/CPYTHON-LICENSE.txt": "https://raw.githubusercontent.com/python/cpython/v3.12.7/LICENSE",
    "public/licenses/EMSCRIPTEN-LICENSE.txt": "https://raw.githubusercontent.com/emscripten-core/emscripten/3.1.58/LICENSE",
}


def fetch(url):
    request = Request(url, headers={"User-Agent": "PenC-Pocket-public-source-preparation"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(relative, data):
    target = ROOT / relative
    resolved = target.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Output escaped source-release root")
    if not (relative.startswith("third_party/") or relative in LICENSES):
        raise ValueError("Output is outside assigned vendor-source scope")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def artifact(relative, url, data):
    write(relative, data)
    return {"path": relative, "url": url, "sha256": digest(data), "bytes": len(data)}


def package_metadata(name, version, expected_commit):
    url = f"https://registry.npmjs.org/{name}/{version}"
    raw = fetch(url)
    metadata = json.loads(raw)
    if metadata["version"] != version or metadata.get("gitHead") != expected_commit:
        raise ValueError(f"Unexpected published metadata for {name}")
    info = {"name": name, "version": version, "metadata_url": url,
            "metadata_sha256": digest(raw), "git_commit": expected_commit,
            "npm_tarball_url": metadata["dist"]["tarball"],
            "npm_integrity": metadata["dist"]["integrity"]}
    tar = fetch(info["npm_tarball_url"])
    algorithm, expected = info["npm_integrity"].split("-", 1)
    actual = base64.b64encode(hashlib.new(algorithm, tar).digest()).decode("ascii")
    if actual != expected:
        raise ValueError(f"npm tarball integrity mismatch for {name}")
    info["npm_tarball_sha256"] = digest(tar)
    info["npm_integrity_verified"] = True
    return info, tar


def tar_member(archive, member):
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        item = package.getmember(member)
        if not item.isfile():
            raise ValueError("Expected regular npm archive member")
        return package.extractfile(item).read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-jsqr-dist", type=Path,
                        help="Optional existing jsqr@1.4.0 dist/jsQR.js to compare in memory")
    args = parser.parse_args()
    jsqr, jsqr_tar = package_metadata("jsqr", "1.4.0", JSQR_COMMIT)
    qr, qr_tar = package_metadata("qrcode-generator", "2.0.4", QR_COMMIT)
    tree_url = f"https://api.github.com/repos/cozmo/jsQR/git/trees/{JSQR_COMMIT}?recursive=1"
    tree_bytes = fetch(tree_url)
    tree = json.loads(tree_bytes)
    if tree.get("truncated") or tree["sha"] != JSQR_COMMIT:
        raise ValueError("Incomplete or unexpected jsQR source tree")
    blobs = {item["path"] for item in tree["tree"] if item["type"] == "blob"}
    production = sorted(path for path in blobs if path.startswith("src/")
                        and path.endswith(".ts") and "test" not in PurePosixPath(path).parts
                        and "test-data" not in PurePosixPath(path).parts
                        and PurePosixPath(path).name != "test.ts"
                        and not path.endswith(".test.ts"))
    configs = ["package.json", "tsconfig.json", "webpack.config.js", "tslint.json", "LICENSE"]
    if not all(path in blobs for path in configs):
        raise ValueError("Missing required upstream build inputs")
    lock_candidates = ["yarn.lock", "package-lock.json", "npm-shrinkwrap.json"]
    locks = [path for path in lock_candidates if path in blobs]
    urls = [("third_party/jsqr-1.4.0/" + path,
             f"https://raw.githubusercontent.com/cozmo/jsQR/{JSQR_COMMIT}/{path}")
            for path in production + configs + locks]
    urls += list(LICENSES.items())
    urls += [("third_party/qrcode-generator-2.0.4/LICENSE",
              f"https://raw.githubusercontent.com/kazuhikoarase/qrcode-generator/{QR_COMMIT}/LICENSE")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        contents = list(pool.map(lambda pair: fetch(pair[1]), urls))
    by_path = {pair[0]: data for pair, data in zip(urls, contents)}
    if not by_path["LICENSE"].lstrip().startswith(b"GNU GENERAL PUBLIC LICENSE"):
        raise ValueError("Unexpected GNU GPL3 response")
    if b"Version 3, 29 June 2007" not in by_path["LICENSE"]:
        raise ValueError("Unexpected GNU GPL version")
    if not by_path["public/licenses/PYODIDE-MPL-2.0.txt"].startswith(b"Mozilla Public License Version 2.0"):
        raise ValueError("Unexpected Pyodide license response")
    jsqr_dist_url = f"https://raw.githubusercontent.com/cozmo/jsQR/{JSQR_COMMIT}/dist/jsQR.js"
    jsqr_dist = fetch(jsqr_dist_url)
    npm_jsqr_dist = tar_member(jsqr_tar, "package/dist/jsQR.js")
    if jsqr_dist != npm_jsqr_dist:
        raise ValueError("jsQR commit dist differs from npm package")
    jsqr["upstream_dist"] = {"url": jsqr_dist_url, "sha256": digest(jsqr_dist),
                             "bytes": len(jsqr_dist), "npm_dist_byte_identical": True}
    if args.reference_jsqr_dist:
        reference = args.reference_jsqr_dist.read_bytes()
        if reference != jsqr_dist:
            raise ValueError("jsQR commit dist differs from reference project")
        jsqr["upstream_dist"]["reference_package_dist_byte_identical"] = True
        jsqr["upstream_dist"]["reference_package_dist_sha256"] = digest(reference)
    jsqr["source_tree_url"] = tree_url
    jsqr["source_tree_response_sha256"] = digest(tree_bytes)
    jsqr["source_files"] = production
    jsqr["upstream_lockfiles"] = locks
    jsqr["lockfile_note"] = "No dependency lockfile exists at this upstream commit; none was invented."
    jsqr["rebuild_status"] = "NOT_RUN; source-to-upstream-dist identity is established by exact commit and npm package comparison, not an independent compiler build."
    qr_url = f"https://raw.githubusercontent.com/kazuhikoarase/qrcode-generator/{QR_COMMIT}/js/dist/qrcode.mjs"
    qr_source = fetch(qr_url)
    if qr_source != tar_member(qr_tar, "package/dist/qrcode.mjs"):
        raise ValueError("QR generator source differs from npm package")
    public_qr = ROOT / "public/vendor/qrcode-generator-2.0.4.mjs"
    if public_qr.read_bytes() != qr_source:
        raise ValueError("QR generator source differs from public browser module")
    qr["preferred_source"] = {"path": "public/vendor/qrcode-generator-2.0.4.mjs",
                              "url": qr_url, "sha256": digest(qr_source), "bytes": len(qr_source),
                              "npm_dist_byte_identical": True, "public_module_byte_identical": True}
    records = [artifact(relative, url, data) for (relative, url), data in zip(urls, contents)]
    manifest = {"schema_version": 1, "prepared_utc": datetime.now(timezone.utc).isoformat(),
                "status": "PINNED_PRODUCTION_SOURCE_AND_LICENSES_PREPARED_NO_RUNTIME_BINARIES",
                "packages": [jsqr, qr], "files": records,
                "exclusions": ["tests", "test-data", "fixtures", "images", "firmware", "node_modules", "runtime binaries"],
                "runtime_notice_scope": "Pyodide, CPython and Emscripten license texts are supplied as notices for the external CDN runtime. This is not a complete runtime SBOM."}
    write("third_party/SOURCE-MANIFEST.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": manifest["status"], "downloaded_source_and_license_files": len(records),
                      "jsqr_production_typescript_files": len(production),
                      "jsqr_dist_sha256": digest(jsqr_dist),
                      "qr_source_sha256": digest(qr_source), "upstream_jsqr_lockfiles": locks}, indent=2))


if __name__ == "__main__":
    main()
