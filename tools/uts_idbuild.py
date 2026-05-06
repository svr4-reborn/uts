#!/usr/bin/env python3

from __future__ import annotations

import argparse

try:
    from . import uts_idmkunix
except ImportError:
    import uts_idmkunix


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = uts_idmkunix._normalize_option_values(argv, {"--cflag", "--include-dir"})
    parser = argparse.ArgumentParser(description="Thin Python replacement for the historical idbuild wrapper.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--ld", required=True)
    parser.add_argument("--output")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--include-dir", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    idmkunix_args = [
        "--manifest",
        args.manifest,
        "--cc",
        args.cc,
        "--ld",
        args.ld,
    ]
    if args.output:
        idmkunix_args.extend(["--output", args.output])
    for cflag in args.cflag:
        idmkunix_args.extend(["--cflag", cflag])
    for include_dir in args.include_dir:
        idmkunix_args.extend(["--include-dir", include_dir])
    return uts_idmkunix.main(idmkunix_args)


if __name__ == "__main__":
    raise SystemExit(main())