from __future__ import annotations

import argparse
import json
import sys

from ..errors import FolioCrossError
from ..infrastructure.workspace import Workspace
from .engine import WorkerEngine, stdout_event_sink


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--retranslate", metavar="SEGMENT_ID")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--export-format")
    parser.add_argument("--output")
    parser.add_argument("--expected-version", type=int)
    args = parser.parse_args()
    try:
        engine = WorkerEngine(Workspace(args.workspace), event_sink=stdout_event_sink)
        if args.review:
            result = engine.deep_review(args.job)
        elif args.prepare_only:
            result = engine.prepare_only(args.job)
        elif args.retranslate:
            result = engine.retranslate_segment(
                args.job, args.retranslate, args.instruction, expected_version=args.expected_version
            )
        elif args.export_format:
            result = engine.export_only(args.job, args.export_format, args.output)
        else:
            result = engine.run(args.job, export_when_done=not args.no_export)
        print(
            json.dumps(
                {"protocol_version": 1, "type": "worker.result", "payload": result},
                ensure_ascii=False,
            )
        )
    except FolioCrossError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as error:
        wrapped = FolioCrossError(
            "operation_failed",
            str(error) or "Worker 操作失败。",
            details={"exception": type(error).__name__},
        )
        print(json.dumps(wrapped.as_dict(), ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
