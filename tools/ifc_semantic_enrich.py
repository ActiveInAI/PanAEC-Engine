# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
"""ifc_semantic_enrich.py — 按 SJG 157 给 IFC 构件赋真实类型与分类

两种用法:
1. 写出器(我方控制的 3DM/SKP→IFC):用 pick_ifc_entity_type 在创建构件时按名称
   选真实 IFC 实体类型(命中则 IfcColumn/IfcBeam/...,否则 IfcBuildingElementProxy);
   再用 attach_sjg_classifications 批量写 IfcClassificationReference(SJG 157)。
2. 后处理(外部转换器输出,如 RVT2IFC):upgrade_proxies_and_classify 对整模型
   按名称分类——为命中元素加 SJG 分类关联;IfcBuildingElementProxy 若命中具体类型
   则重建为真实类型(保留几何/放置/属性/材料关联)。

依赖 sjg157_classify(同目录)。无匹配时不写任何分类,不伪造。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sjg157_classify import (  # noqa: E402
    Sjg157Match,
    classify_by_ifc_class,
    classify_sjg157,
)

import ifcopenshell  # noqa: E402

SJG_STANDARD = "SJG 157-2024 建筑工程信息模型语义字典标准"
SJG_SOURCE = "深圳市住房和建设局"

# 仅这些 IFC4 实体可作为模型单元直接实例化(SJG 字典里出现的具体构件类)。
# IfcElement/IfcBuildingElement 等抽象类不直接实例化,退回 Proxy。
_CONCRETE_IFC_TYPES = {
    "IfcColumn", "IfcBeam", "IfcMember", "IfcWall", "IfcWallStandardCase",
    "IfcSlab", "IfcPlate", "IfcDoor", "IfcWindow", "IfcStair", "IfcStairFlight",
    "IfcRamp", "IfcRailing", "IfcRoof", "IfcFooting", "IfcPile",
    "IfcElementAssembly", "IfcCurtainWall", "IfcCovering",
}


def classify_component(*names: Optional[str]) -> Optional[Sjg157Match]:
    """按构件名分类(名称命中优先)。供写出器在创建前判定类型。"""
    return classify_sjg157(*names)


def pick_ifc_entity_type(match: Optional[Sjg157Match]) -> str:
    """SJG 命中且为可实例化的具体类型则用之,否则退回 IfcBuildingElementProxy。"""
    if match and match["ifc"] in _CONCRETE_IFC_TYPES:
        return match["ifc"]
    return "IfcBuildingElementProxy"


def attach_sjg_classifications(
    model: ifcopenshell.file,
    classified: list[tuple[ifcopenshell.entity_instance, Sjg157Match]],
) -> int:
    """为已分类的构件批量写 IfcClassificationReference + IfcRelAssociatesClassification。

    同一 SJG 编码共享一个 reference 与一个关联关系(IFC 规范允许一个关系关联多元素)。
    返回写出的分类编码数。
    """
    if not classified:
        return 0
    guid = ifcopenshell.guid.new
    classification = model.create_entity(
        "IfcClassification",
        Source=SJG_SOURCE,
        Edition="2024",
        Name=SJG_STANDARD,
    )
    by_code: dict[str, dict] = {}
    for element, match in classified:
        entry = by_code.setdefault(
            match["code"],
            {"category": match["category"], "elements": []},
        )
        entry["elements"].append(element)

    for code, entry in by_code.items():
        reference = model.create_entity(
            "IfcClassificationReference",
            Location=None,
            Identification=code,
            Name=entry["category"],
            ReferencedSource=classification,
        )
        model.create_entity(
            "IfcRelAssociatesClassification",
            GlobalId=guid(),
            Name="SJG157",
            RelatedObjects=entry["elements"],
            RelatingClassification=reference,
        )
    return len(by_code)


def upgrade_proxies_and_classify(model: ifcopenshell.file) -> dict:
    """后处理:按名称给所有 IfcElement 加 SJG 分类;命中具体类型的 Proxy 重建为真实类型。

    返回统计 {classified, upgraded, byCode}。用于外部转换器(RVT2IFC)输出增补。
    """
    classified: list[tuple[ifcopenshell.entity_instance, Sjg157Match]] = []
    upgraded = 0
    # 先收集需升级的 Proxy(避免遍历中修改)
    proxies = list(model.by_type("IfcBuildingElementProxy"))
    for proxy in proxies:
        match = classify_sjg157(
            getattr(proxy, "Name", None), getattr(proxy, "ObjectType", None)
        )
        target = pick_ifc_entity_type(match)
        if match and target != "IfcBuildingElementProxy":
            new_el = _recreate_as(model, proxy, target)
            if new_el is not None:
                classified.append((new_el, match))
                upgraded += 1
                continue
        if match:
            classified.append((proxy, match))

    # 其余已是具体类型的构件:按名称或 IFC 类型补分类
    for element in model.by_type("IfcElement"):
        if element.is_a("IfcBuildingElementProxy"):
            continue
        if any(element is e for e, _ in classified):
            continue
        match = classify_sjg157(
            getattr(element, "Name", None), getattr(element, "ObjectType", None)
        ) or classify_by_ifc_class(element.is_a())
        if match:
            classified.append((element, match))

    code_count = attach_sjg_classifications(model, classified)
    return {
        "classified": len(classified),
        "upgraded": upgraded,
        "codeCount": code_count,
    }


def _recreate_as(
    model: ifcopenshell.file,
    proxy: ifcopenshell.entity_instance,
    target_type: str,
) -> Optional[ifcopenshell.entity_instance]:
    """把 IfcBuildingElementProxy 重建为 target_type,迁移共有产品属性与关联关系。

    保守迁移:GlobalId/Name/Description/ObjectType/ObjectPlacement/Representation/Tag;
    并把指向 proxy 的 IfcRelContainedInSpatialStructure / IfcRelAssociates*
    指回新实体。失败返回 None(调用方保留原 Proxy + 分类)。
    """
    try:
        attrs = {
            "GlobalId": proxy.GlobalId,
            "OwnerHistory": getattr(proxy, "OwnerHistory", None),
            "Name": getattr(proxy, "Name", None),
            "Description": getattr(proxy, "Description", None),
            "ObjectType": getattr(proxy, "ObjectType", None),
            "ObjectPlacement": getattr(proxy, "ObjectPlacement", None),
            "Representation": getattr(proxy, "Representation", None),
            "Tag": getattr(proxy, "Tag", None),
        }
        new_el = model.create_entity(target_type, **attrs)
        # 把所有引用 proxy 的关系/关联改指向新实体
        for ref in model.get_inverse(proxy):
            for attr_name in ("RelatedObjects", "RelatedElements"):
                if hasattr(ref, attr_name):
                    current = getattr(ref, attr_name)
                    if current and proxy in current:
                        setattr(
                            ref,
                            attr_name,
                            [new_el if x is proxy else x for x in current],
                        )
        model.remove(proxy)
        return new_el
    except Exception:
        return None
