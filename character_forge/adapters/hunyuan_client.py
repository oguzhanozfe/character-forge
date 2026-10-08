"""Minimal client for a local Hunyuan3D-2.x API server (POST /generate -> GLB bytes).

The request schema differs between Hunyuan3D releases and community launchers; verify the fields against your
server's api_server.py and adjust --payload-extra. Read LICENSE-NOTES.md: Hunyuan3D community terms restrict
use/distribution of outputs in the EU, UK and South Korea.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--no-texture", action="store_true")
    parser.add_argument("--payload-extra", default="{}", help="JSON merged into the request body")
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args(argv)
    body = {"image": base64.b64encode(Path(args.image).read_bytes()).decode("ascii"), "seed": args.seed,
            "texture": not args.no_texture}
    body.update(json.loads(args.payload_extra))
    request = urllib.request.Request(args.url.rstrip("/") + "/generate", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        data = response.read()
    if not data.startswith(b"glTF"):
        print("Server did not return a binary glTF (first bytes %r)" % data[:16], file=sys.stderr)
        return 2
    Path(args.output).write_bytes(data)
    print("wrote", args.output, len(data), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
