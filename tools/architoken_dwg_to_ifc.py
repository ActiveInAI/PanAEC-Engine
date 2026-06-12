# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""ArchIToken DWG to IFC sidecar.

Reads AutoCAD DWG geometry through the LibreDWG native JSON dump (dwgread -O
JSON) and writes a real IFC4 tessellated exchange model through IfcOpenShell.

Primary input is a 3D model DWG whose geometry lives as 3DFACE entities inside
(anonymous) block definitions placed by INSERT. An optional 2D structural plan
DWG (--plan) contributes semantics: storey titles, default member sections and
per-discipline counts used for cross-checking. Elements are classified by the
PKPM-style numeric layer prefix of their INSERT (11=钢柱, 12=钢梁, 13=钢斜柱,
22=板) — everything else stays IfcBuildingElementProxy. Storey elevations are
clustered from beam Z midpoints; the result is an approximation for review,
not a claim of professional BIM compliance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_semantic_enrich import (  # noqa: E402
    attach_sjg_classifications as _attach_sjg,
    classify_component as _sjg_classify,
)
from sjg157_classify import classify_by_ifc_class as _sjg_by_ifc  # noqa: E402

Vec3 = tuple[float, float, float]

DWGREAD_TIMEOUT_SECONDS = 600
STOREY_GAP_MM = 600.0

LAYER_PREFIX_CLASSES: dict[str, tuple[str, str]] = {
    # prefix -> (IFC class, Chinese label)
    "11": ("IfcColumn", "钢柱"),
    "12": ("IfcBeam", "钢梁"),
    "13": ("IfcMember", "钢斜柱"),
    "22": ("IfcPlate", "板"),
}

CLASS_COLORS: dict[str, tuple[float, float, float]] = {
    "IfcColumn": (0.45, 0.55, 0.75),
    "IfcBeam": (0.75, 0.55, 0.35),
    "IfcMember": (0.55, 0.7, 0.5),
    "IfcPlate": (0.6, 0.6, 0.65),
    "IfcBuildingElementProxy": (0.62, 0.62, 0.62),
}

SECTION_TEXT_PATTERN = re.compile(
    r"^(?:H[NMW]?\d+(?:[xX×]\d+(?:\.\d+)?){1,3}|BC\d+(?:[xX×]\d+)?|C\d+[xX×]\d+.*|PL\d+.*)$"
)
STOREY_TITLE_PATTERN = re.compile(r"第\s*(\d+)\s*层")


def absref(handle: object) -> int | None:
    if isinstance(handle, list) and handle:
        last = handle[-1]
        if isinstance(last, int):
            return last
    return None


@dataclass
class BlockGeometry:
    handle: int
    coordinates: list[Vec3] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    z_min: float = math.inf
    z_max: float = -math.inf


@dataclass
class InsertRecord:
    block_handle: int
    ins_pt: Vec3
    layer: str
    handle: int | None


@dataclass
class PlanSemantics:
    storey_titles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    section_texts: Counter = field(default_factory=Counter)
    layer_entity_counts: Counter = field(default_factory=Counter)


def resolve_dwgread(cli_value: str | None) -> str:
    candidates: list[str] = []
    if cli_value:
        candidates.append(cli_value)
    env_bin = os.environ.get("ARCHITOKEN_LIBREDWG_BIN", "").strip()
    if env_bin:
        env_path = Path(env_bin)
        if env_path.is_dir():
            candidates.append(str(env_path / "dwgread"))
        else:
            candidates.append(str(env_path.with_name("dwgread")))
            candidates.append(env_bin)
    env_dir = os.environ.get("LIBREDWG_BIN_DIR", "").strip()
    if env_dir:
        candidates.append(str(Path(env_dir) / "dwgread"))
    which = shutil.which("dwgread")
    if which:
        candidates.append(which)
    candidates.append(str(Path.home() / "libredwg" / "bin" / "dwgread"))

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK) and path.name.startswith("dwgread"):
            return str(path)
    raise SystemExit(
        "dwgread (LibreDWG) not found; install LibreDWG and/or set "
        "ARCHITOKEN_LIBREDWG_BIN / LIBREDWG_BIN_DIR"
    )


def dwg_to_json(dwgread: str, source: Path, scratch_dir: Path) -> dict:
    out_path = scratch_dir / f"{source.stem}.json"
    result = subprocess.run(
        [dwgread, "-O", "JSON", "-o", str(out_path), str(source)],
        capture_output=True,
        timeout=DWGREAD_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or not out_path.is_file():
        raise SystemExit(
            f"dwgread failed for {source}: rc={result.returncode} "
            f"stderr={result.stderr.decode('utf-8', 'replace')[-400:]}"
        )
    with out_path.open(encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def triangulate_3dface(corners: list[Vec3]) -> list[tuple[Vec3, Vec3, Vec3]]:
    c1, c2, c3, c4 = corners
    triangles = [(c1, c2, c3)]
    if c4 is not None and tuple(c4) != tuple(c3):
        triangles.append((c1, c3, c4))
    return triangles


def collect_model(dump: dict) -> tuple[
    dict[int, BlockGeometry],
    list[InsertRecord],
    dict[str, int],
]:
    objects = dump.get("OBJECTS", [])
    layer_names: dict[int, str] = {}
    for obj in objects:
        if obj.get("object") == "LAYER":
            handle = absref(obj.get("handle"))
            if handle is not None:
                layer_names[handle] = str(obj.get("name") or f"layer#{handle}")

    blocks: dict[int, BlockGeometry] = {}
    inserts: list[InsertRecord] = []
    skipped = Counter()

    for obj in objects:
        kind = obj.get("entity")
        if kind == "3DFACE":
            owner = absref(obj.get("ownerhandle"))
            if owner is None:
                skipped["3dface_without_owner"] += 1
                continue
            corners = [obj.get(f"corner{i}") for i in (1, 2, 3, 4)]
            if any(not isinstance(c, list) or len(c) < 3 for c in corners[:3]):
                skipped["3dface_malformed"] += 1
                continue
            block = blocks.setdefault(owner, BlockGeometry(handle=owner))
            for tri in triangulate_3dface([tuple(c[:3]) if isinstance(c, list) else None for c in corners]):
                indices = []
                for point in tri:
                    block.coordinates.append(point)
                    block.z_min = min(block.z_min, point[2])
                    block.z_max = max(block.z_max, point[2])
                    indices.append(len(block.coordinates) - 1)
                block.triangles.append(tuple(indices))
        elif kind == "INSERT":
            if obj.get("entmode") not in (None, 2):
                skipped["nested_insert"] += 1
                continue
            block_handle = absref(obj.get("block_header"))
            ins_pt = obj.get("ins_pt") or [0.0, 0.0, 0.0]
            if block_handle is None:
                skipped["insert_without_block"] += 1
                continue
            scale = obj.get("scale") or [1.0, 1.0, 1.0]
            rotation = float(obj.get("rotation") or 0.0)
            extrusion = obj.get("extrusion") or [0.0, 0.0, 1.0]
            if (
                any(abs(s - 1.0) > 1e-9 for s in scale)
                or abs(rotation) > 1e-9
                or tuple(extrusion) != (0.0, 0.0, 1.0)
            ):
                # 当前样本全部为纯平移；遇到带旋转/缩放的 INSERT 时记账而不是静默丢失。
                skipped["insert_with_transform"] += 1
                continue
            layer = layer_names.get(absref(obj.get("layer")) or -1, "?")
            inserts.append(
                InsertRecord(
                    block_handle=block_handle,
                    ins_pt=tuple(float(v) for v in ins_pt[:3]),
                    layer=layer,
                    handle=absref(obj.get("handle")),
                )
            )
        elif kind in ("POLYLINE_3D", "POLYLINE_2D", "POINT"):
            skipped[f"{kind.lower()}_wireframe"] += 1

    return blocks, inserts, dict(skipped)


def collect_plan(dump: dict) -> PlanSemantics:
    objects = dump.get("OBJECTS", [])
    layer_names: dict[int, str] = {}
    for obj in objects:
        if obj.get("object") == "LAYER":
            handle = absref(obj.get("handle"))
            if handle is not None:
                layer_names[handle] = str(obj.get("name") or f"layer#{handle}")

    semantics = PlanSemantics()
    for obj in objects:
        kind = obj.get("entity")
        if not kind:
            continue
        layer = layer_names.get(absref(obj.get("layer")) or -1, "?")
        semantics.layer_entity_counts[(kind, layer)] += 1
        if kind in ("TEXT", "MTEXT"):
            text = str(obj.get("text_value") or obj.get("text") or "").strip()
            if not text:
                continue
            if STOREY_TITLE_PATTERN.search(text):
                semantics.storey_titles.append(text)
            elif text.startswith("注") or re.match(r"^\d+、", text):
                semantics.notes.append(text)
            elif SECTION_TEXT_PATTERN.match(text):
                semantics.section_texts[text] += 1
    semantics.storey_titles.sort()
    return semantics


def classify_layer(layer: str) -> tuple[str, str]:
    prefix = layer.split("-", 1)[0]
    return LAYER_PREFIX_CLASSES.get(prefix, ("IfcBuildingElementProxy", "未分类构件"))


def cluster_levels(values: list[float], gap_mm: float = STOREY_GAP_MM) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - clusters[-1][-1] > gap_mm:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(group) / len(group) for group in clusters]


def assign_storey(levels: list[float], z_ref: float) -> int:
    if not levels:
        return 0
    best = min(range(len(levels)), key=lambda i: abs(levels[i] - z_ref))
    return best


def build_ifc(
    output: Path,
    *,
    project_name: str,
    schema: str,
    blocks: dict[int, BlockGeometry],
    inserts: list[InsertRecord],
    storey_levels: list[float],
    storey_names: list[str],
    plan: PlanSemantics | None,
    source_names: list[str],
) -> dict:
    model = ifcopenshell.file(schema=schema)
    guid = ifcopenshell.guid.new

    def axis_placement(location: Vec3 = (0.0, 0.0, 0.0)):
        return model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint", Coordinates=tuple(float(v) for v in location)),
        )

    world_placement = axis_placement()
    context = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Body",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1.0e-5,
        WorldCoordinateSystem=world_placement,
    )
    millimeter = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    unit_assignment = model.create_entity("IfcUnitAssignment", Units=[millimeter])

    project = model.create_entity(
        "IfcProject",
        GlobalId=guid(),
        Name=project_name,
        RepresentationContexts=[context],
        UnitsInContext=unit_assignment,
    )
    site = model.create_entity("IfcSite", GlobalId=guid(), Name=f"{project_name} 场地")
    building = model.create_entity("IfcBuilding", GlobalId=guid(), Name=f"{project_name} 建筑")
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=project, RelatedObjects=[site])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=site, RelatedObjects=[building])

    site_placement = model.create_entity("IfcLocalPlacement", RelativePlacement=world_placement)
    building_placement = model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=site_placement, RelativePlacement=axis_placement()
    )

    storeys = []
    storey_placements = []
    sjg_classified: list = []
    levels = storey_levels or [0.0]
    names = storey_names or [f"标高 {level / 1000:+.3f}m" for level in levels]
    for index, level in enumerate(levels):
        placement = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=building_placement,
            RelativePlacement=axis_placement((0.0, 0.0, float(level))),
        )
        storey = model.create_entity(
            "IfcBuildingStorey",
            GlobalId=guid(),
            Name=names[index] if index < len(names) else f"标高 {level / 1000:+.3f}m",
            Elevation=float(level),
            ObjectPlacement=placement,
        )
        storeys.append(storey)
        storey_placements.append(placement)
    model.create_entity(
        "IfcRelAggregates", GlobalId=guid(), RelatingObject=building, RelatedObjects=storeys
    )

    # 每个块定义一份网格，经 IfcRepresentationMap 由实例复用。
    representation_maps: dict[int, object] = {}
    styled: set[int] = set()
    style_cache: dict[str, object] = {}

    def surface_style(ifc_class: str):
        if ifc_class not in style_cache:
            rgb = CLASS_COLORS.get(ifc_class, CLASS_COLORS["IfcBuildingElementProxy"])
            colour = model.create_entity("IfcColourRgb", Red=rgb[0], Green=rgb[1], Blue=rgb[2])
            rendering = model.create_entity(
                "IfcSurfaceStyleRendering", SurfaceColour=colour, ReflectanceMethod="NOTDEFINED"
            )
            style_cache[ifc_class] = model.create_entity(
                "IfcSurfaceStyle", Side="BOTH", Styles=[rendering]
            )
        return style_cache[ifc_class]

    def representation_map_for(block: BlockGeometry, ifc_class: str):
        if block.handle in representation_maps:
            return representation_maps[block.handle]
        point_list = model.create_entity(
            "IfcCartesianPointList3D",
            CoordList=[tuple(float(v) for v in point) for point in block.coordinates],
        )
        face_set = model.create_entity(
            "IfcTriangulatedFaceSet",
            Coordinates=point_list,
            CoordIndex=[tuple(i + 1 for i in triangle) for triangle in block.triangles],
        )
        if block.handle not in styled:
            model.create_entity(
                "IfcStyledItem", Item=face_set, Styles=[surface_style(ifc_class)]
            )
            styled.add(block.handle)
        shape = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=context,
            RepresentationIdentifier="Body",
            RepresentationType="Tessellation",
            Items=[face_set],
        )
        rep_map = model.create_entity(
            "IfcRepresentationMap",
            MappingOrigin=axis_placement(),
            MappedRepresentation=shape,
        )
        representation_maps[block.handle] = rep_map
        return rep_map

    class_counter: Counter = Counter()
    storey_elements: dict[int, list] = defaultdict(list)
    triangle_total = 0

    for insert in inserts:
        block = blocks.get(insert.block_handle)
        if block is None or not block.triangles:
            class_counter["skipped_no_geometry"] += 1
            continue
        ifc_class, label = classify_layer(insert.layer)
        class_counter[ifc_class] += 1
        triangle_total += len(block.triangles)

        z_ref = insert.ins_pt[2] + (
            block.z_min if ifc_class == "IfcColumn" else (block.z_min + block.z_max) / 2.0
        )
        storey_index = assign_storey(levels, z_ref)
        level = levels[storey_index]

        rep_map = representation_map_for(block, ifc_class)
        mapped_item = model.create_entity(
            "IfcMappedItem",
            MappingSource=rep_map,
            MappingTarget=model.create_entity(
                "IfcCartesianTransformationOperator3D",
                LocalOrigin=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
            ),
        )
        shape = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=context,
            RepresentationIdentifier="Body",
            RepresentationType="MappedRepresentation",
            Items=[mapped_item],
        )
        product_shape = model.create_entity("IfcProductDefinitionShape", Representations=[shape])
        placement = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=storey_placements[storey_index],
            RelativePlacement=axis_placement(
                (insert.ins_pt[0], insert.ins_pt[1], insert.ins_pt[2] - level)
            ),
        )
        sequence = class_counter[ifc_class]
        element = model.create_entity(
            ifc_class,
            GlobalId=guid(),
            Name=f"{label}-{sequence:04d}",
            ObjectType=f"DWG 图层 {insert.layer}",
            Tag=str(insert.handle or ""),
            ObjectPlacement=placement,
            Representation=product_shape,
        )
        storey_elements[storey_index].append(element)
        sjg = _sjg_classify(label, insert.layer) or _sjg_by_ifc(ifc_class)
        if sjg:
            sjg_classified.append((element, sjg))

    for storey_index, elements in storey_elements.items():
        model.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=guid(),
            RelatedElements=elements,
            RelatingStructure=storeys[storey_index],
        )

    _attach_sjg(model, sjg_classified)

    if plan is not None and (plan.notes or plan.section_texts or plan.storey_titles):
        properties = []

        def text_property(name: str, value: str):
            return model.create_entity(
                "IfcPropertySingleValue",
                Name=name,
                NominalValue=model.create_entity("IfcText", value),
            )

        for index, note in enumerate(plan.notes[:10], start=1):
            properties.append(text_property(f"平面图说明{index}", note))
        if plan.storey_titles:
            properties.append(text_property("平面图楼层标题", " / ".join(plan.storey_titles)))
        if plan.section_texts:
            top = ", ".join(f"{text}×{count}" for text, count in plan.section_texts.most_common(12))
            properties.append(text_property("平面图截面标注统计", top))
        pset = model.create_entity(
            "IfcPropertySet",
            GlobalId=guid(),
            Name="ArchiToken_结构平面布置图",
            HasProperties=properties,
        )
        model.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=guid(),
            RelatedObjects=[building],
            RelatingPropertyDefinition=pset,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))

    return {
        "elementsByClass": {
            key: value for key, value in class_counter.items() if not key.startswith("skipped")
        },
        "skipped": {key: value for key, value in class_counter.items() if key.startswith("skipped")},
        "triangleCount": triangle_total,
        "blockDefinitionsUsed": len(representation_maps),
        "storeys": [
            {"name": storeys[i].Name, "elevationMm": levels[i], "elements": len(storey_elements.get(i, []))}
            for i in range(len(storeys))
        ],
        "sourceNames": source_names,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert DWG drawings to an IFC4 model")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--plan", default=None, help="2D structural plan DWG for semantics")
    parser.add_argument("--name", default=None)
    parser.add_argument("--schema", default="IFC4")
    parser.add_argument("--dwgread", default=None, help="path to LibreDWG dwgread binary")
    args = parser.parse_args(argv)

    source_arg = args.source or (args.paths[0] if len(args.paths) >= 1 else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required; pass --input/--output or positional source output")

    source = Path(source_arg)
    output = Path(output_arg)
    plan_path = Path(args.plan) if args.plan else None
    if not source.is_file():
        raise SystemExit(f"DWG source is not a readable file: {source}")
    if plan_path is not None and not plan_path.is_file():
        raise SystemExit(f"plan DWG is not a readable file: {plan_path}")

    dwgread = resolve_dwgread(args.dwgread)

    with tempfile.TemporaryDirectory(prefix="architoken-dwg-ifc-") as scratch:
        scratch_dir = Path(scratch)
        model_dump = dwg_to_json(dwgread, source, scratch_dir)
        blocks, inserts, skipped = collect_model(model_dump)
        if not any(block.triangles for block in blocks.values()):
            raise SystemExit("DWG source did not expose any 3DFACE surface geometry")

        plan = None
        if plan_path is not None:
            plan = collect_plan(dwg_to_json(dwgread, plan_path, scratch_dir))

    beam_mids = [
        insert.ins_pt[2]
        + (blocks[insert.block_handle].z_min + blocks[insert.block_handle].z_max) / 2.0
        for insert in inserts
        if classify_layer(insert.layer)[0] == "IfcBeam"
        and insert.block_handle in blocks
        and blocks[insert.block_handle].triangles
    ]
    levels = cluster_levels(beam_mids)
    warnings: list[str] = []
    storey_names: list[str] = []
    plan_storey_count = len(plan.storey_titles) if plan else 0
    if plan_storey_count and len(levels) == plan_storey_count:
        storey_names = [f"第{i + 1}层" for i in range(len(levels))]
    elif plan_storey_count:
        warnings.append(
            f"平面图标注 {plan_storey_count} 个楼层，但梁标高聚类得到 {len(levels)} 个标高带；"
            "楼层按聚类标高命名"
        )
    if not levels:
        warnings.append("未能从钢梁标高聚类出楼层；全部构件归入单一楼层")

    summary = build_ifc(
        output,
        project_name=args.name or source.stem,
        schema=args.schema.upper(),
        blocks=blocks,
        inserts=inserts,
        storey_levels=levels,
        storey_names=storey_names,
        plan=plan,
        source_names=[source.name] + ([plan_path.name] if plan_path else []),
    )

    parsed = ifcopenshell.open(str(output))
    manifest = {
        "schema": "architoken.dwg_to_ifc_sidecar_manifest.v1",
        "sourcePath": str(source),
        "planPath": str(plan_path) if plan_path else None,
        "outputPath": str(output),
        "engine": "libredwg-json+ifcopenshell",
        "ifcSchema": str(getattr(parsed, "schema", args.schema.upper())),
        "blockCount": len(blocks),
        "insertCount": len(inserts),
        "skippedEntities": skipped,
        "warnings": warnings,
        "planStoreyTitles": plan.storey_titles if plan else [],
        "planNotes": plan.notes[:10] if plan else [],
        "sourceOfRecord": "dwg",
        "semanticScope": "geometry_exchange_ifc_with_plan_semantics",
        **summary,
    }
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
