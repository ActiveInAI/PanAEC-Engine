# PanAEC Engine

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

PanAEC Engine is an open engineering intelligence engine for AEC, CAD, document, media, archive, and code-programming assets.

The engine is designed as an independent open-source project. It replaces the previous internal Prengine naming and establishes a broader PanAEC scope: BIM, CAD, PDF, Office, audio, video, images, decompression/archive processing, and code-programming content.

## License

PanAEC Engine is licensed under the GNU Affero General Public License version 3 only (`AGPL-3.0-only`).

This is the strict network-copyleft open-source license used by this project. If PanAEC Engine is modified and served over a network, the corresponding source code for the modified version must be made available under the same license terms.

The initial copyright owner is 潘永胜 personally. Hosting this repository under the `ActiveInAI` GitHub account does not transfer copyright ownership to the account, company, platform, contributor, user, or downstream distributor unless a signed written copyright assignment says so.

## Scope

PanAEC Engine covers these asset and workflow domains:

- BIM and openBIM: IFC, IDS, BCF, COBie, gbXML, OpenUSD/USDZ, 3D Tiles, Revit/RVT through lawful adapters, SketchUp/SKP through lawful adapters, Rhino/3DM through lawful adapters, property sets, quantities, classifications, approvals, and audit trails.
- CAD and engineering geometry: DWG, DXF, STEP, IGES, BREP, mesh, point cloud, drawing layers, blocks, dimensions, snapping, measurement, redlines, coordinates, and unit systems.
- PDF: text extraction, page rendering, vector inspection, annotations, signatures, compliance review, drawing sheet indexing, and controlled OCR routes.
- Office documents: Word, Excel, PowerPoint, OpenDocument, tables, formulas, tracked changes, comments, templates, and report generation.
- Audio: transcription, diarization, translation, time-coded notes, meeting records, evidence packaging, and searchable metadata.
- Video: keyframes, captions, scene segmentation, inspection records, progress evidence, safety review, and searchable metadata.
- Images: raster inspection, EXIF metadata, OCR, segmentation, annotation, defect evidence, thumbnails, and controlled derivative generation.
- Archives and decompression: ZIP, 7z, tar, gzip, nested package inspection, safe extraction, manifesting, checksums, and malware/suspicious-content boundaries.
- Code programming assets: source code, repositories, AST parsing, dependency manifests, generated SDKs, scripts, notebooks, build/test results, static analysis, code review evidence, and sandboxed execution boundaries.

## Principles

- Source-truth first: never claim semantic BIM, CAD, PDF, Office, media, archive, or code correctness from a visual fallback alone.
- Adapter boundaries: proprietary formats must route through lawful adapters, licensed sidecars, or user-provided conversion commands.
- OpenBIM compatibility: BIM semantics must respect IFC, IDS, BCF, buildingSMART, and jurisdiction-specific professional standards.
- Auditability: every derivative must preserve source file identity, route, adapter, unit, coordinate, checksum, timestamp, and reviewer state.
- Security: archive extraction, media processing, PDF parsing, Office macro handling, and code execution are isolated and bounded.
- Registry over hardcoding: file types, engines, renderers, capabilities, schemas, and workflows are registered data, not scattered enums.

## Repository Layout

```text
panaec_engine/               Minimal Python package and public constants
registry/capabilities.json   Capability registry for supported domains
schemas/                     JSON Schemas for registries and contracts
docs/                        Architecture and adapter boundary documents
tests/                       Minimal validation tests
```

## Status

This repository is the public PanAEC Engine starting point. It establishes the license, copyright owner, capability boundaries, and naming contract. Runtime implementations should be added as isolated modules with tests, schemas, and adapter license review.

