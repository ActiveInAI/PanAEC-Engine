# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_step_to_bom.py <input.step|.igs> <output.json> [--csv-dir DIR] [--name NAME]

STEP/IGES 真实 BOM:FreeCAD(OCCT 内核)读取装配/实体结构,按产品标签
分组计数,逐实体实测体积/表面积/包围盒(OCCT 几何度量,单位 mm)。
不假设材料密度,不伪造重量。需在 freecad.cmd 解释器下运行。

manifest schema: architoken.model_bom_manifest.v1
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


def base_label(label: str) -> str:
    # FreeCAD 对重名对象追加数字后缀(Part001):按基名分组计数
    return re.sub(r"\d+$", "", label).strip() or label


def main(argv: list[str]) -> int:
    # freecadcmd 会把位置参数当文档打开,因此参数一律走环境变量传递
    import os  # noqa: PLC0415

    source_env = os.environ.get("ARCHITOKEN_BOM_INPUT", "")
    output_env = os.environ.get("ARCHITOKEN_BOM_OUTPUT", "")
    if not source_env or not output_env:
        raise SystemExit(
            "需要环境变量 ARCHITOKEN_BOM_INPUT / ARCHITOKEN_BOM_OUTPUT"
            "(可选 ARCHITOKEN_BOM_CSV_DIR / ARCHITOKEN_BOM_NAME)",
        )
    source = Path(source_env)
    output = Path(output_env)
    csv_dir_env = os.environ.get("ARCHITOKEN_BOM_CSV_DIR", "")
    csv_dir = Path(csv_dir_env) if csv_dir_env else None
    name = os.environ.get("ARCHITOKEN_BOM_NAME") or source.stem
    if not source.is_file():
        raise SystemExit(f"source is not a readable file: {source}")

    started = time.time()
    import FreeCAD  # noqa: PLC0415 - 仅在 freecad.cmd 下可用
    import Import  # noqa: PLC0415

    doc = FreeCAD.newDocument("bom")
    Import.insert(str(source), doc.Name)

    items = []
    for obj in doc.Objects:
        type_id = getattr(obj, "TypeId", "")
        # 基准几何(原点/基准面/基准轴)不是零件,排除
        if type_id.startswith(("App::Origin", "App::Plane", "App::Line", "App::Part")):
            continue
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        if not shape.Solids and not shape.Faces:
            continue
        bbox = shape.BoundBox
        # 无限/超界包围盒(基准平面等)排除,不污染度量
        if max(bbox.XLength, bbox.YLength, bbox.ZLength) > 1.0e9:
            continue
        items.append(
            {
                "label": obj.Label,
                "baseLabel": base_label(obj.Label),
                "solids": len(shape.Solids),
                "faces": len(shape.Faces),
                # 开放曲面壳体的"体积"无意义(可为负):仅封闭实体报告体积
                "volumeMm3": round(float(shape.Volume), 1) if shape.Solids else None,
                "areaMm2": round(float(shape.Area), 1),
                "bboxMm": [
                    round(bbox.XLength, 1),
                    round(bbox.YLength, 1),
                    round(bbox.ZLength, 1),
                ],
            }
        )

    if not items:
        raise SystemExit("OCCT 未解析出任何实体/面几何")

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item["baseLabel"]].append(item)

    lines = []
    for index, (label, members) in enumerate(
        sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])), start=1
    ):
        volumes = [m["volumeMm3"] for m in members if m["volumeMm3"] is not None]
        lines.append(
            {
                "lineNo": index,
                "name": label,
                "quantity": len(members),
                "unit": "PCS",
                "quantityBasis": "OCCT 产品标签分组计数",
                "volumeMm3Avg": round(sum(volumes) / len(volumes), 1) if volumes else None,
                "bboxMm": members[0]["bboxMm"],
                "measureBasis": "OCCT 实体几何实测(体积/表面积/包围盒)",
            }
        )

    manifest = {
        "schema": "architoken.model_bom_manifest.v1",
        "sourceFormat": source.suffix.lower(),
        "sourcePath": str(source),
        "engine": f"FreeCAD {'.'.join(FreeCAD.Version()[:3])} / OCCT",
        "projectName": name,
        "reviewState": "professional_review_required",
        "quantityBasis": "occt_product_label_count",
        "measureBasis": "occt_solid_geometry",
        "summary": {
            "lineCount": len(lines),
            "elementCount": len(items),
            "totalQuantity": len(items),
            "totalVolumeMm3": round(
                sum(i["volumeMm3"] for i in items if i["volumeMm3"] is not None), 1
            ),
            "solidElementCount": sum(1 for i in items if i["volumeMm3"] is not None),
        },
        "lines": lines,
        "elements": items,
        "durationSeconds": round(time.time() - started, 2),
        "notes": [
            "数量为 OCCT 装配/产品标签分组的真实实体计数;体积/表面积/包围盒为 OCCT 几何实测(mm)。",
            "STEP/IGES 无材料密度语义,不计算重量,不伪造缺失数据。",
            "开放曲面模型(常见于 IGES)无封闭实体时体积留空,不报告无意义量。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if csv_dir:
        csv_dir.mkdir(parents=True, exist_ok=True)
        with (csv_dir / "bom_summary.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["行号", "名称", "数量", "单位", "数量依据", "平均体积mm3", "包围盒mm", "度量依据", "评审状态"])
            for line in lines:
                writer.writerow([
                    line["lineNo"], line["name"], line["quantity"], line["unit"],
                    line["quantityBasis"], line["volumeMm3Avg"],
                    "x".join(str(v) for v in line["bboxMm"]),
                    line["measureBasis"], "待专业评审",
                ])
        with (csv_dir / "bom_elements.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["标签", "实体数", "面数", "体积mm3", "表面积mm2", "包围盒mm"])
            for item in items:
                writer.writerow([
                    item["label"], item["solids"], item["faces"],
                    item["volumeMm3"], item["areaMm2"],
                    "x".join(str(v) for v in item["bboxMm"]),
                ])

    print(json.dumps({"status": "ok", "lines": len(lines), "elements": len(items)}), file=sys.stderr)
    return 0


# freecadcmd 执行脚本时 __name__ 不是 "__main__":只要喂了输入环境变量就执行
import os as _os  # noqa: E402

if _os.environ.get("ARCHITOKEN_BOM_INPUT"):
    raise SystemExit(main(sys.argv))
if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
