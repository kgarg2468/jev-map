import json
import subprocess
import sys
import unittest
from pathlib import Path

from jev_map.index import build
from jev_map.store import explain_link, load, related_tests, save
from support import TemporaryRepository


class RepositoryTest(TemporaryRepository):
    def fixture(self):
        self.write("src/pkg/core.py", "def normalize(x):\n    return x.strip()\n\ndef public(x):\n    return normalize(x)\n")
        self.write("tests/test_core.py", "from pkg.core import public as clean\n\ndef test_space():\n    assert clean(' a ') == 'a'\n")
        return build(self.root)

    def test_import_alias_and_transitive_evidence(self):
        data = self.fixture()
        result = related_tests(data, "normalize")
        self.assertEqual(len(result["links"]), 1)
        link = result["links"][0]
        self.assertEqual(link["call_path"], ["tests/test_core.py::test_space", "src/pkg/core.py::public", "src/pkg/core.py::normalize"])
        self.assertEqual(link["evidence"], "structural")
        self.assertIn("return x.strip()", explain_link(data, "normalize", "test_space")["function"]["text"])

    def test_stale_on_edit_add_delete(self):
        for change in ("edit", "add", "delete"):
            with self.subTest(change=change):
                data = self.fixture()
                save(self.root, data)
                self.assertEqual(load(self.root)["snapshot"], data["snapshot"])
                if change == "edit":
                    self.write("src/pkg/core.py", "def normalize(x):\n    return x\n")
                elif change == "add":
                    self.write("new.py", "x = 1\n")
                else:
                    (self.root / "src/pkg/core.py").unlink()
                with self.assertRaisesRegex(ValueError, "stale"):
                    load(self.root)
                if (self.root / "new.py").exists():
                    (self.root / "new.py").unlink()

    def test_shadowed_import_does_not_create_link(self):
        self.fixture()
        self.write("tests/test_core.py", "from pkg.core import public as clean\n\ndef test_other(clean):\n    clean('a')\n\ndef test_local():\n    clean = lambda x: x\n    clean('a')\n")
        self.assertEqual(build(self.root)["links"], [])

    def test_relative_import_and_module_alias(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/core.py", "def work():\n    return 1\n")
        self.write("pkg/api.py", "from .core import work\n\ndef go():\n    return work()\n")
        self.write("tests/test_api.py", "import pkg.api as api\n\ndef test_api():\n    assert api.go() == 1\n")
        self.assertEqual(len(related_tests(build(self.root), "work")["links"]), 1)

    def test_nested_function_is_not_executed_by_definition(self):
        self.write("core.py", "def work():\n    pass\n")
        self.write("test_core.py", "from core import work\n\ndef test_no_call():\n    def unused():\n        work()\n")
        self.assertEqual(build(self.root)["links"], [])

    def test_default_expression_is_not_a_test_body_call(self):
        self.write("core.py", "def work():\n    return 1\n")
        self.write("test_core.py", "from core import work\n\ndef test_other(value=work()):\n    assert value == 1\n")
        self.assertEqual(build(self.root)["links"], [])

    def test_definition_replaces_import_in_module_order(self):
        self.write("other.py", "def work():\n    return 'other'\n")
        self.write("core.py", "from other import work\n\ndef work():\n    return 'local'\n\ndef public():\n    return work()\n")
        self.write("test_core.py", "from core import public\n\ndef test_public():\n    assert public() == 'local'\n")
        data = build(self.root)
        self.assertEqual(len(related_tests(data, "core.py::work")["links"]), 1)
        self.assertEqual(related_tests(data, "other.py::work")["links"], [])
        self.write("core.py", "def work():\n    return 'local'\n\nfrom other import work\n\ndef public():\n    return work()\n")
        data = build(self.root)
        self.assertEqual(len(related_tests(data, "other.py::work")["links"]), 1)

    def test_nested_definition_shadows_import(self):
        self.write("core.py", "def work():\n    return 1\n")
        self.write("test_core.py", "from core import work\n\ndef test_local():\n    def work():\n        return 2\n    assert work() == 2\n")
        self.assertEqual(build(self.root)["links"], [])

    def test_malformed_map_reports_json_error(self):
        data = self.fixture()
        save(self.root, data)
        for malformed in ([], {"schema": 1}, {**data, "symbols": {"bad": []}}, {**data, "enrichment": []},
                          {**data, "links": [{"id": "x"}]}):
            with self.subTest(malformed=type(malformed).__name__):
                (self.root / ".jev-map/map.json").write_text(json.dumps(malformed))
                run = subprocess.run([sys.executable, "-m", "jev_map", "--repo", str(self.root), "symbols"], capture_output=True, text=True)
                self.assertEqual(run.returncode, 2)
                self.assertIn("Malformed map", json.loads(run.stderr)["error"])

    def test_symlinks_ignored_and_no_execution(self):
        self.write("core.py", "raise RuntimeError('do not execute')\n\ndef work():\n    pass\n")
        (self.root / "outside.py").symlink_to(Path(__file__))
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        data = build(self.root)
        self.assertEqual(set(data["files"]), {"core.py"})
        (self.root / ".jev-map").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            save(self.root, data)

    def test_gitignored_and_deleted_files(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/key.py", "SECRET = 'fixture'\n")
        self.write("deleted.py", "x = 1\n")
        subprocess.run(["git", "-C", str(self.root), "add", "deleted.py"], check=True)
        (self.root / "deleted.py").unlink()
        self.write("ok.py", "def work():\n    return 1\n")
        self.assertEqual(set(build(self.root)["files"]), {"ok.py"})

    def test_syntax_error_is_visible(self):
        self.write("bad.py", "def broken(\n")
        self.assertEqual(build(self.root)["diagnostics"], [{"path": "bad.py", "reason": "SyntaxError"}])

    def test_ambiguous_symbol_requires_identifier(self):
        self.write("a.py", "def work():\n    pass\n")
        self.write("b.py", "def work():\n    pass\n")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            related_tests(build(self.root), "work")

    def test_cli_round_trip(self):
        self.fixture()
        for args in (["refresh"], ["related-tests", "normalize"], ["explain-link", "normalize", "test_space"]):
            run = subprocess.run([sys.executable, "-m", "jev_map", "--repo", str(self.root), *args], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIsInstance(json.loads(run.stdout), dict)


if __name__ == "__main__":
    unittest.main()
