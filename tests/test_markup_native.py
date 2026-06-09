# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

import tempfile
import unittest
from pathlib import Path

from panaec_engine.markup_native import build_markup_native_manifest


class MarkupNativeTests(unittest.TestCase):
    def test_reads_xml_source_without_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "model.xml"
            source.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<root>
  <title>工程配置</title>
  <item href="spec.xml">A</item>
</root>
""",
                encoding="utf-8",
            )

            manifest = build_markup_native_manifest(source)

        self.assertEqual(manifest.schema, "panaec.markup_native_manifest.v1")
        self.assertEqual(manifest.source_format, "xml")
        self.assertEqual(manifest.viewer, "source_xml_native_viewer")
        self.assertEqual(manifest.derivative_roles, ())
        self.assertEqual(manifest.root_tag, "root")
        self.assertEqual(manifest.element_count, 3)
        self.assertEqual(manifest.title, "工程配置")
        self.assertEqual(manifest.links, ("spec.xml",))
        self.assertFalse(manifest.native_adapter_required)

    def test_reads_html_source_without_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "index.html"
            source.write_text(
                """<!doctype html>
<html>
  <head><title>PanAEC</title><link href="site.css"></head>
  <body><img src="hero.png"><a href="/docs">Docs</a></body>
</html>
""",
                encoding="utf-8",
            )

            manifest = build_markup_native_manifest(source)

        self.assertEqual(manifest.source_format, "html")
        self.assertEqual(manifest.viewer, "source_html_native_viewer")
        self.assertEqual(manifest.root_tag, "html")
        self.assertEqual(manifest.title, "PanAEC")
        self.assertEqual(manifest.links, ("site.css", "hero.png", "/docs"))
        self.assertEqual(manifest.derivative_roles, ())

    def test_reads_plain_text_source_without_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "notes.txt"
            source.write_text("第一行\n第二行\n", encoding="utf-8")

            manifest = build_markup_native_manifest(source)

        self.assertEqual(manifest.source_format, "txt")
        self.assertEqual(manifest.viewer, "source_text_native_viewer")
        self.assertEqual(manifest.line_count, 2)
        self.assertIn("第一行", manifest.text_preview)
        self.assertEqual(manifest.derivative_roles, ())


if __name__ == "__main__":
    unittest.main()
