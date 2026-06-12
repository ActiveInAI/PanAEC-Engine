# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""architoken_ifc_enrich.py <in.ifc> <out.ifc>

后处理 IFC:按构件名做 SJG 157 分类,为命中构件加 IfcClassificationReference;
命中具体类型的 IfcBuildingElementProxy 重建为真实 IFC 类型(保留几何/放置/关联)。
用于外部转换器(如 RVT2IFC)输出的语义增补。原地不改源,写到 out。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import ifcopenshell

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_semantic_enrich import upgrade_proxies_and_classify  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: architoken_ifc_enrich.py <in.ifc> <out.ifc>")
    source, output = Path(argv[0]), Path(argv[1])
    if not source.is_file():
        raise SystemExit(f"IFC source not readable: {source}")
    model = ifcopenshell.open(str(source))
    stats = upgrade_proxies_and_classify(model)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(json.dumps({"status": "ok", **stats}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
