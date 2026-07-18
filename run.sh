#!/usr/bin/env bash
# Launch the ETS Pulse dashboard.
#
# Sets ARROW_DEFAULT_MEMORY_POOL=system to avoid a pyarrow/mimalloc segfault on
# macOS + Python 3.13 (symptom: "Python quit unexpectedly" and the server dies
# when a table renders). Using the system allocator sidesteps the bug.
set -euo pipefail

cd "$(dirname "$0")"

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export ARROW_DEFAULT_MEMORY_POOL=system

exec streamlit run app.py "$@"
