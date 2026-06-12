# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_dxf_to_bom.py <input.dxf> <output.json> [--csv-dir DIR] [--name NAME]

图纸(DXF)真实 BOM:ezdxf 读取模型空间,
- 块引用(INSERT)按块名计数——图纸的真实数量语义(图例/构件块统计表)
- 按图层统计实体数与线性实体图面长度(LINE/LWPOLYLINE/POLYLINE/ARC/CIRCLE)
单位如实报告图头 $INSUNITS;不臆测比例,不伪造实物量。
DWG 先经 LibreDWG dwg2dxf 转换(由包装脚本完成)。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sjg157_classify import classify_sjg157  # noqa: E402

INSUNITS_LABELS = {
    0: "无单位", 1: "英寸", 2: "英尺", 4: "毫米", 5: "厘米", 6: "米",
}


def entity_length(entity) -> float:
    kind = entity.dxftype()
    try:
        if kind == "LINE":
            return entity.dxf.start.distance(entity.dxf.end)
        if kind == "LWPOLYLINE":
            points = list(entity.get_points("xy"))
            closed = entity.closed
            total = sum(
                math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)
            )
            if closed and len(points) > 2:
                total += math.dist(points[-1], points[0])
            return total
        if kind == "POLYLINE" and entity.is_2d_polyline:
            points = [v.dxf.location for v in entity.vertices]
            return sum(points[i].distance(points[i + 1]) for i in range(len(points) - 1))
        if kind == "CIRCLE":
            return 2 * math.pi * entity.dxf.radius
        if kind == "ARC":
            span = (entity.dxf.end_angle - entity.dxf.start_angle) % 360
            return math.radians(span) * entity.dxf.radius
    except Exception:  # noqa: BLE001 - 单实体度量失败不致命
        return 0.0
    return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract drawing BOM from DXF")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--csv-dir", default=None)
    parser.add_argument("--name", default=None)
    args = parser.parse_args(argv)
    source_arg = args.source or (args.paths[0] if args.paths else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required")
    source, output = Path(source_arg), Path(output_arg)

    started = time.time()
    doc = ezdxf.readfile(str(source))
    msp = doc.modelspace()
    insunits = int(doc.header.get("$INSUNITS", 0))
    unit_label = INSUNITS_LABELS.get(insunits, f"INSUNITS={insunits}")

    block_counts: Counter[str] = Counter()
    block_layers: dict[str, Counter[str]] = defaultdict(Counter)
    layer_entities: Counter[str] = Counter()
    layer_length: dict[str, float] = defaultdict(float)
    total_entities = 0

    for entity in msp:
        total_entities += 1
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        layer_entities[layer] += 1
        if entity.dxftype() == "INSERT":
            block_name = entity.dxf.name
            if block_name.startswith("*"):
                continue  # 匿名块(填充/阵列内部)不算图例数量
            block_counts[block_name] += 1
            block_layers[block_name][layer] += 1
        else:
            layer_length[layer] += entity_length(entity)

    lines = []
    for index, (block, count) in enumerate(
        sorted(block_counts.items(), key=lambda kv: (-kv[1], kv[0])), start=1
    ):
        # 按块名与所在图层名做 SJG 157 语义分类
        sjg = classify_sjg157(block, *block_layers[block].keys())
        lines.append(
            {
                "lineNo": index,
                "name": block,
                "quantity": count,
                "unit": "个(块引用)",
                "quantityBasis": "DXF INSERT 块引用计数(图纸数量语义)",
                "sjgCode": sjg["code"] if sjg else "",
                "sjgCategory": sjg["category"] if sjg else "",
                "ifc": sjg["ifc"] if sjg else "",
                "layers": dict(block_layers[block]),
            }
        )

    layer_stats = [
        {
            "layer": layer,
            "entityCount": layer_entities[layer],
            "drawingLength": round(layer_length.get(layer, 0.0), 1),
            "lengthUnit": unit_label,
        }
        for layer in sorted(layer_entities, key=lambda k: -layer_entities[k])
    ]

    manifest = {
        "schema": "architoken.model_bom_manifest.v1",
        "sourceFormat": source.suffix.lower(),
        "sourcePath": str(source),
        "engine": f"ezdxf {ezdxf.__version__}",
        "projectName": args.name or source.stem,
        "reviewState": "professional_review_required",
        "quantityBasis": "dxf_insert_block_count",
        "measureBasis": "drawing_space_length",
        "drawingUnits": unit_label,
        "summary": {
            "lineCount": len(lines),
            "blockInstanceTotal": sum(block_counts.values()),
            "entityCount": total_entities,
            "layerCount": len(layer_entities),
        },
        "lines": lines,
        "layerStats": layer_stats,
        "durationSeconds": round(time.time() - started, 2),
        "notes": [
            "数量为模型空间 INSERT 块引用真实计数;匿名块(*开头)不计入。",
            f"长度为图面长度(图纸单位:{unit_label}),未换算实物比例;图纸无可靠比例语义时不伪造实长。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.csv_dir:
        csv_dir = Path(args.csv_dir)
        csv_dir.mkdir(parents=True, exist_ok=True)
        with (csv_dir / "bom_summary.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["行号", "块名称", "SJG编码", "SJG类目", "数量", "单位", "数量依据", "图层分布", "评审状态"])
            for line in lines:
                writer.writerow([
                    line["lineNo"], line["name"], line["sjgCode"], line["sjgCategory"],
                    line["quantity"], line["unit"],
                    line["quantityBasis"],
                    " ".join(f"{k}×{v}" for k, v in line["layers"].items()),
                    "待专业评审",
                ])
        with (csv_dir / "bom_elements.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["图层", "实体数", f"图面长度({unit_label})"])
            for stat in layer_stats:
                writer.writerow([stat["layer"], stat["entityCount"], stat["drawingLength"]])

    print(json.dumps({"status": "ok", "blocks": len(lines), "entities": total_entities}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
