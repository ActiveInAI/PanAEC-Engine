# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

import json
import unittest

from panaec_engine import COPYRIGHT_OWNER, ENGINE_NAME, SPDX_LICENSE
from panaec_engine.capabilities import (
    FORMAT_CAPABILITY_IDS,
    REGISTRY_PATH,
    capability_id_for_extension,
    capability_id_for_filename,
    capability_ids,
)


class CapabilityTests(unittest.TestCase):
    def test_identity_constants(self) -> None:
        self.assertEqual(ENGINE_NAME, "PanAEC Engine")
        self.assertEqual(SPDX_LICENSE, "AGPL-3.0-only")
        self.assertEqual(COPYRIGHT_OWNER, "潘永胜")

    def test_registry_covers_required_domains(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
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

    def test_registry_covers_ofd_odf_raw_and_markup_formats(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        formats_by_id = {
            capability["id"]: set(capability["formats"])
            for capability in registry["capabilities"]
        }
        self.assertIn("ofd", formats_by_id["pdf"])
        self.assertTrue({"odt", "ods", "odp", "odg", "odb"}.issubset(formats_by_id["office"]))
        self.assertTrue({"dng", "raw"}.issubset(formats_by_id["images"]))
        self.assertTrue(
            {
                "usd",
                "usda",
                "usdc",
                "usdz",
                "3dtiles",
                "tileset.json",
                "b3dm",
                "i3dm",
                "pnts",
                "cmpt",
            }.issubset(formats_by_id["bim_openbim"])
        )
        self.assertTrue({"gltf", "glb"}.issubset(formats_by_id["cad_geometry"]))
        self.assertTrue(
            {"xml", "html", "htm", "xhtml", "txt"}.issubset(
                formats_by_id["code_programming"]
            )
        )

    def test_requested_extensions_route_to_expected_capability(self) -> None:
        expected = {
            ".odt": "office",
            ".ods": "office",
            ".odp": "office",
            ".odg": "office",
            ".odb": "office",
            ".dng": "images",
            ".raw": "images",
            ".ofd": "pdf",
            ".usd": "bim_openbim",
            ".usda": "bim_openbim",
            ".usdc": "bim_openbim",
            ".usdz": "bim_openbim",
            ".3dtiles": "bim_openbim",
            ".b3dm": "bim_openbim",
            ".i3dm": "bim_openbim",
            ".pnts": "bim_openbim",
            ".cmpt": "bim_openbim",
            ".gltf": "cad_geometry",
            ".glb": "cad_geometry",
            ".xml": "code_programming",
            ".html": "code_programming",
            ".htm": "code_programming",
            ".xhtml": "code_programming",
            ".txt": "code_programming",
        }
        for extension, capability_id in expected.items():
            with self.subTest(extension=extension):
                self.assertEqual(capability_id_for_extension(extension), capability_id)

    def test_compound_filenames_route_to_expected_capability(self) -> None:
        expected = {
            "tileset.json": "bim_openbim",
            "city/tileset.json": "bim_openbim",
            "city/TILESET.JSON": "bim_openbim",
            "data.json": "code_programming",
            "model.glb": "cad_geometry",
            "source/index.xhtml": "code_programming",
            "notes.txt": "code_programming",
        }
        for filename, capability_id in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(capability_id_for_filename(filename), capability_id)

    def test_code_format_map_matches_registry_formats(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        expected = {
            extension: capability["id"]
            for capability in registry["capabilities"]
            for extension in capability["formats"]
        }
        self.assertEqual(expected, FORMAT_CAPABILITY_IDS)

    def test_registry_has_no_duplicate_formats(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        formats = [
            extension
            for capability in registry["capabilities"]
            for extension in capability["formats"]
        ]
        self.assertEqual(len(formats), len(set(formats)))


if __name__ == "__main__":
    unittest.main()
