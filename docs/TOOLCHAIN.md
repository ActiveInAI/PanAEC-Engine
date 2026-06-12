# PanAEC Engine Toolchain

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

The `tools/` directory contains the PanAEC conversion, quantity-takeoff, enrichment, validation, and editing command line tools. Every tool is registered in `registry/tools.json` (registry over hardcoding); the registry entry is the contract for inputs, outputs, route type, runtime dependencies, and report schema.

## Command Contract

The public command contract is the `panaec-*` CLI name. Each CLI is a thin Bash wrapper that resolves its runtime and delegates to the implementation script next to it.

Naming note: the implementation scripts, environment variables (`ARCHITOKEN_*`), and report schema identifiers (`architoken.*`) keep the ABI of the authorized first-party integration (see README: ArchIToken is authorized by the copyright owner to integrate PanAEC Engine). They are kept verbatim so the public tools and the first-party deployment stay byte-compatible and testable against each other.

## Routes

- **Conversion to IFC**: `panaec-dwg-to-ifc` (LibreDWG `dwgread` native JSON dump — the `dwg2dxf` path is not used for IFC because its geometry output is unreliable), `panaec-dxf-to-ifc` (ezdxf), `panaec-cad-to-ifc` (STEP/IGES/STL via FreeCAD/OCCT), `panaec-3dm-to-ifc` (rhino3dm), `panaec-skp-to-ifc` (licensed SketchUp sidecar over HTTP).
- **Quantity takeoff / BOM**: `panaec-ifc-to-bom` (measured geometry quantities via ifcopenshell), `panaec-step-to-bom` (FreeCAD/OCCT), `panaec-drawing-to-bom` (DXF block references; DWG through a real LibreDWG conversion), `panaec-pdf-to-bom` (verbatim vector-text table export with page provenance), `panaec-usd-to-bom` (three.js USD loaders in Node — the same parser as the source viewer).
- **IFC semantics**: `panaec-ifc-enrich` upgrades proxies to real IFC entity types and attaches SJG 157-2024 classification references; `tools/sjg157_classify.py` plus `data/sjg157_semantic_dictionary.json` are the single source of truth for the name → IFC type → SJG code mapping.
- **IFC quality**: `panaec-ifc-validate` (local schema/EXPRESS validation report), `panaec-ifc-edit` (atomic whitelisted attribute and property-set edits; no partial writes).

## Honesty Rules

These tools follow the engine principles in the README:

- A converted IFC, GLB, CSV, or JSON output is a derivative; the uploaded file stays the source of record and every report carries provenance (engine, route, source identity).
- Pure 2D drawings are never faked into 3D geometry; scanned PDFs without vector text are reported as having no extractable tables.
- Proprietary formats (DWG, SKP, RVT) go through lawful adapters or user-provided licensed sidecars only.
- Validation and editing never claim success on partial results; a failed operation fails the whole run.

## Runtime Dependencies

The registry-only CI validates JSON, the registries, and the pure-Python classifier tests. The conversion tools additionally need, per `registry/tools.json`: `ifcopenshell`, `numpy`, `ezdxf`, `rhino3dm`, `pdfplumber`, LibreDWG (`dwgread`, `dwg2dxf`), FreeCAD (`freecadcmd`), Node with three.js, and — for SKP — a user-provided licensed SketchUp sidecar reachable over HTTP (`SKETCHUP_ADAPTER_URL` or `ARCHITOKEN_SKP_ADAPTER_URL`).

Wrapper environment overrides:

- `ARCHITOKEN_WORKER_PYTHON` — Python interpreter (default: repo `.venv/bin/python`, then `python3` on PATH).
- `LIBREDWG_BIN_DIR` / `ARCHITOKEN_LIBREDWG_BIN` — LibreDWG binaries (default: PATH).
- `FREECAD_CMD_BIN` — freecadcmd location (default: `/snap/bin/freecad.cmd`).
- `ARCHITOKEN_CAD_IFC_STAGE_ROOT` / `ARCHITOKEN_STEP_BOM_STAGE_ROOT` — visible staging area for snap-confined FreeCAD (default: `~/.cache/panaec/runtime-stage`).
- `ARCHITOKEN_FRONTEND_DIR` — directory whose `node_modules/three` provides the USD loaders (default: repository root).
