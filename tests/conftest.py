import os
from pathlib import Path

# Tests must never share the user's installed overlay configuration or cache.
os.environ['CODEX_TOKENUSE_DATA_DIR'] = str(Path(__file__).resolve().parents[1] / '.test-data')
