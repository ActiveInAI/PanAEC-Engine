# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_ifc_validate.py <input.ifc> <output.json>

真实 IFC 校验(本地,不依赖外部服务):ifcopenshell.validate 执行
schema/EXPRESS 规则检查,输出结构化报告 JSON。

报告 schema: architoken.ifc_validation_report.v1
status: passed | failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import ifcopenshell
from ifcopenshell import validate as ifc_validate

try:
    from ifctester import ids as ifctester_ids
    from ifctester import reporter as ifctester_reporter
except Exception:  # noqa: BLE001 - ifctester 可选,缺失时仅做 schema 校验
    ifctester_ids = None
    ifctester_reporter = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an IFC file with ifcopenshell")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument(
        "--ids",
        action="append",
        default=[],
        help="IDS 1.0 规则文件路径(可重复);经 ifctester 执行业务规则校验",
    )
    args = parser.parse_args(argv)

    source_arg = args.source or (args.paths[0] if len(args.paths) >= 1 else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required")
    source, output = Path(source_arg), Path(output_arg)
    if not source.is_file():
        raise SystemExit(f"IFC source is not a readable file: {source}")

    started = time.time()
    logger = ifc_validate.json_logger()
    schema = None
    fatal: str | None = None
    try:
        model = ifcopenshell.open(str(source))
        schema = str(model.schema)
        ifc_validate.validate(model, logger, express_rules=True)
    except Exception as error:  # noqa: BLE001 - 解析失败本身就是校验失败
        fatal = f"{type(error).__name__}: {error}"

    # IDS 业务规则校验(ifctester)。规则文件解析失败不吞掉:计入报告。
    ids_results: list[dict] = []
    ids_failed = False
    if args.ids and fatal is None:
        for ids_path in args.ids:
            entry: dict = {"idsPath": str(ids_path)}
            if ifctester_ids is None:
                entry["error"] = "ifctester not installed"
                ids_failed = True
                ids_results.append(entry)
                continue
            try:
                spec_set = ifctester_ids.open(str(ids_path))
                spec_set.validate(model)
                payload = ifctester_reporter.Json(spec_set).report()
                specs = payload.get("specifications", [])
                entry["title"] = payload.get("title")
                entry["specifications"] = [
                    {
                        "name": s.get("name"),
                        "status": bool(s.get("status")),
                        "totalChecks": s.get("total_checks"),
                        "totalChecksPass": s.get("total_checks_pass"),
                        "totalApplicable": s.get("total_applicable"),
                    }
                    for s in specs
                ]
                spec_failed = any(not s.get("status") for s in specs)
                entry["status"] = "failed" if spec_failed else "passed"
                ids_failed = ids_failed or spec_failed
            except Exception as error:  # noqa: BLE001
                entry["error"] = f"{type(error).__name__}: {error}"
                ids_failed = True
            ids_results.append(entry)

    statements = list(getattr(logger, "statements", []))
    errors = [
        {
            "level": str(s.get("level", "")),
            "message": str(s.get("message", ""))[:500],
            "instance": str(s.get("instance", ""))[:200],
            "attribute": str(s.get("attribute", ""))[:200],
        }
        for s in statements[: args.max_errors]
    ]
    failed = fatal is not None or len(statements) > 0 or ids_failed
    report = {
        "schema": "architoken.ifc_validation_report.v1",
        "validatorRef": f"ifcopenshell.validate {ifcopenshell.version} (schema+EXPRESS rules, local)",
        "sourcePath": str(source),
        "ifcSchema": schema,
        "status": "failed" if failed else "passed",
        "errorCount": len(statements) + (1 if fatal else 0),
        "fatalError": fatal,
        "errors": errors,
        "truncated": len(statements) > args.max_errors,
        "durationSeconds": round(time.time() - started, 2),
        "scope": (
            "schema_express_and_ids_rules" if args.ids else "schema_and_express_rules_only"
        ),
        "idsResults": ids_results,
        "notes": [
            "schema/EXPRESS 规则为本地 ifcopenshell 校验;IDS 业务规则(如提供)为本地 ifctester 校验。",
            "不包含 MVD 视图校验;buildingSMART Validate 服务可作为更深层校验接入。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "errorCount": report["errorCount"]}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
