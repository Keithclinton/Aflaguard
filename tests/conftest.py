import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# keep test calls out of the real logs
os.environ.setdefault("AFLAGUARD_LOG_DIR", tempfile.mkdtemp(prefix="aflaguard_logs_"))

MANIFEST = json.loads((ROOT / "data" / "synthetic" / "mess_manifest.json").read_text(encoding="utf-8"))
