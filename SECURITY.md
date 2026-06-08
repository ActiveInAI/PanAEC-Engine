# Security

SPDX-License-Identifier: AGPL-3.0-only

Copyright (C) 2026 潘永胜

PanAEC Engine handles untrusted files. Treat every input as hostile until validated.

## High-Risk Areas

- Archive extraction and decompression
- PDF parsing and OCR
- Office documents, especially macros and external links
- Media codecs and metadata parsers
- CAD/BIM proprietary adapters
- Code repositories, notebooks, scripts, generated code, and build/test commands

## Required Controls

- Use bounded extraction limits for archives.
- Keep macro execution disabled unless an explicit isolated workflow enables it.
- Run code-programming execution only in an isolated sandbox with resource limits.
- Record checksums and provenance for every derivative.
- Do not load proprietary adapters without license review.
- Do not expose local filesystem paths, tokens, credentials, or host secrets in derivatives or logs.

## Reporting

Open a private security report or contact the maintainer before publishing exploit details.

