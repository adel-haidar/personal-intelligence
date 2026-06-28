import sys
from pathlib import Path

# The agents service uses 'agents/' as its import root (from assistant... imports).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))
# The API service (private_internet package) lives under src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
