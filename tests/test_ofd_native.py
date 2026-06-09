# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from panaec_engine.ofd_native import build_ofd_native_manifest


class OfdNativeTests(unittest.TestCase):
    def test_reads_ofd_source_package_without_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "invoice.ofd"
            _write_minimal_ofd(source)

            manifest = build_ofd_native_manifest(source)

        self.assertEqual(manifest.schema, "panaec.ofd_native_manifest.v1")
        self.assertEqual(manifest.source_format, "ofd")
        self.assertEqual(manifest.standard, "GB/T 33190-2016")
        self.assertEqual(manifest.engine, "PanAEC Engine OFD Native")
        self.assertEqual(manifest.viewer, "ofd_native_package_viewer")
        self.assertEqual(manifest.derivative_roles, ())
        self.assertTrue(manifest.native_adapter_required)
        self.assertTrue(manifest.can_render_fixed_layout)
        self.assertEqual(manifest.documents, ("Doc_0/Document.xml",))
        self.assertEqual(manifest.pages, ("Doc_0/Pages/Page_0/Content.xml",))
        self.assertIn("Doc_0/PublicRes.xml", manifest.resources)
        self.assertEqual(len(manifest.rendered_pages), 1)

        page = manifest.rendered_pages[0]
        self.assertEqual(page.width, 210)
        self.assertEqual(page.height, 297)
        self.assertEqual(page.source_path, "Doc_0/Pages/Page_0/Content.xml")
        self.assertEqual(len(page.objects), 2)
        self.assertEqual(page.objects[0].text, "电子发票")
        self.assertEqual(page.objects[0].font_family, "Noto Sans CJK SC")
        self.assertEqual(page.objects[0].fill, "#000000")
        self.assertEqual(page.objects[1].text, "金额 100.00")
        self.assertEqual(page.objects[1].x, 15)
        self.assertEqual(page.objects[1].y, 38)


def _write_minimal_ofd(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "OFD.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ofd:OFD xmlns:ofd="http://www.ofdspec.org/2016">
  <ofd:DocBody>
    <ofd:DocInfo><ofd:DocID>invoice-test</ofd:DocID></ofd:DocInfo>
    <ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot>
  </ofd:DocBody>
</ofd:OFD>
""",
        )
        package.writestr(
            "Doc_0/Document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ofd:Document xmlns:ofd="http://www.ofdspec.org/2016">
  <ofd:CommonData>
    <ofd:PageArea><ofd:PhysicalBox>0 0 210 297</ofd:PhysicalBox></ofd:PageArea>
    <ofd:PublicRes>PublicRes.xml</ofd:PublicRes>
  </ofd:CommonData>
  <ofd:Pages>
    <ofd:Page ID="1" BaseLoc="Pages/Page_0/Content.xml"/>
  </ofd:Pages>
</ofd:Document>
""",
        )
        package.writestr(
            "Doc_0/PublicRes.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ofd:Res xmlns:ofd="http://www.ofdspec.org/2016">
  <ofd:Fonts>
    <ofd:Font ID="5" FontName="Noto Sans CJK SC"/>
  </ofd:Fonts>
</ofd:Res>
""",
        )
        package.writestr(
            "Doc_0/Pages/Page_0/Content.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<ofd:Page xmlns:ofd="http://www.ofdspec.org/2016">
  <ofd:Content>
    <ofd:Layer ID="1">
      <ofd:TextObject ID="T1" Boundary="10 20 80 8" Font="5" Size="5">
        <ofd:FillColor Value="0 0 0"/>
        <ofd:TextCode X="0" Y="5">电子发票</ofd:TextCode>
      </ofd:TextObject>
      <ofd:TextObject ID="T2" Boundary="15 32 60 8" Font="5" Size="4">
        <ofd:FillColor Value="64 64 64"/>
        <ofd:TextCode X="0" Y="6">金额 100.00</ofd:TextCode>
      </ofd:TextObject>
    </ofd:Layer>
  </ofd:Content>
</ofd:Page>
""",
        )
        package.writestr("Doc_0/Res/font.ttf", b"font bytes")


if __name__ == "__main__":
    unittest.main()
