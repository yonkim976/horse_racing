from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("rs_equal_mixture.py")
SPEC = importlib.util.spec_from_file_location("rs_equal_mixture_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load equal-mixture test target")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EqualMixtureSyntheticTests(unittest.TestCase):
    def test_full_synthetic_contract(self) -> None:
        result = MODULE.run_synthetic_checks()
        self.assertEqual(result["status"], "PASS_SYNTHETIC_ONLY")
        self.assertGreaterEqual(result["check_count"], 7)
        self.assertFalse(result["real_sources_opened"])
        self.assertFalse(result["E_real_data_constructed"])


if __name__ == "__main__":
    unittest.main()
