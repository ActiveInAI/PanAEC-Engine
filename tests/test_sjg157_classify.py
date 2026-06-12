# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""SJG 157-2024 semantic dictionary classifier tests (pure stdlib, CI-safe)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from sjg157_classify import classify_by_ifc_class, classify_sjg157  # noqa: E402


class Sjg157ClassifyTest(unittest.TestCase):
    def test_steel_column(self):
        m = classify_sjg157("钢柱-0001")
        self.assertIsNotNone(m)
        self.assertEqual(m["ifc"], "IfcColumn")
        self.assertEqual(m["code"], "30-03.95.03")

    def test_numbered_concrete_column(self):
        m = classify_sjg157("框架柱KZ3")
        self.assertIsNotNone(m)
        self.assertEqual(m["ifc"], "IfcColumn")
        self.assertEqual(m["category"], "混凝土结构柱")

    def test_specific_beats_generic_raft(self):
        # 筏板基础 不应被泛化的"板"抢占
        m = classify_sjg157("筏板基础")
        self.assertIsNotNone(m)
        self.assertEqual(m["ifc"], "IfcFooting")

    def test_layer_prefix_stripped(self):
        m = classify_sjg157("S-钢支撑")
        self.assertIsNotNone(m)
        self.assertEqual(m["ifc"], "IfcMember")

    def test_gz_code_prefix_kept(self):
        m = classify_sjg157("GZ-1")
        self.assertIsNotNone(m)
        self.assertEqual(m["ifc"], "IfcColumn")

    def test_unrelated_unclassified(self):
        self.assertIsNone(classify_sjg157("XYZ无关层"))
        self.assertIsNone(classify_sjg157(""))
        self.assertIsNone(classify_sjg157(None))

    def test_ifc_class_default(self):
        m = classify_by_ifc_class("IfcBeam")
        self.assertIsNotNone(m)
        self.assertEqual(m["category"], "混凝土构造梁")
        self.assertIsNone(classify_by_ifc_class("IfcUnknownXYZ"))

    def test_name_first_then_ifc_fallback(self):
        # 名称命中优先
        self.assertEqual(classify_sjg157("钢梁")["code"], "30-03.95.09")


if __name__ == "__main__":
    unittest.main()
