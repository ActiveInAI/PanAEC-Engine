# Adapter Boundaries

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

PanAEC Engine separates open formats, browser-readable formats, proprietary formats, and executable assets.

## Open Or Direct Routes

These may be parsed directly when the implementation and dependency licenses are compatible:

- IFC, IDS, BCF, gbXML, CSV, JSON, XML, Markdown, plain text
- GLB/glTF when used as visual or derivative output
- OpenUSD/USDZ when a compatible runtime is available
- ZIP and other archives only through bounded safe extraction
- Common image, audio, and video metadata through compatible parsers

## Licensed Or External Adapter Routes

These require lawful adapters, user-provided commands, or licensed services:

- RVT/RFA
- SKP
- 3DM when semantic conversion is required
- DWG when native DWG interpretation is required
- Proprietary Office features beyond open document parsing
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
- Missing validator evidence cannot be called compliant.
- A code generation result cannot be called passing unless tests actually ran and passed.

