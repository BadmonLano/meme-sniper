"""Unit tests for the launch rail (network: GitHub API). Run: python -m unittest test_launch_rail -v"""
import os, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
os.environ["LAUNCH_RAIL_LIVE"] = "0"   # tests never send (also the shipped default)
import launch_rail as lr
import tempfile as _tf
_T = Path(_tf.mkdtemp())                      # tests never write the real bot_logs
lr.LOG_FILE = _T / "launch_rail_log.jsonl"; lr.SEEN_FILE = _T / "launch_rail_seen.json"

class RepoGate(unittest.TestCase):
    def test_good_repo(self):
        r = lr.check_repo("https://github.com/psf/requests")   # active public repo
        print("\n good:", r["score"], r["reasons"]); self.assertTrue(r["passed"])
    def test_missing_repo(self):
        r = lr.check_repo("https://github.com/example-org/this-repo-does-not-exist-xyz")
        self.assertFalse(r["passed"])
    def test_archived_repo(self):
        r = lr.check_repo("https://github.com/atom/atom")
        print("\n archived:", r["score"], r["reasons"]); self.assertFalse(r["passed"])
    def test_not_github(self):
        self.assertFalse(lr.check_repo("https://gitlab.com/a/b")["passed"])

class Gates(unittest.TestCase):
    def test_metadata_links_repo(self):
        m = lr.build_metadata({"repo_url": "https://github.com/x/y", "name": "N", "ticker": "T", "description": "d"})
        self.assertEqual(m["website"], "https://github.com/x/y"); self.assertIn("github.com/x/y", m["description"])
    def test_default_on(self):
        self.assertFalse(lr.DEFAULT_CONFIG["LAUNCH_RAIL_ENABLED"])
    def test_live_env_zero_stays_dry(self):
        req = {"repo_url": "https://github.com/your-org/your-repo", "name": "Test Rail", "ticker": "TRAIL",
               "description": "t", "image": "x.png", "dev_buy_sol": 0.01}
        r = lr.launch(req, no_upload=True, throwaway=True, no_build=True)
        self.assertEqual(r["mode"], "dry-run"); self.assertTrue(r["blockers"])
    def test_cap(self):
        req = {"repo_url": "https://github.com/your-org/your-repo", "name": "Test Rail", "ticker": "TRAIL",
               "description": "t", "image": "x.png", "dev_buy_sol": 5}
        self.assertEqual(lr.launch(req, no_upload=True, throwaway=True, force=True)["status"], "blocked_dev_buy_cap")

class Relay(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        lr.JSON_RELAY = self.tmp / "json_relay"; lr.JSON_RELAY.mkdir()
        lr.RELAY_REQUEST_FILE = lr.JSON_RELAY / "launch_requests.json"
        lr.RELAY_REQUEST_DIR = lr.JSON_RELAY / "launch_requests"
        lr.RELAY_RESULTS_FILE = lr.JSON_RELAY / "launch_results.json"
        lr.SEEN_FILE = self.tmp / "seen.json"; lr.LOG_FILE = self.tmp / "log.jsonl"
        self.calls = []
        self._orig = lr.launch
        lr.launch = lambda req, **kw: (self.calls.append(kw) or {"status": "dry_run_ok", "mode": "dry-run", "mint": "M"})
    def tearDown(self):
        lr.launch = self._orig
    def req(self, **o):
        r = {"id": "t1", "action": "launch", "repo_url": "https://github.com/x/y", "name": "N", "ticker": "T",
             "description": "d", "image": "i.png", "dev_buy_sol": 0.1, "dry_run": True, "requested_by": "test"}
        r.update(o); return r
    def test_schema_reject(self):
        self.assertTrue(lr.validate_relay_request({"id": "x"}))
        self.assertTrue(lr.validate_relay_request(self.req(evil=1)))
        self.assertFalse(lr.validate_relay_request(self.req()))
    def test_idempotent(self):
        import json
        lr.RELAY_REQUEST_FILE.write_text(json.dumps(self.req()))
        lr.process_relay(no_upload=True)
        lr.RELAY_REQUEST_FILE.write_text(json.dumps(self.req()))
        lr.process_relay(no_upload=True)
        self.assertEqual(len(self.calls), 1)
        res = json.loads(lr.RELAY_RESULTS_FILE.read_text())["results"]["t1"]
        self.assertIn("request dry_run is true", res["why_not_live"])
    def test_folder_and_dry_run_passthrough(self):
        import json
        lr.RELAY_REQUEST_DIR.mkdir()
        (lr.RELAY_REQUEST_DIR / "a.json").write_text(json.dumps(self.req(id="t2", dry_run=False)))
        lr.process_relay(no_upload=True)
        self.assertFalse(self.calls[0]["dry_run"])
        self.assertTrue(list(lr.RELAY_REQUEST_DIR.glob("a.json.processed_*")))

if __name__ == "__main__":
    unittest.main(verbosity=2)
