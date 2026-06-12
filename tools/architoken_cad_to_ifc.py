# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_cad_to_ifc.py — STEP/STP/IGES/IGS/STL → 真实几何 IFC4(在 freecad.cmd 下运行)

用 FreeCAD(OCCT 内核)读取实体/网格,对每个对象三角化为 IfcTriangulatedFaceSet,
按对象名/产品标签做 SJG 157 分类——命中具体构件类则生成真实 IFC 实体
(IfcColumn/IfcBeam/...)并写 IfcClassificationReference,否则 IfcBuildingElementProxy。
STL 为无名网格 → 单一 Proxy(不伪造语义)。

参数经环境变量传入(freecadcmd 会把位置参数当文档打开):
  ARCHITOKEN_IFC_INPUT / ARCHITOKEN_IFC_OUTPUT / ARCHITOKEN_IFC_NAME
单位:输出毫米(OCCT 几何按 mm),Z-up 保持源坐标。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import ifcopenshell  # FreeCAD 内置 0.8.x
import ifcopenshell.guid

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ifc_semantic_enrich import (
        attach_sjg_classifications,
        classify_component,
        pick_ifc_entity_type,
    )
except Exception:  # noqa: BLE001
    def classify_component(*_a):
        return None

    def pick_ifc_entity_type(_m):
        return "IfcBuildingElementProxy"

    def attach_sjg_classifications(_model, _c):
        return 0

# OCCT 三角化精度(线性偏差 mm / 角度 rad)
LINEAR_DEFLECTION = 1.0
ANGULAR_DEFLECTION = 0.5


def _emit_ifc_skeleton(model, name):
    guid = ifcopenshell.guid.new
    origin = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    refdir = model.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0))
    wcs = model.create_entity(
        "IfcAxis2Placement3D", Location=origin, Axis=axis, RefDirection=refdir
    )
    ctx = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Body",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1.0e-5,
        WorldCoordinateSystem=wcs,
    )
    mm = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=[mm])
    project = model.create_entity(
        "IfcProject", GlobalId=guid(), Name=name,
        RepresentationContexts=[ctx], UnitsInContext=units,
    )
    site = model.create_entity("IfcSite", GlobalId=guid(), Name="CAD Source Site")
    building = model.create_entity("IfcBuilding", GlobalId=guid(), Name="CAD Source Building")
    storey = model.create_entity("IfcBuildingStorey", GlobalId=guid(), Name="CAD Geometry")
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=project, RelatedObjects=[site])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=site, RelatedObjects=[building])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=building, RelatedObjects=[storey])
    placement = model.create_entity("IfcLocalPlacement", RelativePlacement=wcs)
    return ctx, storey, placement


def _add_tessellated(model, ctx, placement, coords, triangles, name, ifc_type):
    guid = ifcopenshell.guid.new
    point_list = model.create_entity("IfcCartesianPointList3D", CoordList=coords)
    face_set = model.create_entity(
        "IfcTriangulatedFaceSet", Coordinates=point_list,
        CoordIndex=[tuple(i + 1 for i in t) for t in triangles],
    )
    shape = model.create_entity(
        "IfcShapeRepresentation", ContextOfItems=ctx,
        RepresentationIdentifier="Body", RepresentationType="Tessellation",
        Items=[face_set],
    )
    product_shape = model.create_entity("IfcProductDefinitionShape", Representations=[shape])
    return model.create_entity(
        ifc_type, GlobalId=guid(), Name=name,
        ObjectType="CAD Tessellation (FreeCAD/OCCT)",
        ObjectPlacement=placement, Representation=product_shape,
    )


def _shape_to_mesh(shape):
    """OCCT Shape → (coords[mm], triangles)。返回 None 表示无网格。"""
    try:
        verts, facets = shape.tessellate(LINEAR_DEFLECTION)
    except Exception:
        return None
    if not verts or not facets:
        return None
    coords = [(round(v.x, 3), round(v.y, 3), round(v.z, 3)) for v in verts]
    triangles = [tuple(f) for f in facets if len(f) == 3]
    if not triangles:
        return None
    return coords, triangles


def main() -> int:
    source = Path(os.environ["ARCHITOKEN_IFC_INPUT"])
    output = Path(os.environ["ARCHITOKEN_IFC_OUTPUT"])
    name = os.environ.get("ARCHITOKEN_IFC_NAME") or source.stem
    ext = source.suffix.lower()

    import FreeCAD  # noqa: PLC0415

    model = ifcopenshell.file(schema="IFC4")
    ctx, storey, placement = _emit_ifc_skeleton(model, f"{name} (CAD→IFC 几何交换)")
    elements = []
    classified = []

    if ext == ".stl":
        import Mesh  # noqa: PLC0415

        mesh = Mesh.Mesh(str(source))
        pts = mesh.Topology[0]
        facets = mesh.Topology[1]
        coords = [(round(p.x, 3), round(p.y, 3), round(p.z, 3)) for p in pts]
        triangles = [tuple(f) for f in facets if len(f) == 3]
        if triangles:
            el = _add_tessellated(model, ctx, placement, coords, triangles, name, "IfcBuildingElementProxy")
            elements.append(el)
    else:
        import Import  # noqa: PLC0415

        doc = FreeCAD.newDocument("cad2ifc")
        Import.insert(str(source), doc.Name)
        for obj in doc.Objects:
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull():
                continue
            if not shape.Solids and not shape.Faces:
                continue
            bbox = shape.BoundBox
            if max(bbox.XLength, bbox.YLength, bbox.ZLength) > 1.0e9:
                continue  # 基准面等无界对象
            mesh = _shape_to_mesh(shape)
            if mesh is None:
                continue
            coords, triangles = mesh
            label = obj.Label or name
            match = classify_component(label)
            ifc_type = pick_ifc_entity_type(match)
            el = _add_tessellated(model, ctx, placement, coords, triangles, label, ifc_type)
            elements.append(el)
            if match:
                classified.append((el, match))

    if not elements:
        raise SystemExit("未从源 CAD 解析出可三角化几何")

    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        RelatedElements=elements,
        RelatingStructure=storey,
    )
    code_count = attach_sjg_classifications(model, classified)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(
        f"INFO: IFC written: {output} elements={len(elements)} "
        f"sjgClassified={len(classified)} sjgCodes={code_count}",
        file=sys.stderr,
    )
    return 0


if os.environ.get("ARCHITOKEN_IFC_INPUT"):
    raise SystemExit(main())
if __name__ == "__main__":
    raise SystemExit(main())
