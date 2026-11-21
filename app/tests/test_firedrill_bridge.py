"""Protocol smoke test: no database queries or model calls."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class BridgeProtocolTest(unittest.TestCase):
    def test_readiness_and_multiple_requests(self):
        app = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "firedrill_bridge.py"], cwd=app,
            input='{"id":"first","input":{}}\n{"id":"second","input":{}}\n',
            capture_output=True, text=True, timeout=15, check=True,
        )
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(records[0], {"ready": "tab-negotiation-bridge.v1"})
        self.assertEqual([r["id"] for r in records[1:]], ["first", "second"])
        self.assertTrue(all("error" in r for r in records[1:]))


if __name__ == "__main__":
    unittest.main()
