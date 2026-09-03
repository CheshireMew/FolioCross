from __future__ import annotations

import argparse
import json

from ..application.service import FolioCrossService
from ..errors import FolioCrossError
from ..infrastructure.workspace import Workspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    try:
        service = FolioCrossService(Workspace(args.workspace))
        result = service.import_book(args.path, service.default_job_config())
    except FolioCrossError as error:
        result = error.as_dict()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
