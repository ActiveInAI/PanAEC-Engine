# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
"""sjg157_classify.py — SJG 157-2024 语义字典分类器(供 BOM/IFC worker 复用)

按构件中文名/图层名子串匹配,返回 IFC 实体类型 + SJG 构件编码 + 规范类目名。
规则按特异性从高到低排序,首个命中即采用。数据源:
06-workers/data/sjg157_semantic_dictionary.json(单一真源,前端同源)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, TypedDict

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sjg157_semantic_dictionary.json"


class Sjg157Match(TypedDict):
    ifc: str
    code: str
    category: str
    matchedKeyword: str


_rules: Optional[list[dict]] = None
_ifc_defaults: Optional[dict] = None


def _load_doc() -> dict:
    global _rules, _ifc_defaults
    if _rules is None:
        try:
            doc = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
        _rules = doc.get("rules", [])
        _ifc_defaults = doc.get("ifcDefaults", {})
    return {"rules": _rules, "ifcDefaults": _ifc_defaults}


def _load_rules() -> list[dict]:
    return _load_doc()["rules"]


def classify_by_ifc_class(ifc_class: Optional[str]) -> Optional[Sjg157Match]:
    """按 IFC 实体类型给默认 SJG 分类(无名构件兜底)。"""
    if not ifc_class:
        return None
    default = (_load_doc()["ifcDefaults"] or {}).get(ifc_class)
    if not default:
        return None
    return {
        "ifc": ifc_class,
        "code": default["code"],
        "category": default["category"],
        "matchedKeyword": f"<ifc:{ifc_class}>",
    }


def _normalize(text: str) -> str:
    # 去掉常见前缀噪声(标准号、图层前缀如 S-、BS-、SH-)并小写以便英文关键词匹配
    cleaned = re.sub(r"^[A-Za-z]{1,4}[-_]", "", text.strip())
    return cleaned.lower()


def classify_sjg157(*texts: Optional[str]) -> Optional[Sjg157Match]:
    """对一个或多个候选文本(构件名/对象类型/图层名)做 SJG 157 分类。

    任一文本命中即返回;多文本时按传入顺序优先。返回 None 表示无法分类
    (调用方应如实标注"未分类",不得伪造)。
    """
    rules = _load_rules()
    for raw in texts:
        if not raw:
            continue
        # 同时匹配原始小写与去前缀形式(图层前缀 S-/BS- 等噪声 vs GZ-1 这类编号)
        candidates = {str(raw).strip().lower(), _normalize(str(raw))}
        candidates.discard("")
        if not candidates:
            continue
        for rule in rules:
            for kw in rule.get("keywords", []):
                if not kw:
                    continue
                kwl = kw.lower()
                if any(kwl in hay for hay in candidates):
                    return {
                        "ifc": rule["ifc"],
                        "code": rule["code"],
                        "category": rule["category"],
                        "matchedKeyword": kw,
                    }
    return None
