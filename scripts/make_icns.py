#!/usr/bin/env python3
import struct
import sys
from pathlib import Path


ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}

ICONSET_FILES = {
    16: "icon_16x16.png",
    32: "icon_32x32.png",
    64: "icon_32x32@2x.png",
    128: "icon_128x128.png",
    256: "icon_256x256.png",
    512: "icon_512x512.png",
    1024: "icon_512x512@2x.png",
}


def png_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: make_icns.py <iconset_dir> <output.icns>", file=sys.stderr)
        return 2

    iconset_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    entries: list[bytes] = []

    for size, filename in ICONSET_FILES.items():
        path = iconset_dir / filename
        data = path.read_bytes()
        width, height = png_size(data)
        if width != size or height != size:
            raise ValueError(f"{path} is {width}x{height}, expected {size}x{size}")

        payload_size = len(data) + 8
        entries.append(ICNS_TYPES[size] + struct.pack(">I", payload_size) + data)

    body = b"".join(entries)
    output_path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
