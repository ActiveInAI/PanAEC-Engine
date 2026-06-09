# PanAEC Engine Architecture

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

## Identity

PanAEC Engine is the independent engine name for the engineering asset runtime previously referred to internally as Prengine. New user-facing code, docs, APIs, and registries should use PanAEC Engine.

## Domains

The engine covers nine top-level domains:

1. BIM and openBIM
2. CAD and engineering geometry
3. PDF and fixed-layout documents, including OFD
4. Office documents, including ODF
5. Audio
6. Video
7. Images
8. Archives and decompression
9. Code programming assets

## Pipeline

```text
Source File
  -> Intake
  -> Type Registry
  -> Safety Scanner
  -> Adapter Route
  -> Parser or Converter
  -> Derivative Builder
  -> Schema Validator
  -> Rule Checker
  -> Audit Record
  -> Viewer, API, SDK, or Workflow Output
```

## Core Contracts

- Every source file has a stable source ID and checksum.
- Every route declares its adapter, license boundary, command or service, input type, output type, and failure mode.
- Every derivative declares source ID, adapter ID, unit system, coordinate system, schema version, timestamp, and validation state.
- Browser preview is not semantic truth unless the registered route says it is.
- Proprietary source formats need lawful adapters and must not be silently treated as open formats.
- Native display routes must keep source package/object identity. Derivative routes must be labelled as derivative, export, thumbnail, index, OCR, or fallback.

## OFD And ODF Contracts

OFD support starts with GB/T 33190-2016 source-package inspection. The engine reads OFD package entries, document roots, page content XML, public resources, signatures, and text objects without creating a PDF/image/OCR derivative.

ODF support includes `.odt`, `.ods`, `.odp`, `.odg`, and `.odb`. Online source-bound viewing/editing should prefer Collabora WOPI or another native OpenDocument runtime. LibreOffice CLI exports, PDF previews, images, and text extraction are derivative or batch routes, not native ODF display.

Digital seal validation, electronic invoice semantics, and regulated submission readiness require dedicated standards adapters and cannot be inferred from source-package opening alone.

## Code Programming Boundary

Code-programming support includes repository indexing, source parsing, dependency manifest reading, generated SDKs, scripts, notebooks, static analysis, code review evidence, test reports, and sandboxed execution.

It does not allow arbitrary unsandboxed execution. Any execution route must declare:

- sandbox image or runtime
- resource limits
- allowed filesystem roots
- network policy
- secret policy
- command allowlist
- audit log location
