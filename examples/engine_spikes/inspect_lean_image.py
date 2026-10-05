"""Read public LEAN manifest metadata without downloading or executing image layers."""

import argparse
import json
import urllib.request
from pathlib import Path

REGISTRY = "https://registry-1.docker.io/v2/quantconnect/lean"
PINNED_INDEX = "sha256:442c0f886cbc55403d779fa3cbd6070c192a7b8e1f2a5dcf9b570b735dc543e4"


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Metadata response exceeded the 2 MB experiment bound.")
        return json.loads(body)


def inspect():
    token = get(
        "https://auth.docker.io/token?service=registry.docker.io"
        "&scope=repository:quantconnect/lean:pull"
    )["token"]
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": (
            "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json"
        ),
    }
    index = get(f"{REGISTRY}/manifests/{PINNED_INDEX}", headers)
    arm = next(
        item
        for item in index["manifests"]
        if item.get("platform") == {"architecture": "arm64", "os": "linux"}
    )
    manifest = get(f"{REGISTRY}/manifests/{arm['digest']}", headers)
    config = get(f"{REGISTRY}/blobs/{manifest['config']['digest']}", headers)
    return {
        "image": "quantconnect/lean",
        "index_digest": PINNED_INDEX,
        "arm64_digest": arm["digest"],
        "platform": arm["platform"],
        "compressed_layer_bytes": sum(layer["size"] for layer in manifest["layers"]),
        "created": config["created"],
        "labels": config["config"].get("Labels"),
        "entrypoint": config["config"].get("Entrypoint"),
        "layers_downloaded": False,
        "engine_executed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(inspect(), indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
        print(f"Pinned public image metadata saved: {args.output}")
    else:
        print(output, end="")
