import copy
import json
import math
import unittest

from jev_map.enrich import enrich
from jev_map.index import build
from jev_map.provider import ProviderError, validate_response
from support import TemporaryRepository


class EnrichmentTest(TemporaryRepository):
    def fixture(self):
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.strip()\n")
        self.write("test_core.py", "from core import Cleaner\n\ndef test_normalize():\n    cleaner = Cleaner()\n    assert cleaner.normalize(' a ') == 'a'\n")
        return build(self.root)

    @staticmethod
    def client(payload):
        return {"answers": {key: {"noul": 0.9} for key in payload["questions"]}, "usage": {"input_tokens": 100}}

    def test_inferred_link_has_exact_receipt(self):
        data = enrich(self.root, self.fixture(), self.client)
        links = [link for link in data["links"] if link["evidence"] == "inferred"]
        self.assertEqual(len(links), 1)
        receipt = json.loads((self.root / ".jev-map" / links[0]["receipt"]).read_text())
        self.assertEqual(receipt["request_sha256"], links[0]["request_sha256"])
        self.assertEqual(data["enrichment"]["stats"]["known_input_tokens"], 100)

    def test_cache_reuse_and_source_change(self):
        data = self.fixture()
        first = enrich(self.root, copy.deepcopy(data), self.client)
        second = enrich(self.root, copy.deepcopy(data), self.client)
        self.assertEqual(first["enrichment"]["stats"]["requests"], 1)
        self.assertEqual(second["enrichment"]["stats"]["requests"], 0)
        self.assertEqual(second["enrichment"]["stats"]["cache_hits"], 1)
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.lstrip()\n")
        third = enrich(self.root, build(self.root), self.client)
        self.assertEqual(third["enrichment"]["stats"]["requests"], 1)

    def test_model_change_invalidates_request_cache(self):
        data = self.fixture()
        enrich(self.root, copy.deepcopy(data), self.client, model="fixture-v1")
        result = enrich(self.root, copy.deepcopy(data), self.client, model="fixture-v2")
        self.assertEqual(result["enrichment"]["stats"]["requests"], 1)

    def test_errors_preserve_structural_links(self):
        data = self.fixture()
        data["links"].append({"id": "fixture", "evidence": "structural", "function": "other", "test": "other"})
        def broken(payload):
            raise ProviderError("Jev HTTP 503; no automatic retry")
        result = enrich(self.root, data, broken)
        self.assertEqual(len(result["links"]), 1)
        self.assertEqual(result["enrichment"]["stats"]["errors"], 1)
        self.assertEqual(len(list((self.root / ".jev-map/receipts").glob("*.json"))), 1)

    def test_budget_and_rejected_scores(self):
        result = enrich(self.root, self.fixture(), self.client, max_calls=0)
        self.assertEqual(result["enrichment"]["stats"]["skipped_budget"], 1)
        result = enrich(self.root, self.fixture(), self.client, threshold=0.95)
        self.assertEqual(result["links"], [])
        self.assertEqual(len(result["enrichment"]["decisions"]), 1)

    def test_nan_bool_and_missing_answers_rejected(self):
        payload = {"questions": {"b0": {}}}
        for response in ({}, {"answers": {"b0": {"noul": math.nan}}},
                         {"answers": {"b0": {"noul": True}}}, {"answers": {"b0": {"noul": 2}}}):
            with self.assertRaises(ProviderError):
                validate_response(payload, response)

    def test_corrupt_cache_is_not_trusted(self):
        result = enrich(self.root, self.fixture(), self.client)
        receipt = self.root / ".jev-map" / result["links"][0]["receipt"]
        corrupted = json.loads(receipt.read_text())
        corrupted["response"]["answers"]["b0"]["noul"] = 0.1
        receipt.write_text(json.dumps(corrupted))
        result = enrich(self.root, self.fixture(), self.client)
        self.assertEqual(result["enrichment"]["stats"]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
