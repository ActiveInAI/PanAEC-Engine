# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""ArchIToken 3DM to IFC sidecar.

This command reads Rhino/OpenNURBS 3DM geometry through rhino3dm and writes a
real IFC4 tessellated geometry exchange file through IfcOpenShell. It preserves
the 3DM file as source of record and emits IfcBuildingElementProxy objects for
geometry that has meshable 3DM data. It does not claim professional BIM semantic
classification or compliance beyond producing a readable IFC artifact.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import ifcopenshell
import rhino3dm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_semantic_enrich import (  # noqa: E402
    attach_sjg_classifications,
    classify_component,
    pick_ifc_entity_type,
)


Matrix4 = tuple[tuple[float, float, float, float], ...]
READABLE_TEXT_ALLOWED_PATTERN = re.compile(
    r"[\x20-\x7e\u3000-\u303f\uff01-\uff5e\u4e00-\u9fff°²³µ×ØøΦφ±≤≥]"
)


@dataclass
class MaterialStyle:
    name: str
    color: tuple[float, float, float, float]


@dataclass
class MeshRecord:
    name: str
    source_type: str
    coordinates: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]
    material: MaterialStyle | None = None


IDENTITY: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Rhino 3DM geometry to IFC4")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--name", default=None)
    parser.add_argument("--max-depth", type=int, default=16)
    parser.add_argument("--schema", default="IFC4")
    args = parser.parse_args(argv)

    source_arg = args.source or (args.paths[0] if len(args.paths) >= 1 else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required; pass --input/--output or positional source output paths")

    source = Path(source_arg)
    output = Path(output_arg)
    if not source.is_file():
        raise SystemExit(f"3DM source is not a readable file: {source}")

    model = rhino3dm.File3dm.Read(str(source))
    if model is None:
        raise SystemExit(f"Cannot read 3DM source: {source}")

    records = collect_mesh_records(model, max_depth=args.max_depth)
    if not records:
        raise SystemExit(
            "3DM source did not expose any meshable geometry through rhino3dm/OpenNURBS"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    write_ifc(
        output,
        records,
        project_name=args.name or source.stem,
        schema=args.schema.upper(),
    )
    parsed = ifcopenshell.open(str(output))
    summary = {
        "schema": "architoken.3dm_to_ifc_sidecar_manifest.v1",
        "sourcePath": str(source),
        "outputPath": str(output),
        "engine": "rhino3dm+ifcopenshell",
        "ifcSchema": str(getattr(parsed, "schema", args.schema.upper())),
        "elementCount": len(records),
        "triangleCount": sum(len(record.triangles) for record in records),
        "sourceOfRecord": "3dm",
        "semanticScope": "geometry_exchange_ifc",
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def collect_mesh_records(model: rhino3dm.File3dm, *, max_depth: int) -> list[MeshRecord]:
    object_by_id = {
        str(model.Objects[index].Attributes.Id): model.Objects[index]
        for index in range(len(model.Objects))
    }
    definition_by_id = {
        str(model.InstanceDefinitions[index].Id): model.InstanceDefinitions[index]
        for index in range(len(model.InstanceDefinitions))
    }
    materials = [model.Materials[index] for index in range(len(model.Materials))]
    layers = [model.Layers[index] for index in range(len(model.Layers))]

    records: list[MeshRecord] = []
    for index in range(len(model.Objects)):
        obj = model.Objects[index]
        if getattr(obj.Attributes, "IsInstanceDefinitionObject", False):
            continue
        if getattr(obj.Attributes, "Visible", True) is False:
            continue
        records.extend(
            collect_object_mesh_records(
                obj,
                object_by_id=object_by_id,
                definition_by_id=definition_by_id,
                materials=materials,
                layers=layers,
                transform=IDENTITY,
                name_prefix=object_name(obj, fallback=f"Object {index + 1}"),
                inherited_material=None,
                depth=0,
                max_depth=max_depth,
            )
        )
    return [
        record
        for record in records
        if record.coordinates and record.triangles and len(record.coordinates) >= 3
    ]


def collect_object_mesh_records(
    obj: rhino3dm.File3dmObject,
    *,
    object_by_id: dict[str, rhino3dm.File3dmObject],
    definition_by_id: dict[str, rhino3dm.InstanceDefinition],
    materials: list[rhino3dm.Material],
    layers: list[rhino3dm.Layer],
    transform: Matrix4,
    name_prefix: str,
    inherited_material: MaterialStyle | None,
    depth: int,
    max_depth: int,
) -> list[MeshRecord]:
    geometry = obj.Geometry
    material = object_material_style(obj, materials=materials, layers=layers) or inherited_material
    if isinstance(geometry, rhino3dm.InstanceReference):
        if depth >= max_depth:
            return []
        definition = definition_by_id.get(str(geometry.ParentIdefId))
        if definition is None:
            return []
        instance_transform = multiply_matrix(transform, matrix_from_transform(geometry.Xform))
        records: list[MeshRecord] = []
        for object_id in definition.GetObjectIds():
            child = object_by_id.get(str(object_id))
            if child is None:
                continue
            child_name = object_name(child, fallback=definition.Name or name_prefix)
            records.extend(
                collect_object_mesh_records(
                    child,
                    object_by_id=object_by_id,
                    definition_by_id=definition_by_id,
                    materials=materials,
                    layers=layers,
                    transform=instance_transform,
                    name_prefix=f"{name_prefix} / {child_name}",
                    inherited_material=material,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
        return records

    mesh_fragments = geometry_to_mesh_fragments(geometry, transform)
    if not mesh_fragments:
        return []

    coordinates: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for fragment_coordinates, fragment_triangles in mesh_fragments:
        offset = len(coordinates)
        coordinates.extend(fragment_coordinates)
        triangles.extend(
            (a + offset, b + offset, c + offset)
            for a, b, c in fragment_triangles
        )
    return [
        MeshRecord(
            name=safe_name(name_prefix),
            source_type=type(geometry).__name__,
            coordinates=coordinates,
            triangles=triangles,
            material=material,
        )
    ]


def geometry_to_mesh_fragments(
    geometry: object,
    transform: Matrix4,
) -> list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]]:
    if isinstance(geometry, rhino3dm.Mesh):
        fragment = mesh_to_fragment(geometry, transform)
        return [fragment] if fragment is not None else []

    if isinstance(geometry, rhino3dm.Brep):
        fragments = []
        for face_index in range(len(geometry.Faces)):
            mesh = geometry.Faces[face_index].GetMesh(rhino3dm.MeshType.Any)
            if mesh is None:
                continue
            fragment = mesh_to_fragment(mesh, transform)
            if fragment is not None:
                fragments.append(fragment)
        return fragments

    get_mesh = getattr(geometry, "GetMesh", None)
    if callable(get_mesh):
        try:
            mesh = get_mesh(rhino3dm.MeshType.Any)
        except TypeError:
            mesh = get_mesh()
        if isinstance(mesh, rhino3dm.Mesh):
            fragment = mesh_to_fragment(mesh, transform)
            return [fragment] if fragment is not None else []

    return []


def mesh_to_fragment(
    mesh: rhino3dm.Mesh,
    transform: Matrix4,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]] | None:
    if len(mesh.Vertices) < 3 or len(mesh.Faces) <= 0:
        return None
    coordinates = [
        transform_point(transform, (float(vertex.X), float(vertex.Y), float(vertex.Z)))
        for vertex in mesh.Vertices
    ]
    triangles: list[tuple[int, int, int]] = []
    for face in mesh.Faces:
        indices = [int(index) for index in face]
        if len(indices) < 3:
            continue
        if len(indices) == 3 or indices[2] == indices[-1]:
            triangles.append((indices[0], indices[1], indices[2]))
            continue
        triangles.append((indices[0], indices[1], indices[2]))
        triangles.append((indices[0], indices[2], indices[3]))
    if not triangles:
        return None
    return coordinates, triangles


def write_ifc(
    output: Path,
    records: Iterable[MeshRecord],
    *,
    project_name: str,
    schema: str,
) -> None:
    model = ifcopenshell.file(schema=schema)
    guid = ifcopenshell.guid.new

    origin = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    ref_direction = model.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0))
    world_placement = model.create_entity(
        "IfcAxis2Placement3D",
        Location=origin,
        Axis=axis,
        RefDirection=ref_direction,
    )
    context = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Body",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1.0e-5,
        WorldCoordinateSystem=world_placement,
    )
    millimeter = model.create_entity(
        "IfcSIUnit",
        UnitType="LENGTHUNIT",
        Prefix="MILLI",
        Name="METRE",
    )
    unit_assignment = model.create_entity("IfcUnitAssignment", Units=[millimeter])

    project = model.create_entity(
        "IfcProject",
        GlobalId=guid(),
        Name=project_name,
        RepresentationContexts=[context],
        UnitsInContext=unit_assignment,
    )
    site = model.create_entity("IfcSite", GlobalId=guid(), Name="3DM Source Site")
    building = model.create_entity("IfcBuilding", GlobalId=guid(), Name="3DM Source Building")
    storey = model.create_entity("IfcBuildingStorey", GlobalId=guid(), Name="3DM Geometry")
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=project, RelatedObjects=[site])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=site, RelatedObjects=[building])
    model.create_entity("IfcRelAggregates", GlobalId=guid(), RelatingObject=building, RelatedObjects=[storey])

    local_placement = model.create_entity("IfcLocalPlacement", RelativePlacement=world_placement)
    elements = []
    classified: list[tuple[ifcopenshell.entity_instance, dict]] = []
    style_cache: dict[tuple[str, tuple[float, float, float, float]], ifcopenshell.entity_instance] = {}
    material_cache: dict[str, ifcopenshell.entity_instance] = {}
    for index, record in enumerate(records, start=1):
        point_list = model.create_entity("IfcCartesianPointList3D", CoordList=record.coordinates)
        face_set = model.create_entity(
            "IfcTriangulatedFaceSet",
            Coordinates=point_list,
            CoordIndex=[tuple(face_index + 1 for face_index in triangle) for triangle in record.triangles],
        )
        shape = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=context,
            RepresentationIdentifier="Body",
            RepresentationType="Tessellation",
            Items=[face_set],
        )
        product_shape = model.create_entity(
            "IfcProductDefinitionShape",
            Representations=[shape],
        )
        # 按构件名/源类型做 SJG 157 分类:命中具体类型则升级真实 IFC 实体,否则 Proxy
        layer_name = getattr(record, "layer", "") or ""
        match = classify_component(record.name, record.source_type, layer_name)
        entity_type = pick_ifc_entity_type(match)
        element = model.create_entity(
            entity_type,
            GlobalId=guid(),
            Name=record.name or f"3DM Geometry {index}",
            ObjectType=record.source_type,
            ObjectPlacement=local_placement,
            Representation=product_shape,
        )
        if match:
            classified.append((element, match))
        if record.material:
            styled_item = ifc_style_for_material(model, style_cache, record.material)
            model.create_entity(
                "IfcStyledItem",
                Item=face_set,
                Styles=[styled_item],
                Name=record.material.name,
            )
            material_entity = ifc_material_for_style(model, material_cache, record.material)
            model.create_entity(
                "IfcRelAssociatesMaterial",
                GlobalId=guid(),
                RelatedObjects=[element],
                RelatingMaterial=material_entity,
            )
        elements.append(element)

    if elements:
        model.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=guid(),
            RelatedElements=elements,
            RelatingStructure=storey,
        )

    attach_sjg_classifications(model, classified)

    model.write(str(output))


def matrix_from_transform(transform: rhino3dm.Transform) -> Matrix4:
    return (
        (float(transform.M00), float(transform.M01), float(transform.M02), float(transform.M03)),
        (float(transform.M10), float(transform.M11), float(transform.M12), float(transform.M13)),
        (float(transform.M20), float(transform.M21), float(transform.M22), float(transform.M23)),
        (float(transform.M30), float(transform.M31), float(transform.M32), float(transform.M33)),
    )


def multiply_matrix(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(sum(left[row][k] * right[k][col] for k in range(4)) for col in range(4))
        for row in range(4)
    )


def transform_point(
    matrix: Matrix4,
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def object_name(obj: rhino3dm.File3dmObject, *, fallback: str) -> str:
    name = getattr(obj.Attributes, "Name", None)
    if isinstance(name, str) and name.strip():
        return readable_text(name, fallback=fallback)
    return fallback


def safe_name(value: str) -> str:
    return readable_text(value, fallback="3DM Geometry")[:255] or "3DM Geometry"


def readable_text(value: object, *, fallback: str = "") -> str:
    raw = str(value or "")
    replacement_count = raw.count("\ufffd")
    text = raw.replace("\ufffd", " ")
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return fallback
    compact = re.sub(r"\s+", "", text)
    bad_count = replacement_count + len(re.findall(r"[\u25a0-\u25a3\u25a8-\u25a9]", compact))
    suspicious_count = sum(
        1
        for character in compact
        if not READABLE_TEXT_ALLOWED_PATTERN.fullmatch(character)
    )
    readable_count = len(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]", compact))
    if bad_count > 0 and (len(compact) <= 12 or bad_count / max(len(compact), 1) > 0.2):
        return fallback
    if suspicious_count / max(len(compact), 1) > 0.25:
        return fallback
    if readable_count == 0:
        return fallback
    return text


def object_material_style(
    obj: rhino3dm.File3dmObject,
    *,
    materials: list[rhino3dm.Material],
    layers: list[rhino3dm.Layer],
) -> MaterialStyle | None:
    attributes = obj.Attributes
    material = material_from_attributes(attributes, materials, layers)
    material_color = color_from_material(material) if material is not None else None
    object_color = color_from_attributes(attributes, material, layers)
    color = material_color or object_color
    if color is None:
        return None

    material_name = readable_text(getattr(material, "Name", ""), fallback="")
    object_label = readable_text(getattr(attributes, "Name", ""), fallback="")
    name = material_name or object_label or "3DM Material"
    return MaterialStyle(name=name[:255], color=color)


def material_from_attributes(
    attributes: rhino3dm.ObjectAttributes,
    materials: list[rhino3dm.Material],
    layers: list[rhino3dm.Layer],
) -> rhino3dm.Material | None:
    material_index = int_index(getattr(attributes, "MaterialIndex", -1))
    material_source = str(getattr(attributes, "MaterialSource", ""))
    if "MaterialFromObject" in material_source and material_index >= 0:
        return item_at(materials, material_index)

    layer = item_at(layers, int_index(getattr(attributes, "LayerIndex", -1)))
    layer_material_index = int_index(getattr(layer, "RenderMaterialIndex", -1)) if layer else -1
    if "MaterialFromLayer" in material_source and layer_material_index >= 0:
        return item_at(materials, layer_material_index)

    if material_index >= 0:
        return item_at(materials, material_index)
    if layer_material_index >= 0:
        return item_at(materials, layer_material_index)
    return None


def color_from_attributes(
    attributes: rhino3dm.ObjectAttributes,
    material: rhino3dm.Material | None,
    layers: list[rhino3dm.Layer],
) -> tuple[float, float, float, float] | None:
    color_source = str(getattr(attributes, "ColorSource", ""))
    if "ColorFromObject" in color_source:
        return normalize_rgba(getattr(attributes, "ObjectColor", None))
    if "ColorFromMaterial" in color_source and material is not None:
        return color_from_material(material)
    if "ColorFromLayer" in color_source:
        layer = item_at(layers, int_index(getattr(attributes, "LayerIndex", -1)))
        layer_color = normalize_rgba(getattr(layer, "Color", None)) if layer else None
        if layer_color and not is_default_black_layer_color(layer, layer_color):
            return layer_color
    draw_color = getattr(attributes, "DrawColor", None)
    if callable(draw_color):
        try:
            return normalize_rgba(draw_color())
        except TypeError:
            return None
    return None


def color_from_material(material: rhino3dm.Material) -> tuple[float, float, float, float] | None:
    for attr in ("DiffuseColor", "PreviewColor"):
        color = normalize_rgba(getattr(material, attr, None))
        if color is not None:
            alpha = 1.0 - clamp(float(getattr(material, "Transparency", 0.0) or 0.0), 0.0, 1.0)
            return (color[0], color[1], color[2], min(color[3], alpha))
    return None


def normalize_rgba(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        channels = list(value)  # rhino3dm exposes colors as RGBA tuples.
    except TypeError:
        return None
    if len(channels) < 3:
        return None
    red = clamp(float(channels[0]) / 255.0, 0.0, 1.0)
    green = clamp(float(channels[1]) / 255.0, 0.0, 1.0)
    blue = clamp(float(channels[2]) / 255.0, 0.0, 1.0)
    alpha = clamp(float(channels[3]) / 255.0, 0.0, 1.0) if len(channels) >= 4 else 1.0
    return red, green, blue, alpha


def is_default_black_layer_color(
    layer: rhino3dm.Layer | None,
    color: tuple[float, float, float, float],
) -> bool:
    if layer is None:
        return False
    if any(channel > 0.001 for channel in color[:3]):
        return False
    return int_index(getattr(layer, "RenderMaterialIndex", -1)) < 0


def ifc_style_for_material(
    model: ifcopenshell.file,
    cache: dict[tuple[str, tuple[float, float, float, float]], ifcopenshell.entity_instance],
    material: MaterialStyle,
) -> ifcopenshell.entity_instance:
    key = (material.name, material.color)
    existing = cache.get(key)
    if existing is not None:
        return existing

    red, green, blue, alpha = material.color
    colour = model.create_entity(
        "IfcColourRgb",
        Name=material.name,
        Red=red,
        Green=green,
        Blue=blue,
    )
    shading = model.create_entity(
        "IfcSurfaceStyleShading",
        SurfaceColour=colour,
        Transparency=clamp(1.0 - alpha, 0.0, 1.0),
    )
    surface_style = model.create_entity(
        "IfcSurfaceStyle",
        Name=material.name,
        Side="BOTH",
        Styles=[shading],
    )
    assignment = model.create_entity(
        "IfcPresentationStyleAssignment",
        Styles=[surface_style],
    )
    cache[key] = assignment
    return assignment


def ifc_material_for_style(
    model: ifcopenshell.file,
    cache: dict[str, ifcopenshell.entity_instance],
    material: MaterialStyle,
) -> ifcopenshell.entity_instance:
    existing = cache.get(material.name)
    if existing is not None:
        return existing
    entity = model.create_entity("IfcMaterial", Name=material.name)
    cache[material.name] = entity
    return entity


def item_at(items: list, index: int):
    if index < 0 or index >= len(items):
        return None
    return items[index]


def int_index(value: object) -> int:
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


if __name__ == "__main__":
    sys.exit(main())
