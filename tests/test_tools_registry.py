# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""Structural checks for registry/tools.json (stdlib only, CI-safe)."""

import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry" / "tools.json"

ROUTES = {"direct", "adapter", "licensed-sidecar"}


class ToolsRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_engine_identity(self):
        engine = self.doc["engine"]
        self.assertEqual(engine["name"], "PanAEC Engine")
        self.assertEqual(engine["spdxLicense"], "AGPL-3.0-only")
        self.assertEqual(engine["copyrightOwner"], "潘永胜")

    def test_tool_entries_complete_and_unique(self):
        tools = self.doc["tools"]
        self.assertGreaterEqual(len(tools), 1)
        ids = [t["id"] for t in tools]
        self.assertEqual(len(ids), len(set(ids)), "duplicate tool ids")
        commands = [t["command"] for t in tools]
        self.assertEqual(len(commands), len(set(commands)), "duplicate commands")
        for tool in tools:
            for key in ("id", "command", "implementation", "inputs", "outputs", "route", "runtime", "summary"):
                self.assertIn(key, tool, f"{tool.get('id')}: missing {key}")
            self.assertIn(tool["route"], ROUTES, tool["id"])

    def test_registered_files_exist(self):
        for tool in self.doc["tools"]:
            command = ROOT / tool["command"]
            implementation = ROOT / tool["implementation"]
            self.assertTrue(command.is_file(), f"missing {tool['command']}")
            self.assertTrue(
                os.access(command, os.X_OK), f"not executable: {tool['command']}"
            )
            self.assertTrue(implementation.is_file(), f"missing {tool['implementation']}")

    def test_every_shipped_cli_is_registered(self):
        shipped = {
            f"tools/{p.name}" for p in (ROOT / "tools").glob("panaec-*")
        }
        registered = {t["command"] for t in self.doc["tools"]}
        self.assertEqual(shipped, registered)

    def test_data_entries_exist(self):
        for entry in self.doc.get("data", []):
            self.assertTrue((ROOT / entry["path"]).is_file(), f"missing {entry['path']}")
            classifier = entry.get("classifier")
            if classifier:
                self.assertTrue((ROOT / classifier).is_file(), f"missing {classifier}")


if __name__ == "__main__":
    unittest.main()
