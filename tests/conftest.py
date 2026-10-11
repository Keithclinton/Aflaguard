import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# keep test calls out of the real logs and runtime state
_tmp = tempfile.mkdtemp(prefix="aflaguard_test_")
os.environ.setdefault("AFLAGUARD_LOG_DIR", os.path.join(_tmp, "logs"))
os.environ.setdefault("AFLAGUARD_STATE_DB", os.path.join(_tmp, "state.db"))

MANIFEST = json.loads((ROOT / "data" / "synthetic" / "mess_manifest.json").read_text(encoding="utf-8"))
