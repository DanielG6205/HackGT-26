"""Full camera/audio application with robot hardware always mocked.

Run: python tests/test_full.py
"""
from pathlib import Path
import sys

# Support direct execution after moving the manual launchers into tests/.
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import main as run_app


def main(argv=None):
    return run_app([*(sys.argv[1:] if argv is None else argv), '--mock-robot'])


if __name__ == '__main__':
    raise SystemExit(main())
