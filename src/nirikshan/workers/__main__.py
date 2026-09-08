"""`nirikshan-worker` -> event consumer + maintenance loop."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="nirikshan-worker")
    parser.add_argument("--once", action="store_true", help="process one batch then exit")
    parser.add_argument("--drain", action="store_true", help="process all pending events then exit")
    args = parser.parse_args()

    from nirikshan.workers.runner import drain, run

    if args.drain:
        n = drain()
        print(f"drained {n} events")
        return
    run(once=args.once)


if __name__ == "__main__":
    main()
