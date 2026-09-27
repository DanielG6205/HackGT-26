#!/usr/bin/env python3
"""CLI entry: python tools/calibrate_robot.py [--mock] [--port DEVICE]."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep the original REPL available when no new mode is requested.
if len(sys.argv) > 1 and sys.argv[1] in {'limits', 'world', 'track'}:
    from app.robot.gaze_calibrate import main
else:
    from app.robot.calibrate import main

if __name__ == "__main__":
    raise SystemExit(main())
