"""Download a catalogued vocabulary into data/, verifying the recorded checksum.

    python scripts/fetch_vocab.py emmo          # fetch, verify, extract
    python scripts/fetch_vocab.py --list        # what can be fetched

Only resources carrying an `acquire:` block in resources.yaml can be
fetched, and the sha256 recorded there must match. A mismatch stops the run: an
upstream file that changed under a fixed version tag is a fact to record, not to
work around.

Downloads land in data/<id>-<version>/ and are gitignored. Everything under there
is untrusted input: pass its path to a converter as an argument, never run anything
from inside it.

A resource made of several files (an ontology plus its code lists; an API plus its LICENSE)
lists them under `acquire.files`, each with its own url, file, bytes and sha256.

A resource behind a sign-in or a terms form carries `manual:` (what a person does) and
`file:` (the name it downloads as). This script never signs in; it tells you where to put
the file, then verifies and extracts it like any other.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import yaml

# Standalone copy for this artifact: the resource list sits beside this file and holds only
# the two vocabularies the paper's ontology-grounding table used. In the internal repository
# this reads catalog/resources.yaml, which is not published.
HERE = Path(__file__).resolve().parent
ROOT = HERE
DATA = ROOT / "data"


def acquirable() -> dict[str, dict]:
    rs = yaml.safe_load((HERE / "resources.yaml").read_text())
    return {r["id"]: r for r in rs if r.get("acquire")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(res: dict) -> Path:
    acq = res["acquire"]
    dest = DATA / f"{res['id']}-{acq.get('version', 'latest')}"
    dest.mkdir(parents=True, exist_ok=True)
    for part in acq.get("files") or []:
        fetch_one(res, part, dest)
    if acq.get("files"):
        return dest
    return fetch_one(res, acq, dest)


def fetch_one(res: dict, acq: dict, dest: Path) -> Path:
    name = acq.get("file") or acq["url"].rsplit("/", 1)[-1]
    if not name or name.startswith("refs"):
        name = f"{res['id']}-{acq.get('version', 'latest')}.tar.gz"
    archive = dest / name

    if not archive.exists() and acq.get("manual"):
        sys.exit(f"{res['id']} is not fetched automatically: {acq['manual'].strip()}\n"
                 f"Then place it at {archive.relative_to(ROOT)} and run this again.")
    if not archive.exists():
        print(f"fetching {acq['url']}", file=sys.stderr)
        urllib.request.urlretrieve(acq["url"], archive)
    got, want = sha256(archive), acq.get("sha256")
    size = archive.stat().st_size
    print(f"  {archive.name}  {size} bytes  sha256 {got[:16]}...", file=sys.stderr)
    if want and got != want:
        sys.exit(f"sha256 mismatch for {res['id']}:\n  recorded {want}\n  got      {got}\n"
                 f"The catalog records a fixed version; upstream changing under it is a "
                 f"finding. Update the acquire block only once you know why.")
    if acq.get("bytes") and size != acq["bytes"]:
        print(f"  note: recorded {acq['bytes']} bytes, got {size}", file=sys.stderr)

    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest, filter="data")
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    have = acquirable()
    if a.list or not a.id:
        for i, r in sorted(have.items()):
            acq = r["acquire"]
            url = acq.get("url") or f"{len(acq['files'])} files, first {acq['files'][0]['url']}"
            print(f"{i:12} {r.get('license') or '?':14} {acq.get('version', '?'):8} {url}")
        return 0
    if a.id not in have:
        sys.exit(f"{a.id!r} has no acquire block; add one or run --list")
    dest = fetch(have[a.id])
    print(f"{a.id} ready under {dest.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
