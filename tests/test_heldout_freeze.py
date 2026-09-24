"""Guard the source-only target selection against outcome-dependent filtering."""

import hashlib
import unittest

from benchmarks.heldout_freeze import selected_functions, under


class HeldoutFreezeTests(unittest.TestCase):
    def test_root_matching_uses_path_components(self):
        self.assertTrue(under("src/pkg/core.py", ["src/pkg"]))
        self.assertFalse(under("src/pkg_extra/core.py", ["src/pkg"]))

    def test_selection_excludes_prior_targets_but_not_functions_without_candidates(self):
        config = {"seed": "fixed", "functions_per_repository": 2}
        repo = {"name": "example", "source_roots": ["src/pkg"], "source_excludes": ["src/pkg/tests"]}
        symbols = [
            {"id": "src/pkg/a.py::alpha", "path": "src/pkg/a.py", "kind": "function"},
            {"id": "src/pkg/b.py::beta", "path": "src/pkg/b.py", "kind": "function"},
            {"id": "src/pkg/c.py::gamma", "path": "src/pkg/c.py", "kind": "function"},
            {"id": "src/pkg/tests/test_c.py::test_gamma", "path": "src/pkg/tests/test_c.py", "kind": "test"},
            {"id": "other/x.py::delta", "path": "other/x.py", "kind": "function"},
        ]
        data = {"symbols": {symbol["id"]: symbol for symbol in symbols}}
        picked = selected_functions(config, repo, data, {"src/pkg/b.py::beta"})
        self.assertEqual({item["id"] for item in picked},
                         {"src/pkg/a.py::alpha", "src/pkg/c.py::gamma"})
        expected = sorted(picked, key=lambda symbol: hashlib.sha256(
            f'fixed\0example\0{symbol["id"]}'.encode()).hexdigest())
        self.assertEqual(picked, expected)


if __name__ == "__main__":
    unittest.main()
