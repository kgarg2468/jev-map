"""Execute only the project's original mini-repo tests, recording actual function calls."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "examples/mini_repo"
sys.path.insert(0, str(ROOT))
import test_text_ops  # noqa: E402


def main():
    relationships = []
    outcomes = []
    for name in unittest.defaultTestLoader.getTestCaseNames(test_text_ops.TextTests):
        observed = set()
        def profile(frame, event, arg):
            if event == "call" and Path(frame.f_code.co_filename).resolve() == ROOT / "text_ops.py":
                observed.add(frame.f_code.co_qualname)
        case = test_text_ops.TextTests(name)
        result = unittest.TestResult()
        sys.setprofile(profile)
        try:
            case.run(result)
        finally:
            sys.setprofile(None)
        outcomes.append({"test": name, "passed": result.wasSuccessful(), "runs": result.testsRun})
        relationships.extend({"function": f"text_ops.py::{function}", "test": f"test_text_ops.py::TextTests.{name}"}
                             for function in sorted(observed))
    print(json.dumps({"relationships": relationships, "outcomes": outcomes}))
    return 0 if all(outcome["passed"] for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
