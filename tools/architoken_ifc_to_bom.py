# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""ArchIToken IFC to BOM sidecar.

Walks an IFC model with IfcOpenShell, measures every element's real tessellated
geometry (principal-axis length and cross-section outline via PCA of the mesh
vertices), matches the outline against standard hot-rolled H sections (GB/T
11263) plus any full H{h}x{b}x{t1}x{t2} designations supplied via --section-tag,
and emits a grouped BOM (summary lines + per-element detail).

Weights are theoretical (section area x length x 7850 kg/m3) and only computed
where a full section spec is known — outline-only matches and plates fall back
to honest "missing" markers. The output is review input, not a procurement
document.

Usage:
  architoken_ifc_to_bom.py model.ifc out.json [--csv-dir DIR]
      [--section-tag H306X151X8X12 ...] [--name NAME]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sjg157_classify import classify_by_ifc_class, classify_sjg157  # noqa: E402

STEEL_DENSITY_KG_M3 = 7850.0
SECTION_MATCH_TOLERANCE_MM = 4.0
LENGTH_GROUP_STEP_MM = 10.0

# 常用材料自重（GB 50009-2012 附录A，kg/m3）；仅在 IFC 显式关联材质时使用。
MATERIAL_DENSITY_KG_M3: dict[str, float] = {
    "钢筋混凝土": 2500.0,
    "混凝土": 2400.0,
    "素混凝土": 2300.0,
    "加气混凝土砌块": 625.0,
    "混凝土砌块": 1400.0,
    "烧结普通砖": 1900.0,
    "砖砌体": 1900.0,
    "钢材": 7850.0,
    "钢": 7850.0,
    "木材": 600.0,
    "玻璃": 2560.0,
    "石膏板": 800.0,
    "铝合金": 2700.0,
}

# GB/T 11263 热轧 H 型钢常用规格（外形 -> 完整截面）。
STANDARD_H_SECTIONS: dict[str, tuple[float, float, float, float]] = {
    "HW100x100": (100, 100, 6, 8),
    "HW125x125": (125, 125, 6.5, 9),
    "HW150x150": (150, 150, 7, 10),
    "HW175x175": (175, 175, 7.5, 11),
    "HW200x200": (200, 200, 8, 12),
    "HM148x100": (148, 100, 6, 9),
    "HM194x150": (194, 150, 6, 9),
    "HM244x175": (244, 175, 7, 11),
    "HM294x200": (294, 200, 8, 12),
    "HN150x75": (150, 75, 5, 7),
    "HN198x99": (198, 99, 4.5, 7),
    "HN200x100": (200, 100, 5.5, 8),
    "HN248x124": (248, 124, 5, 8),
    "HN250x125": (250, 125, 6, 9),
    "HN298x149": (298, 149, 5.5, 8),
    "HN300x150": (300, 150, 6.5, 9),
    "HN346x174": (346, 174, 6, 9),
    "HN350x175": (350, 175, 7, 11),
    "HN396x199": (396, 199, 7, 11),
    "HN400x150": (400, 150, 8, 13),
    "HN400x200": (400, 200, 8, 13),
}

FULL_H_TAG_PATTERN = re.compile(
    r"^H[NMW]?(\d+(?:\.\d+)?)[xX×](\d+(?:\.\d+)?)[xX×](\d+(?:\.\d+)?)[xX×](\d+(?:\.\d+)?)$"
)

CLASS_LABELS = {
    "IfcColumn": "钢柱",
    "IfcBeam": "钢梁",
    "IfcMember": "钢斜柱",
    "IfcPlate": "板",
    # 建筑构件（text-to-bim 户型链路与常规建筑 IFC）
    "IfcWall": "墙体",
    "IfcWallStandardCase": "墙体",
    "IfcSlab": "楼板",
    "IfcDoor": "门",
    "IfcWindow": "窗",
    "IfcStairFlight": "楼梯段",
    "IfcRoof": "屋面",
    "IfcCovering": "装饰面层",
    "IfcBuildingElementProxy": "未分类构件",
}

BOM_CLASSES = tuple(CLASS_LABELS)


@dataclass
class ElementMetric:
    global_id: str
    ifc_class: str
    name: str
    object_type: str
    tag: str
    storey: str
    length_mm: float
    cross1_mm: float
    cross2_mm: float
    centroid_mm: tuple[float, float, float]
    surface_area_m2: float
    volume_m3: float = 0.0
    material: str = ""
    section_label: str = ""
    section_spec: tuple[float, float, float, float] | None = None
    unit_weight_kg: float | None = None
    sjg_code: str = ""
    sjg_category: str = ""


@dataclass
class BomLine:
    line_no: int
    ifc_class: str
    category: str
    section_label: str
    length_mm: float
    quantity: int
    unit_weight_kg: float | None
    total_volume_m3: float | None
    total_weight_kg: float | None
    weight_basis: str
    material: str = ""
    sjg_code: str = ""
    sjg_category: str = ""
    storeys: Counter = field(default_factory=Counter)
    global_ids: list[str] = field(default_factory=list)


def h_section_unit_weight_kg_per_m(spec: tuple[float, float, float, float]) -> float:
    h, b, t1, t2 = spec
    area_mm2 = 2 * b * t2 + (h - 2 * t2) * t1
    return area_mm2 * STEEL_DENSITY_KG_M3 / 1_000_000.0


def parse_section_tags(tags: list[str]) -> dict[str, tuple[float, float, float, float]]:
    """图纸标注的完整 H 截面（如 H306X151X8X12）→ 外形匹配表。"""
    parsed: dict[str, tuple[float, float, float, float]] = {}
    for tag in tags:
        match = FULL_H_TAG_PATTERN.match(tag.strip())
        if match:
            h, b, t1, t2 = (float(match.group(i)) for i in range(1, 5))
            parsed[tag.strip()] = (h, b, t1, t2)
    return parsed


def match_section(
    cross1: float,
    cross2: float,
    drawing_sections: dict[str, tuple[float, float, float, float]],
) -> tuple[str, tuple[float, float, float, float] | None]:
    """按截面外形 (深x宽) 匹配：先图纸标注，再 GB/T 11263 标准表。"""
    outline = (max(cross1, cross2), min(cross1, cross2))

    def outline_error(spec: tuple[float, float, float, float]) -> float:
        return max(abs(outline[0] - spec[0]), abs(outline[1] - spec[1]))

    best_label, best_spec, best_err = "", None, SECTION_MATCH_TOLERANCE_MM + 1
    for label, spec in drawing_sections.items():
        err = outline_error(spec)
        if err < best_err:
            best_label, best_spec, best_err = label, spec, err
    if best_spec is None:
        for label, spec in STANDARD_H_SECTIONS.items():
            err = outline_error(spec)
            if err < best_err:
                best_label, best_spec, best_err = label, spec, err
    if best_spec is not None and best_err <= SECTION_MATCH_TOLERANCE_MM:
        return best_label, best_spec
    return f"外形{outline[0]:.0f}x{outline[1]:.0f}", None


def measure_elements(
    model: ifcopenshell.file,
) -> tuple[list[ElementMetric], list[str]]:
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    storey_of: dict[str, str] = {}
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        structure_name = getattr(rel.RelatingStructure, "Name", "") or ""
        for element in rel.RelatedElements:
            storey_of[element.GlobalId] = structure_name

    material_of: dict[str, str] = {}
    for rel in model.by_type("IfcRelAssociatesMaterial"):
        name = _material_name(rel.RelatingMaterial)
        if not name:
            continue
        for related in rel.RelatedObjects:
            global_id = getattr(related, "GlobalId", None)
            if global_id:
                material_of[global_id] = name

    metrics: list[ElementMetric] = []
    failures: list[str] = []
    for ifc_class in BOM_CLASSES:
        for element in model.by_type(ifc_class):
            if element.Representation is None:
                failures.append(f"{element.GlobalId}: no representation")
                continue
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
            except Exception as error:  # noqa: BLE001 - 单元素失败计入清单
                failures.append(f"{element.GlobalId}: {error}")
                continue
            verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
            if verts.shape[0] < 3:
                failures.append(f"{element.GlobalId}: degenerate mesh")
                continue
            faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)

            centroid = verts.mean(axis=0)
            centered = verts - centroid
            # PCA 主轴：第一主轴为构件长度方向（斜构件同样适用）。
            _, _, principal = np.linalg.svd(centered, full_matrices=False)
            extents = np.array(
                [
                    centered @ principal[i]
                    for i in range(3)
                ]
            )
            spans = extents.max(axis=1) - extents.min(axis=1)
            order = np.argsort(spans)[::-1]
            length, cross1, cross2 = (float(spans[i]) for i in order)

            triangle_areas = 0.5 * np.linalg.norm(
                np.cross(
                    verts[faces[:, 1]] - verts[faces[:, 0]],
                    verts[faces[:, 2]] - verts[faces[:, 0]],
                ),
                axis=1,
            )
            # 散度定理网格体积（封闭网格为几何真值；米制）。
            mesh_volume = abs(
                float(
                    np.einsum(
                        "ij,ij->i",
                        verts[faces[:, 0]],
                        np.cross(verts[faces[:, 1]], verts[faces[:, 2]]),
                    ).sum()
                )
                / 6.0
            )
            # 几何坐标为米（IfcOpenShell 归一化），换算回毫米。
            name = element.Name or ""
            object_type = element.ObjectType or ""
            sjg = classify_sjg157(name, object_type) or classify_by_ifc_class(
                ifc_class
            )
            metrics.append(
                ElementMetric(
                    global_id=element.GlobalId,
                    ifc_class=ifc_class,
                    name=name,
                    object_type=object_type,
                    tag=getattr(element, "Tag", "") or "",
                    storey=storey_of.get(element.GlobalId, ""),
                    length_mm=length * 1000.0,
                    cross1_mm=cross1 * 1000.0,
                    cross2_mm=cross2 * 1000.0,
                    centroid_mm=tuple(round(float(v) * 1000.0, 1) for v in centroid),
                    surface_area_m2=float(triangle_areas.sum()),
                    volume_m3=round(mesh_volume, 4),
                    material=material_of.get(element.GlobalId, ""),
                    sjg_code=sjg["code"] if sjg else "",
                    sjg_category=sjg["category"] if sjg else "",
                )
            )
    return metrics, failures


def _material_name(relating: object) -> str:
    """取材质名：IfcMaterial 直接取 Name；层集/型材集取首个材料名。"""
    if relating is None:
        return ""
    if hasattr(relating, "Name") and relating.is_a("IfcMaterial"):
        return relating.Name or ""
    for attr in ("ForLayerSet", "MaterialLayers", "Materials"):
        nested = getattr(relating, attr, None)
        if nested is None:
            continue
        if attr == "ForLayerSet":
            return _material_name(nested)
        for item in nested:
            material = getattr(item, "Material", item)
            name = getattr(material, "Name", "") or ""
            if name:
                return name
    return ""


def count_unmeasured_elements(
    model: ifcopenshell.file,
    covered_global_ids: set[str],
) -> dict[str, int]:
    """统计未进入测量范围的 IfcElement 子类实例(仅计数,不伪造度量)。

    覆盖审计:BOM 度量目前面向钢结构类(BOM_CLASSES);其余构件类
    (管道/风管/电气/门窗等)不能被静默忽略,必须如实计数列出。
    """
    counts: Counter[str] = Counter()
    for element in model.by_type("IfcElement"):
        global_id = getattr(element, "GlobalId", None)
        if global_id and global_id in covered_global_ids:
            continue
        counts[element.is_a()] += 1
    return dict(counts)


def build_bom(
    metrics: list[ElementMetric],
    drawing_sections: dict[str, tuple[float, float, float, float]],
) -> list[BomLine]:
    for metric in metrics:
        if metric.ifc_class in ("IfcColumn", "IfcBeam", "IfcMember"):
            label, spec = match_section(metric.cross1_mm, metric.cross2_mm, drawing_sections)
            metric.section_label = label
            metric.section_spec = spec
            if spec is not None:
                metric.unit_weight_kg = round(
                    h_section_unit_weight_kg_per_m(spec) * metric.length_mm / 1000.0, 2
                )
        elif metric.ifc_class == "IfcPlate":
            metric.section_label = (
                f"板 {metric.length_mm:.0f}x{metric.cross1_mm:.0f}x{metric.cross2_mm:.0f}"
            )
        elif metric.ifc_class in ("IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcRoof", "IfcCovering"):
            metric.section_label = f"厚{metric.cross2_mm:.0f}"
        elif metric.ifc_class in ("IfcDoor", "IfcWindow"):
            metric.section_label = f"{metric.cross1_mm:.0f}宽x{metric.length_mm:.0f}高"

    # 体积×密度计重：仅当构件显式关联了密度表内材质（假定可见可审计）。
    for metric in metrics:
        if metric.unit_weight_kg is None and metric.volume_m3 > 0 and metric.material:
            density = MATERIAL_DENSITY_KG_M3.get(metric.material)
            if density is not None:
                metric.unit_weight_kg = round(metric.volume_m3 * density, 1)

    groups: dict[tuple, list[ElementMetric]] = defaultdict(list)
    for metric in metrics:
        length_key = round(metric.length_mm / LENGTH_GROUP_STEP_MM) * LENGTH_GROUP_STEP_MM
        groups[(metric.ifc_class, metric.section_label, metric.material, length_key)].append(metric)

    lines: list[BomLine] = []
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            BOM_CLASSES.index(item[0][0]),
            item[0][1],
            item[0][2],
            item[0][3],
        ),
    )
    for index, ((ifc_class, section_label, material, length_key), members) in enumerate(ordered, start=1):
        unit_weights = [m.unit_weight_kg for m in members if m.unit_weight_kg is not None]
        unit_weight = round(sum(unit_weights) / len(unit_weights), 2) if unit_weights else None
        total_weight = (
            round(sum(m.unit_weight_kg or 0.0 for m in members), 2) if unit_weights else None
        )
        volumes = [m.volume_m3 for m in members if m.volume_m3 > 0]
        total_volume = round(sum(volumes), 3) if volumes else None
        # 组内构件 SJG 分类取众数(同组同 ifc_class,通常一致)
        sjg_counter = Counter(
            (m.sjg_code, m.sjg_category) for m in members if m.sjg_code
        )
        sjg_code, sjg_category = (
            sjg_counter.most_common(1)[0][0] if sjg_counter else ("", "")
        )
        line = BomLine(
            line_no=index,
            ifc_class=ifc_class,
            category=CLASS_LABELS.get(ifc_class, ifc_class),
            section_label=section_label,
            length_mm=float(length_key),
            quantity=len(members),
            unit_weight_kg=unit_weight,
            total_volume_m3=total_volume,
            total_weight_kg=total_weight,
            material=material,
            weight_basis=(
                # 门窗为体量盒（洞口占位），按樘计数+洞口规格采购；
                # 实体板件按体积x密度或截面理论重量，依据逐行可审计。
                "门窗按樘计数，规格=洞口尺寸；不按体量盒体积折算重量"
                if ifc_class in ("IfcDoor", "IfcWindow")
                else (
                    (
                        f"体积x密度({material} ρ={MATERIAL_DENSITY_KG_M3[material]:.0f})"
                        if material in MATERIAL_DENSITY_KG_M3 and ifc_class not in ("IfcColumn", "IfcBeam", "IfcMember")
                        else "截面规格理论重量"
                    )
                    if unit_weights
                    else f"几何实测体积；材质{material or '未知'}无密度档，不伪造重量"
                    if total_volume
                    else "缺截面厚度规格，不伪造重量"
                )
            ),
            sjg_code=sjg_code,
            sjg_category=sjg_category,
        )
        for member in members:
            line.storeys[member.storey or "?"] += 1
            line.global_ids.append(member.global_id)
        lines.append(line)
    return lines


def write_csvs(
    csv_dir: Path,
    lines: list[BomLine],
    metrics: list[ElementMetric],
    unmeasured_by_class: dict[str, int] | None = None,
) -> dict[str, str]:
    csv_dir.mkdir(parents=True, exist_ok=True)
    summary_path = csv_dir / "bom_summary.csv"
    elements_path = csv_dir / "bom_elements.csv"

    with summary_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "行号", "类别", "SJG编码", "SJG类目", "IFC类型", "截面/规格", "长度mm", "数量",
                "单重kg", "总重kg", "体积m3", "计量依据", "楼层分布",
            ]
        )
        for line in lines:
            writer.writerow(
                [
                    line.line_no,
                    line.category,
                    line.sjg_code,
                    line.sjg_category,
                    line.ifc_class,
                    line.section_label + (f" {line.material}" if line.material else ""),
                    f"{line.length_mm:.0f}",
                    line.quantity,
                    "" if line.unit_weight_kg is None else line.unit_weight_kg,
                    "" if line.total_weight_kg is None else line.total_weight_kg,
                    "" if line.total_volume_m3 is None else line.total_volume_m3,
                    line.weight_basis,
                    " ".join(f"{name}×{count}" for name, count in sorted(line.storeys.items())),
                ]
            )
        for ifc_class, count in sorted((unmeasured_by_class or {}).items()):
            sjg = classify_by_ifc_class(ifc_class)
            writer.writerow(
                ["-", "未测量(仅计数)", sjg["code"] if sjg else "", sjg["category"] if sjg else "",
                 ifc_class, "本类构件不在当前测量范围", "",
                 count, "", "", "", "不伪造缺失度量,仅如实计数", ""]
            )
        total_qty = sum(line.quantity for line in lines)
        total_weight = round(sum(line.total_weight_kg or 0.0 for line in lines), 2)
        total_volume = round(sum(line.total_volume_m3 or 0.0 for line in lines), 3)
        weighted = sum(1 for line in lines if line.total_weight_kg is not None)
        writer.writerow(
            ["合计", "", "", "", "", f"共{len(lines)}行", "", total_qty, "", total_weight,
             total_volume, f"计重行{weighted}", ""]
        )

    with elements_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "GlobalId", "类别", "SJG编码", "SJG类目", "构件名", "楼层", "截面/规格", "实测长度mm",
                "截面外形mm", "单重kg", "形心X", "形心Y", "形心Z",
                "表面积m2", "来源图层", "DWG句柄", "体积m3",
            ]
        )
        for metric in sorted(metrics, key=lambda m: (m.storey, m.ifc_class, m.name)):
            writer.writerow(
                [
                    metric.global_id,
                    CLASS_LABELS.get(metric.ifc_class, metric.ifc_class),
                    metric.sjg_code,
                    metric.sjg_category,
                    metric.name,
                    metric.storey,
                    metric.section_label,
                    f"{metric.length_mm:.0f}",
                    f"{metric.cross1_mm:.0f}x{metric.cross2_mm:.0f}",
                    "" if metric.unit_weight_kg is None else metric.unit_weight_kg,
                    metric.centroid_mm[0],
                    metric.centroid_mm[1],
                    metric.centroid_mm[2],
                    round(metric.surface_area_m2, 3),
                    metric.object_type,
                    metric.tag,
                    round(metric.volume_m3, 4),
                ]
            )
    return {"summary": str(summary_path), "elements": str(elements_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a detailed BOM from an IFC model")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--csv-dir", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--section-tag",
        action="append",
        default=[],
        help="full section designation from drawings, e.g. H306X151X8X12 (repeatable)",
    )
    args = parser.parse_args(argv)

    source_arg = args.source or (args.paths[0] if len(args.paths) >= 1 else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required")
    source, output = Path(source_arg), Path(output_arg)
    if not source.is_file():
        raise SystemExit(f"IFC source is not a readable file: {source}")

    model = ifcopenshell.open(str(source))
    drawing_sections = parse_section_tags(args.section_tag)

    # 模型属性集里若存有平面图截面标注统计，自动并入匹配表。
    for pset in model.by_type("IfcPropertySet"):
        for prop in pset.HasProperties or []:
            if prop.is_a("IfcPropertySingleValue") and prop.NominalValue:
                value = str(prop.NominalValue.wrappedValue)
                for token in re.findall(r"H[NMW]?\d+(?:[xX×]\d+(?:\.\d+)?){3}", value):
                    drawing_sections.update(parse_section_tags([token]))

    metrics, failures = measure_elements(model)
    if not metrics:
        raise SystemExit("IFC model exposed no measurable building elements")
    lines = build_bom(metrics, drawing_sections)
    covered_ids = {m.global_id for m in metrics}
    covered_ids.update(f.split(":", 1)[0] for f in failures)
    unmeasured_by_class = count_unmeasured_elements(model, covered_ids)

    csv_paths: dict[str, str] = {}
    if args.csv_dir:
        csv_paths = write_csvs(Path(args.csv_dir), lines, metrics, unmeasured_by_class)

    weighted_lines = [line for line in lines if line.total_weight_kg is not None]
    manifest = {
        "schema": "architoken.ifc_bom_manifest.v1",
        "sourcePath": str(source),
        "outputPath": str(output),
        "engine": "ifcopenshell-geom+pca",
        "ifcSchema": str(model.schema),
        "projectName": args.name
        or next(iter(model.by_type("IfcProject")), None) and model.by_type("IfcProject")[0].Name,
        "reviewState": "professional_review_required",
        "quantityBasis": "ifc_element_count",
        "measureBasis": "tessellated_geometry_pca",
        "drawingSections": {k: list(v) for k, v in drawing_sections.items()},
        "summary": {
            "lineCount": len(lines),
            "elementCount": len(metrics),
            "totalQuantity": sum(line.quantity for line in lines),
            "weightedLineCount": len(weighted_lines),
            "totalWeightKg": round(sum(line.total_weight_kg or 0.0 for line in lines), 2),
            "totalVolumeM3": round(sum(line.total_volume_m3 or 0.0 for line in lines), 3),
            "geometryFailures": len(failures),
            "byClass": dict(Counter(m.ifc_class for m in metrics)),
            "unmeasuredCount": sum(unmeasured_by_class.values()),
            "unmeasuredByClass": unmeasured_by_class,
        },
        "lines": [
            {
                "lineNo": line.line_no,
                "category": line.category,
                "sjgCode": line.sjg_code,
                "sjgCategory": line.sjg_category,
                "ifcClass": line.ifc_class,
                "sectionLabel": line.section_label,
                "lengthMm": line.length_mm,
                "quantity": line.quantity,
                "unitWeightKg": line.unit_weight_kg,
                "totalWeightKg": line.total_weight_kg,
                "totalVolumeM3": line.total_volume_m3,
                "weightBasis": line.weight_basis,
                "storeys": dict(line.storeys),
                "globalIds": line.global_ids,
            }
            for line in lines
        ],
        "classificationStandard": "SJG 157-2024 建筑工程信息模型语义字典标准",
        "csvArtifacts": csv_paths,
        "failures": failures[:20],
        "notes": [
            "长度与截面外形为 IFC 三角化几何 PCA 实测值；截面厚度按图纸标注/GB.T 11263 标准表匹配。",
            "理论重量=截面积x长度x7850kg/m3，仅对匹配到完整截面规格的构件计算，不伪造缺失数据。",
            "体积为封闭三角网格散度定理实测值（m3）；乘以材质密度即得重量，本清单不假设材质。",
            "SJG 编码/类目按《建筑工程信息模型语义字典标准》SJG 157-2024 由构件名/IFC 类型映射,供专业评审核对。",
            "清单为专业评审输入（professional_review_required），不可直接作为采购依据。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({**manifest, "lines": f"<{len(lines)} lines>", "failures": len(failures)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
