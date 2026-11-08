"""Run with: uv run python -m phineas < synthetic-statement.csv"""

import argparse
import csv
import json
import sys

from phineas.application import summarize_canonical_statement
from phineas.ingestion.errors import (
    StatementValidationError,
    UnsupportedCsvSchemaError,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize a canonical CSV from standard input in memory."
    )
    parser.parse_args()
    try:
        summary = summarize_canonical_statement(sys.stdin)
    except StatementValidationError as error:
        print(json.dumps({
            "error": "statement_validation_failed",
            "issues": [
                {"row_number": issue.row_number, "field": issue.field,
                 "code": issue.code.value}
                for issue in error.issues
            ],
        }), file=sys.stderr)
        return 1
    except (UnsupportedCsvSchemaError, csv.Error, UnicodeError):
        print('{"error": "invalid_csv_statement"}', file=sys.stderr)
        return 1
    print(summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
