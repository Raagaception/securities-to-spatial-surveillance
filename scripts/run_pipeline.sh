#!/usr/bin/env bash
#
# Run the extraction pipeline end to end.
#
# The repository root is derived from this script's own location, so the script
# works whichever directory you call it from.
#
#     scripts/run_pipeline.sh
#
# Set PYTHON to use an interpreter other than the one on your PATH, for example
# an environment you have not activated:
#
#     PYTHON=/path/to/env/bin/python scripts/run_pipeline.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

PY="${PYTHON:-python}"

"$PY" scripts/extract_pdfplumber.py
"$PY" scripts/extract_pymupdf.py
"$PY" scripts/diff_extractors.py

echo
echo "Outputs written to outputs/extraction/"
