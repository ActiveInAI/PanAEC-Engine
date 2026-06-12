# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_pdf_to_bom.py <input.pdf> <output.json> [--csv-dir DIR] [--name NAME]

PDF 图纸 BOM:pdfplumber 提取矢量文本表格**原样导出**(图纸上印的材料表/
构件表本身就是设计方授权的数量数据)。不做语义解释、不合并、不改写单元格;
每张表标注页码与表序。扫描件(无矢量文本)如实报告无可提取表格。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import pdfplumber


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract printed tables from PDF drawings")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="source")
    parser.add_argument("--output", dest="output")
    parser.add_argument("--csv-dir", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--max-pages", type=int, default=200)
    args = parser.parse_args(argv)
    source_arg = args.source or (args.paths[0] if args.paths else None)
    output_arg = args.output or (args.paths[1] if len(args.paths) >= 2 else None)
    if not source_arg or not output_arg:
        parser.error("source and output are required")
    source, output = Path(source_arg), Path(output_arg)

    started = time.time()
    tables = []
    page_count = 0
    with pdfplumber.open(str(source)) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages[: args.max_pages], start=1):
            for table_index, table in enumerate(page.extract_tables() or [], start=1):
                rows = [
                    [(cell or "").strip() for cell in row]
                    for row in table
                    if any((cell or "").strip() for cell in row)
                ]
                if len(rows) < 2:
                    continue  # 单行"表"多为边框噪声
                tables.append(
                    {
                        "page": page_index,
                        "tableIndex": table_index,
                        "rowCount": len(rows),
                        "columnCount": max(len(r) for r in rows),
                        "header": rows[0],
                        "rows": rows,
                    }
                )

    manifest = {
        "schema": "architoken.model_bom_manifest.v1",
        "sourceFormat": ".pdf",
        "sourcePath": str(source),
        "engine": f"pdfplumber {pdfplumber.__version__}",
        "projectName": args.name or source.stem,
        "reviewState": "professional_review_required",
        "quantityBasis": "pdf_printed_table_verbatim",
        "measureBasis": "none",
        "summary": {
            "pageCount": page_count,
            "tableCount": len(tables),
            "rowTotal": sum(t["rowCount"] for t in tables),
        },
        "tables": [
            {k: t[k] for k in ("page", "tableIndex", "rowCount", "columnCount", "header")}
            for t in tables
        ],
        "durationSeconds": round(time.time() - started, 2),
        "notes": [
            "表格为图纸印刷内容的矢量文本原样提取,未做任何语义解释/合并/改写。",
            "扫描件(无矢量文本层)无法提取;需先 OCR,系统不伪造识别结果。"
            if not tables
            else "每张表带页码与表序,可对照原图核对。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.csv_dir:
        csv_dir = Path(args.csv_dir)
        csv_dir.mkdir(parents=True, exist_ok=True)
        with (csv_dir / "bom_summary.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["页码", "表序", "行数", "列数", "表头(原样)"])
            for t in tables:
                writer.writerow([
                    t["page"], t["tableIndex"], t["rowCount"], t["columnCount"],
                    " | ".join(t["header"]),
                ])
        with (csv_dir / "bom_elements.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["页码", "表序", "行号", "单元格(原样)"])
            for t in tables:
                for row_index, row in enumerate(t["rows"], start=1):
                    writer.writerow([t["page"], t["tableIndex"], row_index, *row])

    print(
        json.dumps({"status": "ok", "tables": len(tables), "pages": page_count}),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
