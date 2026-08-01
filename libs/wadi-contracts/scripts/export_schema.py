"""CLI shim for schema export — logic lives in ``wadi_contracts.schema_export``.

Usage: ``python export_schema.py --out schemas/``
"""

import argparse
from pathlib import Path

from wadi_contracts.schema_export import export


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    args = parser.parse_args()
    out_dir: Path = args.out
    for path in export(out_dir):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
