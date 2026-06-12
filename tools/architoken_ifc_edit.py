# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_ifc_edit.py <input.ifc> <output.ifc> --ops <ops.json> --report <report.json>

真实 IFC 构件属性编辑(ifcopenshell):
- 直接属性:Name / Description / Tag / ObjectType / LongName(白名单)
- 属性集:写入/更新指定 IfcPropertySet 中的 IfcPropertySingleValue

原子语义:任何一个操作失败(GlobalId 不存在、属性不在白名单等)则整体失败,
不写输出文件,不允许部分生效。报告 schema: architoken.ifc_edit_report.v1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as element_util
from ifcopenshell.api import run as api_run

ALLOWED_ATTRIBUTES = ("Name", "Description", "Tag", "ObjectType", "LongName")


def apply_operation(model: ifcopenshell.file, op: dict) -> dict:
    global_id = str(op.get("globalId") or "").strip()
    if not global_id:
        raise ValueError("operation missing globalId")
    try:
        element = model.by_guid(global_id)
    except Exception as error:  # noqa: BLE001
        raise ValueError(f"GlobalId 不存在: {global_id}") from error

    changes: list[str] = []

    attributes = op.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise ValueError(f"{global_id}: attributes 必须是对象")
    for name, value in attributes.items():
        if name not in ALLOWED_ATTRIBUTES:
            raise ValueError(f"{global_id}: 属性 {name} 不在可编辑白名单 {ALLOWED_ATTRIBUTES}")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{global_id}: 属性 {name} 只接受字符串或 null")
        try:
            old = getattr(element, name, None)
            setattr(element, name, value)
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"{global_id}: 属性 {name} 不适用于 {element.is_a()}: {error}") from error
        changes.append(f"{name}: {old!r} -> {value!r}")

    pset_spec = op.get("propertySet")
    if pset_spec is not None:
        if not isinstance(pset_spec, dict):
            raise ValueError(f"{global_id}: propertySet 必须是对象")
        pset_name = str(pset_spec.get("name") or "").strip()
        properties = pset_spec.get("properties")
        if not pset_name or not isinstance(properties, dict) or not properties:
            raise ValueError(f"{global_id}: propertySet 需要 name 与非空 properties")
        for key, value in properties.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"{global_id}: 属性集值 {key} 类型不支持: {type(value).__name__}")
        existing = element_util.get_psets(element, psets_only=True)
        if pset_name in existing and "id" in existing[pset_name]:
            pset = model.by_id(existing[pset_name]["id"])
        else:
            pset = api_run("pset.add_pset", model, product=element, name=pset_name)
        api_run("pset.edit_pset", model, pset=pset, properties=dict(properties))
        changes.append(f"pset {pset_name}: {sorted(properties.keys())}")

    if not changes:
        raise ValueError(f"{global_id}: 操作为空(无 attributes 也无 propertySet)")

    return {
        "globalId": global_id,
        "ifcClass": element.is_a(),
        "changes": changes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Edit IFC element attributes/psets")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--ops", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    source_arg = args.source or (args.paths[0] if len(args.paths) >= 1 else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required")
    source, output = Path(source_arg), Path(output_arg)
    report_path = Path(args.report)

    started = time.time()
    payload = json.loads(Path(args.ops).read_text(encoding="utf-8"))
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SystemExit("ops.json 缺少非空 operations 数组")

    model = ifcopenshell.open(str(source))
    applied: list[dict] = []
    error_message: str | None = None
    try:
        for op in operations:
            applied.append(apply_operation(model, op))
    except ValueError as error:
        error_message = str(error)

    report = {
        "schema": "architoken.ifc_edit_report.v1",
        "editorRef": f"ifcopenshell {ifcopenshell.version} (attribute+pset edit, atomic)",
        "sourcePath": str(source),
        "status": "failed" if error_message else "applied",
        "error": error_message,
        "operationCount": len(operations),
        "applied": applied if not error_message else [],
        "durationSeconds": round(time.time() - started, 2),
        "notes": [
            "编辑为原子操作:任一操作失败则不产出新文件,不允许部分生效。",
            "可编辑直接属性白名单:Name/Description/Tag/ObjectType/LongName;属性集走 IfcPropertySingleValue。",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if error_message:
        print(f"ERROR: {error_message}", file=sys.stderr)
        return 4

    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(json.dumps({"status": "applied", "operations": len(applied)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
