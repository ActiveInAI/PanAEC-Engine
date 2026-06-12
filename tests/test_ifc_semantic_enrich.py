# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""IFC semantic enrichment tests.

Requires ifcopenshell; skipped automatically when it is not installed so the
registry-only CI environment stays green.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

try:
    import ifcopenshell
except ImportError:  # pragma: no cover - CI has no ifcopenshell
    ifcopenshell = None

if ifcopenshell is not None:
    from ifc_semantic_enrich import (  # noqa: E402
        attach_sjg_classifications,
        classify_component,
        pick_ifc_entity_type,
        upgrade_proxies_and_classify,
    )


@unittest.skipIf(ifcopenshell is None, "ifcopenshell not installed")
class IfcSemanticEnrichTest(unittest.TestCase):
    @staticmethod
    def _empty_model():
        return ifcopenshell.file(schema="IFC4")

    def test_pick_type_concrete_vs_proxy(self):
        self.assertEqual(pick_ifc_entity_type(classify_component("钢柱-1")), "IfcColumn")
        self.assertEqual(pick_ifc_entity_type(classify_component("钢梁")), "IfcBeam")
        self.assertEqual(
            pick_ifc_entity_type(classify_component("无关物")), "IfcBuildingElementProxy"
        )

    def test_attach_classifications_groups_by_code(self):
        m = self._empty_model()
        guid = ifcopenshell.guid.new
        a = m.create_entity("IfcColumn", GlobalId=guid(), Name="钢柱-1")
        b = m.create_entity("IfcColumn", GlobalId=guid(), Name="钢柱-2")
        c = m.create_entity("IfcBeam", GlobalId=guid(), Name="钢梁-1")
        classified = [
            (a, classify_component("钢柱-1")),
            (b, classify_component("钢柱-2")),
            (c, classify_component("钢梁-1")),
        ]
        code_count = attach_sjg_classifications(m, classified)
        self.assertEqual(code_count, 2)  # 钢柱 + 钢梁
        refs = {r.Identification for r in m.by_type("IfcClassificationReference")}
        self.assertIn("30-03.95.03", refs)
        self.assertIn("30-03.95.09", refs)
        self.assertTrue(m.by_type("IfcClassification")[0].Name.startswith("SJG 157"))

    def test_upgrade_proxy_to_real_type(self):
        m = self._empty_model()
        guid = ifcopenshell.guid.new
        # 一个名为"钢柱"的 Proxy 应被升级为 IfcColumn 并保留 GlobalId
        proxy = m.create_entity(
            "IfcBuildingElementProxy", GlobalId=guid(), Name="钢柱-X1"
        )
        keep_gid = proxy.GlobalId
        # 一个无法分类的 Proxy 应保持 Proxy
        m.create_entity("IfcBuildingElementProxy", GlobalId=guid(), Name="无关物体")
        stats = upgrade_proxies_and_classify(m)
        self.assertEqual(stats["upgraded"], 1)
        cols = m.by_type("IfcColumn")
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].GlobalId, keep_gid)
        self.assertEqual(len(m.by_type("IfcBuildingElementProxy")), 1)
        self.assertGreaterEqual(stats["classified"], 1)


if __name__ == "__main__":
    unittest.main()
