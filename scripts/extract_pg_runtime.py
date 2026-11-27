"""Extract just the PostgreSQL server runtime from the portable binaries zip.

The Windows binaries archive also ships pgAdmin 4 and documentation, whose paths
exceed the Windows MAX_PATH limit in a deep workspace. Only ``bin``, ``lib`` and
``share`` are required to run a local server for migration and test verification.

Usage: python scripts/extract_pg_runtime.py <zip> <destination>
"""

from __future__ import annotations

import os
import sys
import zipfile

KEEP = ("pgsql/bin/", "pgsql/lib/", "pgsql/share/")


def main(archive: str, destination: str) -> int:
    failures = 0
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            normalised = name.replace(os.sep, "/")
            if not normalised.startswith(KEEP) or normalised.endswith("/"):
                continue
            target = os.path.join(destination, *normalised.split("/"))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
            except OSError as exc:  # pragma: no cover - platform specific
                failures += 1
                print(f"FAIL {normalised}: {exc}")
    return failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
