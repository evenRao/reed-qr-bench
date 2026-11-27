"""Download a pinned, licensed ZXing black-box subset without using a decoder as oracle."""

import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "zxing-3.5.3"
BASE = f"https://raw.githubusercontent.com/zxing/zxing/{TAG}"
PATH = "core/src/test/resources/blackbox/qrcode-1"


def fetch(url):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "REED-QR-Bench-corpus-setup"}),
        timeout=30,
    ) as response:
        return response.read()


def main():
    listing = json.loads(
        fetch(f"https://api.github.com/repos/zxing/zxing/contents/{PATH}?ref={TAG}")
    )
    names = {i["name"] for i in listing}
    files = sorted(
        n
        for n in names
        if n.lower().endswith((".png", ".jpg", ".jpeg")) and n.rsplit(".", 1)[0] + ".txt" in names
    )[:12]
    if len(files) < 4:
        raise RuntimeError("Upstream corpus layout differs from the pinned fixture contract")
    directory = ROOT / "assets/corpora"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "ZXing public black-box QR subset",
        "version": TAG + "-subset-v1",
        "source": f"https://github.com/zxing/zxing/tree/{TAG}/{PATH}",
        "license": "Apache-2.0; see ZXING-LICENSE and ZXING-NOTICE",
        "real_world": False,
        "items": [],
    }
    with zipfile.ZipFile(directory / "zxing-subset.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for index, name in enumerate(files):
            data = fetch(f"{BASE}/{PATH}/{name}")
            oracle = fetch(f"{BASE}/{PATH}/{name.rsplit('.', 1)[0]}.txt")
            # ZXing's own harness reads the whole label file; never trim whitespace.
            expected = oracle.decode("utf-8")
            archive.writestr("images/" + name, data)
            archive.writestr("upstream-labels/" + name.rsplit(".", 1)[0] + ".txt", oracle)
            manifest["items"].append(
                {
                    "file": "images/" + name,
                    "split": "development" if index % 2 == 0 else "held_out",
                    "scenario": "public_blackbox",
                    "expected": [expected],
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        archive.writestr("ZXING-LICENSE", fetch(BASE + "/LICENSE"))
        archive.writestr("ZXING-NOTICE", fetch(BASE + "/NOTICE"))
    print(
        f"Prepared {len(files)} independently labelled public cases "
        "at assets/corpora/zxing-subset.zip"
    )


if __name__ == "__main__":
    main()
