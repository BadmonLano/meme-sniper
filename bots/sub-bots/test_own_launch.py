"""Offline tests for own-launch helpers. Run: python -m unittest test_own_launch -v"""
import sys, unittest
from pathlib import Path
_h = Path(__file__).resolve().parent
for _p in (_h, _h.parent, _h / "sub-bots"):
    sys.path.insert(0, str(_p))
import own_launch_core as c


class Core(unittest.TestCase):
    def test_defaults(self):
        s = c.settings_from_env({})
        self.assertEqual((s["mode"], s["treasury_pct"], s["sl_pct"], s["lock_mode"], s["fee_claim_h"]),
                         ("hold", 0.0, None, "off", 24.0))  # shipped default: .env.example + SKILL.md say 0
        self.assertEqual(s["ladder"], [(2.0, 25.0), (5.0, 25.0), (10.0, 25.0)])

    def test_bad_values_fall_back(self):
        s = c.settings_from_env({"OWN_LAUNCH_MODE": "yolo", "OWN_LAUNCH_LOCK_MODE": "lock",
                                 "OWN_LAUNCH_SL_PCT": "off", "OWN_LAUNCH_TREASURY_PCT": "250"})
        self.assertEqual((s["mode"], s["lock_mode"], s["sl_pct"], s["treasury_pct"]), ("hold", "off", None, 100.0))

    def test_ladder_parse(self):
        self.assertEqual(c.parse_ladder("2x:60,3x:60,1x:10,junk"), [(2.0, 60.0), (3.0, 40.0)])
        self.assertEqual(c.parse_ladder("5x:25,2x:25"), [(5.0, 25.0)])

    def test_split(self):
        self.assertEqual(c.split_amounts(1000, "hold", 50), (500, 500))
        self.assertEqual(c.split_amounts(1000, "flip", 50), (1000, 0))

    def test_burn(self):
        self.assertEqual(c.burn_amount(1000, "off", 50), 0)
        self.assertEqual(c.burn_amount(1000, "burn", 10), 100)

    def test_ladder_walk(self):
        L = c.parse_ladder("2x:25,5x:25,10x:25"); cur = 1000; tps = []
        for i in range(4):
            p = c.rung_protection(L, i, 1000, cur)
            if not p:
                break
            tps.append(p["take_profit_pct"]); cur = round(cur * (1 - p["tp_sell_pct"] / 100))
        self.assertEqual(tps, [100.0, 400.0, 900.0]); self.assertEqual(cur, 250)

    def test_new_live_launches(self):
        res = {"results": {"a": {"mode": "LIVE", "mint": "M1", "signature": "S"},
                           "b": {"mode": "dry-run", "mint": "M2"},
                           "c": {"mode": "LIVE", "mint": "M3", "signature": "S"}}}
        self.assertEqual([r["mint"] for r in c.new_live_launches(res, {"M3": {}})], ["M1"])


class Burn(unittest.TestCase):
    def test_burn_ix_data(self):
        try:
            import launch_rail as lr
        except Exception as e:
            self.skipTest(f"launch_rail deps missing: {e}")
        self.assertEqual(lr.burn_ix_data(1), bytes([8, 1, 0, 0, 0, 0, 0, 0, 0]))
        with self.assertRaises(ValueError):
            lr.burn_ix_data(0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
