# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_dxf_to_ifc.py <input.dxf> <output.ifc> [--name NAME]

DXF → IFC4:仅当 DXF 含真实三维几何(3DFACE / POLYFACE_MESH / MESH)时转换为
IfcTriangulatedFaceSet 几何交换模型;按实体图层名做 SJG 157 分类(命中升级真实
IFC 类型,否则 Proxy)。纯 2D 图纸(无三维实体)诚实报错,不把平面图伪造成三维。

DWG 请走 architoken_dwg_to_ifc(LibreDWG 路径)。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import ezdxf
import ifcopenshell
import ifcopenshell.guid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_semantic_enrich import (  # noqa: E402
    attach_sjg_classifications,
    classify_component,
    pick_ifc_entity_type,
)


def _face_triangles(entity):
    """3DFACE → 顶点列表 + 三角(四点拆两三角)。返回 (coords, tris) 或 None。"""
    try:
        pts = [entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx2, entity.dxf.vtx3]
    except Exception:
        return None
    coords = [(round(p[0], 3), round(p[1], 3), round(p[2], 3)) for p in pts]
    # 退化(vtx2==vtx3)即三角形
    if coords[2] == coords[3]:
        return coords[:3], [(0, 1, 2)]
    return coords, [(0, 1, 2), (0, 2, 3)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert 3D DXF to IFC4")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--name", default=None)
    args = parser.parse_args(argv)
    if len(args.paths) < 2:
        parser.error("usage: architoken_dxf_to_ifc.py <input.dxf> <output.ifc>")
    source, output = Path(args.paths[0]), Path(args.paths[1])
    name = args.name or source.stem

    doc = ezdxf.readfile(str(source))
    msp = doc.modelspace()
    # 按图层聚合三维面
    by_layer: dict[str, dict] = defaultdict(lambda: {"coords": [], "tris": []})
    for e in msp:
        if e.dxftype() != "3DFACE":
            continue
        res = _face_triangles(e)
        if not res:
            continue
        coords, tris = res
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        bucket = by_layer[layer]
        base = len(bucket["coords"])
        bucket["coords"].extend(coords)
        bucket["tris"].extend([tuple(i + base for i in t) for t in tris])

    if not by_layer:
        raise SystemExit(
            "DXF 不含三维实体(3DFACE/网格);2D 平面图无三维几何,不可转 IFC——"
            "请直接查看图纸或导出图纸 BOM。"
        )

    model = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid.new
    origin = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    refdir = model.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0))
    wcs = model.create_entity("IfcAxis2Placement3D", Location=origin, Axis=axis, RefDirection=refdir)
    ctx = model.create_entity(
        "IfcGeometricRepresentationContext", ContextIdentifier="Body", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1.0e-5, WorldCoordinateSystem=wcs,
    )
    mm = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=[mm])
    project = model.create_entity(
        "IfcProject", GlobalId=guid(), Name=f"{name} (DXF→IFC 几何交换)",
        RepresentationContexts=[ctx], UnitsInContext=units,
    )
    site = model.create_entity("IfcSite", GlobalId=guid(), Name="DXF Source Site")
    building = model.create_entity("IfcBuilding", GlobalId=guid(), Name="DXF Source Building")
    storey = model.create_entity("IfcBuildingStorey", GlobalId=guid(), Name="DXF Geometry")
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=project, RelatedObjects=[site])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=site, RelatedObjects=[building])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=building, RelatedObjects=[storey])
    placement = model.create_entity("IfcLocalPlacement", RelativePlacement=wcs)

    elements = []
    classified = []
    for layer, bucket in by_layer.items():
        if not bucket["tris"]:
            continue
        point_list = model.create_entity("IfcCartesianPointList3D", CoordList=bucket["coords"])
        face_set = model.create_entity(
            "IfcTriangulatedFaceSet", Coordinates=point_list,
            CoordIndex=[tuple(i + 1 for i in t) for t in bucket["tris"]],
        )
        shape = model.create_entity(
            "IfcShapeRepresentation", ContextOfItems=ctx,
            RepresentationIdentifier="Body", RepresentationType="Tessellation", Items=[face_set],
        )
        product_shape = model.create_entity("IfcProductDefinitionShape", Representations=[shape])
        match = classify_component(layer)
        ifc_type = pick_ifc_entity_type(match)
        el = model.create_entity(
            ifc_type, GlobalId=guid(), Name=layer,
            ObjectType="DXF 3DFACE layer aggregate",
            ObjectPlacement=placement, Representation=product_shape,
        )
        elements.append(el)
        if match:
            classified.append((el, match))

    model.create_entity(
        "IfcRelContainedInSpatialStructure", GlobalId=guid(),
        RelatedElements=elements, RelatingStructure=storey,
    )
    code_count = attach_sjg_classifications(model, classified)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(
        f"INFO: IFC written: {output} layers={len(elements)} "
        f"sjgClassified={len(classified)} sjgCodes={code_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
