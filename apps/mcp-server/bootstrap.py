"""Makes apps/api's `app` package importable from this sibling app,
without a second copy of the DB/auth/tool stack. Import this before
anything else in every module here — same bootstrap idiom as
infra/scripts/seed_demo_data.py.
"""

import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))
