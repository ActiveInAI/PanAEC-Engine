# PanAEC Engine

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

PanAEC Engine is an open engineering intelligence engine for AEC, CAD, document, media, archive, and code-programming assets.

The engine is designed as an independent open-source project. It replaces the previous internal Prengine naming and establishes a broader PanAEC scope: BIM, CAD, PDF, Office, audio, video, images, decompression/archive processing, and code-programming content.

## License

PanAEC Engine is licensed under the GNU Affero General Public License version 3 only (`AGPL-3.0-only`).

This is the strict network-copyleft open-source license used by this project. If PanAEC Engine is modified and served over a network, the corresponding source code for the modified version must be made available under the same license terms.

The initial copyright owner is 潘永胜 personally. Hosting this repository under the `ActiveInAI` GitHub account does not transfer copyright ownership to the account, company, platform, contributor, user, or downstream distributor unless a signed written copyright assignment says so.

ArchIToken is authorized by the copyright owner 潘永胜 to use, integrate, deploy, and call PanAEC Engine as a first-party engine project. This authorization does not transfer PanAEC Engine copyright ownership. Public third-party use remains governed by `AGPL-3.0-only` unless a separate signed written license says otherwise.

## Scope

PanAEC Engine covers these asset and workflow domains:

- BIM and openBIM: IFC, IDS, BCF, COBie, gbXML, OpenUSD/USD/USDA/USDC/USDZ, 3D Tiles (`tileset.json`, B3DM, I3DM, PNTS, CMPT), Revit/RVT through lawful adapters, SketchUp/SKP through lawful adapters, Rhino/3DM through lawful adapters, property sets, quantities, classifications, approvals, and audit trails.
- CAD and engineering geometry: DWG, DXF, STEP, IGES, BREP, mesh, point cloud, glTF/GLB engineering scene assets, drawing layers, blocks, dimensions, snapping, measurement, redlines, coordinates, and unit systems.
- PDF and fixed-layout documents: PDF and OFD source package reading, text extraction, page rendering, vector inspection, annotations, signatures, compliance review, drawing sheet indexing, and controlled OCR routes. OFD follows GB/T 33190-2016 and must not be silently replaced by PDF/image/OCR derivatives.
- Office documents: Word, Excel, PowerPoint, OpenDocument (`.odt`, `.ods`, `.odp`, `.odg`, `.odb`), tables, formulas, tracked changes, comments, templates, and report generation.
- Audio: transcription, diarization, translation, time-coded notes, meeting records, evidence packaging, and searchable metadata.
- Video: keyframes, captions, scene segmentation, inspection records, progress evidence, safety review, and searchable metadata.
- Images: raster inspection, EXIF metadata, OCR, segmentation, annotation, defect evidence, thumbnails, and controlled derivative generation.
- Archives and decompression: ZIP, 7z, tar, gzip, nested package inspection, safe extraction, manifesting, checksums, and malware/suspicious-content boundaries.
- Code programming assets: source code, repositories, XML, HTML, XHTML, TXT, AST/markup parsing, dependency manifests, generated SDKs, scripts, notebooks, build/test results, static analysis, code review evidence, and sandboxed execution boundaries.

## Principles

- Source-truth first: never claim semantic BIM, CAD, PDF, Office, media, archive, or code correctness from a visual fallback alone.
- Native before derivative: source formats must be opened through source-bound runtimes or lawful adapters; PDF, image, OCR, HTML, GLB, IFC, or text exports must be labelled as derivatives.
- Adapter boundaries: proprietary formats must route through lawful adapters, licensed sidecars, or user-provided conversion commands.
- OpenBIM compatibility: BIM semantics must respect IFC, IDS, BCF, buildingSMART, and jurisdiction-specific professional standards.
- Auditability: every derivative must preserve source file identity, route, adapter, unit, coordinate, checksum, timestamp, and reviewer state.
- Security: archive extraction, media processing, PDF parsing, Office macro handling, and code execution are isolated and bounded.
- Registry over hardcoding: file types, engines, renderers, capabilities, schemas, and workflows are registered data, not scattered enums.

## Repository Layout

```text
panaec_engine/               Minimal Python package and public constants
tools/                       panaec-* CLI toolchain: conversion, BOM, enrichment, validation, editing
data/                        SJG 157-2024 semantic dictionary (single source of truth)
registry/capabilities.json   Capability registry for supported domains
registry/tools.json          Tool registry: commands, routes, runtimes, report schemas
schemas/                     JSON Schemas for registries and contracts
docs/                        Architecture, adapter boundary, and toolchain documents
tests/                       Validation tests (heavy runtimes auto-skip when absent)
```

## Status

This repository is the public PanAEC Engine starting point. It establishes the license, copyright owner, capability boundaries, naming contract, and initial runtime contracts.

The current source runtime includes a native OFD package reader that opens GB/T 33190-2016 source packages directly and exposes source XML page/text objects without creating PDF, image, OCR, text, or HTML derivatives. Full OFD digital seal validation and invoice semantics still require a dedicated OFD runtime adapter.

The current source runtime also includes a native XML/HTML/XHTML/TXT source reader. It reads source bytes, checksum, encoding, structure, links, titles, and text previews directly without creating PDF, image, OCR, HTML, or text derivatives.

The repository now also ships the PanAEC conversion and quantity toolchain under `tools/`, registered in `registry/tools.json` and documented in `docs/TOOLCHAIN.md`: real-geometry conversion to IFC4 from DWG (LibreDWG native JSON route), DXF, STEP/IGES/STL (FreeCAD/OCCT), Rhino 3DM, and SketchUp SKP (licensed sidecar); measured-quantity bill of materials from IFC, STEP/IGES, DXF/DWG drawings, PDF drawing sheets, and OpenUSD scenes; SJG 157-2024 semantic classification with proxy-to-real-type IFC enrichment; and local IFC validation and atomic IFC editing with structured reports.
