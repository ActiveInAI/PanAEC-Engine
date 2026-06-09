# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

import json
import unittest
from pathlib import Path

from panaec_engine import COPYRIGHT_OWNER, ENGINE_NAME, SPDX_LICENSE
from panaec_engine.capabilities import capability_ids


class CapabilityTests(unittest.TestCase):
    def test_identity_constants(self) -> None:
        self.assertEqual(ENGINE_NAME, "PanAEC Engine")
        self.assertEqual(SPDX_LICENSE, "AGPL-3.0-only")
        self.assertEqual(COPYRIGHT_OWNER, "潘永胜")

    def test_registry_covers_required_domains(self) -> None:
        registry = json.loads(Path("registry/capabilities.json").read_text())
        ids = {capability["id"] for capability in registry["capabilities"]}
        self.assertEqual(set(capability_ids()), ids)
        self.assertEqual(
            {
                "bim_openbim",
                "cad_geometry",
                "pdf",
                "office",
                "audio",
                "video",
                "images",
                "archives",
                "code_programming",
            },
            ids,
        )

    def test_registry_covers_ofd_odf_and_raw_formats(self) -> None:
        registry = json.loads(Path("registry/capabilities.json").read_text())
        formats_by_id = {
            capability["id"]: set(capability["formats"])
            for capability in registry["capabilities"]
        }
        self.assertIn("ofd", formats_by_id["pdf"])
        self.assertTrue({"odt", "ods", "odp", "odg", "odb"}.issubset(formats_by_id["office"]))
        self.assertTrue({"dng", "raw"}.issubset(formats_by_id["images"]))


if __name__ == "__main__":
    unittest.main()
