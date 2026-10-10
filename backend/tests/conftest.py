import os
from pathlib import Path

_db = Path(__file__).with_name("_test.sqlite")
if _db.exists():
    _db.unlink()
os.environ["DESK_DATABASE"] = str(_db)
os.environ["REDDIT_CLIENT_ID"] = ""
os.environ["REDDIT_CLIENT_SECRET"] = ""
os.environ["REDDIT_USERNAME"] = ""
