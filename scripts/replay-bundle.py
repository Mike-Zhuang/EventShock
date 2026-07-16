#!/usr/bin/env python3
"""从命令行重放 EventShock 实验导出包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.replay import ReplayBundleError, replayBundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay an EventShock export and verify deterministic hashes.",
    )
    parser.add_argument("bundle", type=Path, help="Path to an EventShock ZIP export")
    parser.add_argument(
        "--allow-python-patch-mismatch",
        action="store_true",
        help="Diagnostic only: do not require CPython 3.12.13",
    )
    arguments = parser.parse_args()
    try:
        report = replayBundle(
            arguments.bundle,
            requireExactPython=not arguments.allow_python_patch_mismatch,
        )
    except ReplayBundleError as error:
        print(json.dumps({"verified": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
