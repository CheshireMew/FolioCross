"""Subprocess bridge for a separately installed GPL KindleUnpack package."""

from __future__ import annotations

import json
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: kindleunpack_bridge.py INPUT")
    import mobi

    extraction_dir, content_path = mobi.extract(sys.argv[1])
    print(
        json.dumps(
            {"ok": True, "extraction_dir": extraction_dir, "content_path": content_path},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
