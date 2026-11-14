"""Create the 3 demo accounts (admin@demo, business@demo, user@demo).

Passwords come from .env: DEMO_ADMIN_PW, DEMO_BUSINESS_PW, DEMO_USER_PW (min 8 chars).
Run:  python scripts/seed_users.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import auth, config  # noqa: E402  (config loads .env)

if __name__ == "__main__":
    print(f"Database: {config.db_path()}")
    auth.seed_demo_users(verbose=True)
