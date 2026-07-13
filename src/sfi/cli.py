"""argparse entry point (§5.8). L4 — imports everything below, lazily."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sfi",
        description="SEC Filing Intelligence — grounded Q&A over 10-K/10-Q PDFs",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    sub.add_parser(
        "manifest",
        help="stage 0: 2 EDGAR submissions calls -> manifest.json; "
        "prints the filename<->accession join table",
    )

    p_ingest = sub.add_parser(
        "ingest",
        help="segment -> extract -> accept -> write; stops loudly at first quarantine",
    )
    p_ingest.add_argument("--filing", metavar="ACCESSION")
    p_ingest.add_argument(
        "--dry-run", action="store_true", help="segment only: print located page ranges"
    )

    p_ask = sub.add_parser("ask", help="answer one question with full evidence")
    p_ask.add_argument("question")
    p_ask.add_argument("--json", action="store_true", help="dump the evidence object")

    p_bench = sub.add_parser("bench", help="benchmark harness (§6)")
    p_bench.add_argument("action", choices=["run", "spotcheck"])

    p_measure = sub.add_parser(
        "measure", help="rule-14 measurements -> notes/measurements.md"
    )
    p_measure.add_argument("experiment", choices=["llm-arithmetic", "label-cosine"])

    args = parser.parse_args(argv)

    from .common import config
    from .store import db

    config.ensure_dirs()
    db.init_db()  # idempotent, so every command sees the full schema

    if args.command == "manifest":
        from .ingest import manifest

        return manifest.run()

    if args.command == "ingest":
        from .ingest import run as ingest_run

        return ingest_run.run(filing=args.filing, dry_run=args.dry_run)

    not_yet = {"ask": "P0.6", "bench": "P0.7", "measure": "M1"}
    parser.exit(2, f"sfi {args.command}: not built yet (arrives at {not_yet[args.command]})\n")
    return 2  # unreachable; parser.exit raises


if __name__ == "__main__":
    raise SystemExit(main())
