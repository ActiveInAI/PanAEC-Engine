// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 潘永胜
// architoken_usd_to_bom.mjs <input.usd*> <output.json> [--csv-dir DIR] [--name NAME]
// USD/USDZ 真实 BOM:three.js USDLoader/USDZLoader(与文件查看器同一解析器)
// 在 Node 原生解析场景图,按几何数据块分组统计实例数与包围盒。
// 运行目录需为 03-frontend(解析 three 依赖)。

import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join, basename } from "node:path";

const args = process.argv.slice(2);
const input = args[0];
const output = args[1];
const csvDir = args.includes("--csv-dir") ? args[args.indexOf("--csv-dir") + 1] : null;
const name = args.includes("--name") ? args[args.indexOf("--name") + 1] : null;
if (!input || !output) {
  console.error("usage: architoken_usd_to_bom.mjs <input> <output.json> [--csv-dir DIR] [--name NAME]");
  process.exit(2);
}

const started = Date.now();
// BOM 只统计几何,不需要贴图:给 Node 环境补最小 DOM 垫片,
// 让贴图加载安静地"永不完成"而不是抛异常。
globalThis.Image = class {
  constructor() { this.style = {}; }
  addEventListener() {}
  removeEventListener() {}
  setAttribute() {}
  set src(_) {}
};
globalThis.document = globalThis.document || {
  createElementNS: () => new globalThis.Image(),
  createElement: () => new globalThis.Image(),
};

// ESM 裸名解析基于脚本位置:three 依赖在前端目录,按绝对路径导入
const { pathToFileURL } = await import("node:url");
const frontendDir = process.env.ARCHITOKEN_FRONTEND_DIR || join(new URL("..", import.meta.url).pathname);
const threeBase = join(frontendDir, "node_modules", "three");
const { USDZLoader } = await import(
  pathToFileURL(join(threeBase, "examples/jsm/loaders/USDZLoader.js")).href
);
const { USDLoader } = await import(
  pathToFileURL(join(threeBase, "examples/jsm/loaders/USDLoader.js")).href
);
const { Box3, Vector3 } = await import(
  pathToFileURL(join(threeBase, "build/three.module.js")).href
);

const buffer = (await readFile(input)).buffer;
const lower = input.toLowerCase();
const loader = lower.endsWith(".usdz") ? new USDZLoader() : new USDLoader();
const scene = loader.parse(buffer);

const groups = new Map();
let totalMeshes = 0;
let totalTriangles = 0;
scene.updateMatrixWorld(true);
scene.traverse((object) => {
  if (!object.isMesh || !object.geometry) return;
  totalMeshes += 1;
  const geometry = object.geometry;
  const triangles = geometry.index
    ? geometry.index.count / 3
    : (geometry.attributes.position?.count ?? 0) / 3;
  totalTriangles += triangles;
  const key = geometry.uuid;
  if (!groups.has(key)) groups.set(key, { name: object.name || "mesh", triangles, members: [] });
  const box = new Box3().setFromObject(object);
  const size = new Vector3();
  if (!box.isEmpty()) box.getSize(size);
  groups.get(key).members.push({
    object: object.name || "(unnamed)",
    size: [size.x, size.y, size.z].map((v) => Math.round(v * 10000) / 10000),
  });
});

if (totalMeshes === 0) {
  console.error("USD 场景未解析出任何网格对象");
  process.exit(3);
}

const lines = [...groups.values()]
  .sort((a, b) => b.members.length - a.members.length || a.name.localeCompare(b.name))
  .map((group, index) => ({
    lineNo: index + 1,
    name: group.name,
    quantity: group.members.length,
    unit: "实例",
    quantityBasis: "USD 几何数据块共享实例计数(three.js USDLoader,与查看器同源)",
    trianglesPerInstance: Math.round(group.triangles),
    size: group.members[0].size,
    measureBasis: "世界包围盒(场景单位,未换算)",
  }));

const manifest = {
  schema: "architoken.model_bom_manifest.v1",
  sourceFormat: lower.slice(lower.lastIndexOf(".")),
  sourcePath: input,
  engine: "three.js USDLoader/USDZLoader(与文件查看器同一解析器)",
  projectName: name || basename(input).replace(/\.[^.]+$/, ""),
  reviewState: "professional_review_required",
  quantityBasis: "usd_geometry_instance_count",
  measureBasis: "world_bbox_scene_units",
  summary: {
    lineCount: lines.length,
    elementCount: totalMeshes,
    totalQuantity: totalMeshes,
    totalTriangles: Math.round(totalTriangles),
  },
  lines,
  durationSeconds: Math.round((Date.now() - started) / 10) / 100,
  notes: [
    "数量为 USD 场景几何实例真实计数(共享几何数据块=实例化引用);解析器与浏览器查看器同源。",
    "尺寸为世界包围盒(场景单位);USD 无材料密度语义,不计算重量。",
  ],
};

await mkdir(join(output, ".."), { recursive: true }).catch(() => {});
await writeFile(output, JSON.stringify(manifest, null, 2), "utf8");

if (csvDir) {
  await mkdir(csvDir, { recursive: true });
  const rows = [
    ["行号", "构件/几何", "数量", "单位", "数量依据", "单实例三角面", "包围盒(场景单位)", "评审状态"],
    ...lines.map((line) => [
      line.lineNo, line.name, line.quantity, line.unit, line.quantityBasis,
      line.trianglesPerInstance, line.size.join("x"), "待专业评审",
    ]),
  ];
  const csv = "﻿" + rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(",")).join("\n");
  await writeFile(join(csvDir, "bom_summary.csv"), csv, "utf8");
}

console.error(JSON.stringify({ status: "ok", lines: lines.length, meshes: totalMeshes }));
