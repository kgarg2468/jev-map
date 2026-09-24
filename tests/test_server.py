import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_map.server import MapTools
from support import TemporaryRepository


class ToolTest(TemporaryRepository):
    def test_session_cap_covers_multiple_refreshes(self):
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.strip()\n")
        self.write("test_core.py", "from core import Cleaner\ndef test_normalize():\n    assert Cleaner().normalize(' a ') == 'a'\n")
        tools = MapTools(self.root, jev=True, max_calls=1)
        def reply(payload):
            return {"answers": {key: {"noul": 0.9} for key in payload["questions"]}}
        with patch("jev_map.server.JevClient", return_value=reply):
            first = tools.refresh_map()
            self.assertEqual(first["remaining_session_calls"], 0)
            self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.lstrip()\n")
            second = tools.refresh_map()
        self.assertEqual(second["enrichment"]["requests"], 0)
        self.assertEqual(second["enrichment"]["skipped_budget"], 1)

    def test_on_demand_shares_session_cap_and_requires_opt_in(self):
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.strip()\n")
        self.write("test_core.py", "from core import Cleaner\ndef test_normalize():\n    assert Cleaner().normalize(' a ') == 'a'\n")
        local = MapTools(self.root)
        local.refresh_map()
        with self.assertRaisesRegex(ValueError, "--jev"):
            local.enrich_symbol("normalize")
        remote = MapTools(self.root, jev=True, max_calls=1)
        def reply(payload):
            return {"answers": {key: {"noul": 0.9} for key in payload["questions"]}}
        with patch("jev_map.server.JevClient", return_value=reply):
            first = remote.enrich_symbol("normalize")
            second = remote.enrich_symbol("normalize")
        self.assertEqual(first["remaining_session_calls"], 0)
        self.assertEqual(second["remaining_session_calls"], 0)
        self.assertEqual(second["enrichment"]["cache_hits"], 1)

    def test_on_demand_rejects_source_change_during_provider_call(self):
        self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.strip()\n")
        self.write("test_core.py", "from core import Cleaner\ndef test_normalize():\n    assert Cleaner().normalize(' a ') == 'a'\n")
        MapTools(self.root).refresh_map()
        tools = MapTools(self.root, jev=True, max_calls=1)
        original = (self.root / ".jev-map/map.json").read_text()
        def reply(payload):
            self.write("core.py", "class Cleaner:\n    def normalize(self, text):\n        return text.lstrip()\n")
            return {"answers": {key: {"noul": 0.9} for key in payload["questions"]}}
        with patch("jev_map.server.JevClient", return_value=reply):
            with self.assertRaisesRegex(ValueError, "stale"):
                tools.enrich_symbol("normalize")
        self.assertEqual((self.root / ".jev-map/map.json").read_text(), original)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP dependency not installed")
class MCPIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_and_staleness(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "core.py").write_text("def clean(text):\n    return text.strip()\n")
            (root / "test_core.py").write_text("from core import clean\ndef test_clean():\n    assert clean(' a ') == 'a'\n")
            parameters = StdioServerParameters(command=sys.executable, args=["-m", "jev_map", "--repo", str(root), "serve"])
            async with asyncio.timeout(30):
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        self.assertEqual({tool.name for tool in listed.tools}, {"related_tests", "explain_link", "refresh_map", "enrich_symbol"})
                        refresh = await session.call_tool("refresh_map", {})
                        self.assertFalse(refresh.isError)
                        linked = await session.call_tool("related_tests", {"symbol": "clean"})
                        self.assertFalse(linked.isError)
                        self.assertEqual(len(json.loads(linked.content[0].text)["links"]), 1)
                        explained = await session.call_tool("explain_link", {"function": "clean", "test": "test_clean"})
                        self.assertFalse(explained.isError)
                        (root / "core.py").write_text("def clean(text):\n    return text\n")
                        stale = await session.call_tool("related_tests", {"symbol": "clean"})
                        self.assertTrue(stale.isError)
                        self.assertIn("stale", stale.content[0].text)
