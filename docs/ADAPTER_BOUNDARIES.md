# Adapter Boundaries

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

PanAEC Engine separates open formats, browser-readable formats, proprietary formats, and executable assets.

## Open Or Direct Routes

These may be parsed directly when the implementation and dependency licenses are compatible:

- IFC, IDS, BCF, gbXML, CSV, JSON, XML, Markdown, plain text
- ODF source packages: ODT, ODS, ODP, ODG, and ODB through source-bound office runtimes such as Collabora WOPI
- OFD source packages according to GB/T 33190-2016 for package, document, page, resource, text-object, and signature manifest inspection
- GLB/glTF when used as visual or derivative output
- OpenUSD/USDZ when a compatible runtime is available
- ZIP and other archives only through bounded safe extraction
- Common image, audio, and video metadata through compatible parsers

## Native And Derivative Display

Native display is source-bound. It reads the source format structure, pages, objects, resources, fonts, coordinates, units, selection identity, save boundary, checksum, and audit state.

Derivative display is not native display. PDF, images, OCR text, HTML, Markdown, GLB, IFC, screenshots, thumbnails, or extracted text may be useful for indexing, audit, compatibility, export, or fallback, but they must be labelled as derivatives.

Required rules:

- OFD native display must read the OFD source package and GB/T 33190-2016 page/resource/signature structures. OFD-to-PDF, OFD-to-image, OCR, or extracted text is derivative.
- ODF native display must read the OpenDocument source package. ODT, ODS, ODP, ODG, and ODB should prefer Collabora WOPI or another source-bound office runtime.
- Missing native runtime, sidecar, licensed adapter, or browser engine must be reported as unavailable, adapter-required, blocked, or failed.
- A derivative preview must never be named or reported as source-native support.

## Licensed Or External Adapter Routes

These require lawful adapters, user-provided commands, or licensed services:

- RVT/RFA
- SKP
- 3DM when semantic conversion is required
- DWG when native DWG interpretation is required
- Proprietary Office features beyond open document parsing
- OFD digital seal validation, invoice semantics, and government/business compliance checks until a dedicated GB/T 33190-2016 runtime adapter is connected
- Vendor-specific media codecs when licenses require it

## Code Execution Routes

Code execution is never a plain parser. It is an adapter route with sandbox controls.

Required controls:

- command allowlist
- CPU, memory, process, and time limits
- disabled or policy-controlled network
- isolated temporary workspace
- no host credential access
- immutable audit record

## Failure Rules

- A visual fallback cannot be reported as a semantic conversion.
- A failed proprietary adapter cannot be hidden by a GLB preview.
- A PDF/image/OCR derivative cannot be reported as native OFD, ODF, Office, BIM, CAD, media, archive, or code display.
- Missing validator evidence cannot be called compliant.
- A code generation result cannot be called passing unless tests actually ran and passed.
