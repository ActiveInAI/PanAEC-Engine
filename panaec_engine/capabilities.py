# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""PanAEC Engine top-level capability identifiers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    label: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability("bim_openbim", "BIM and openBIM"),
    Capability("cad_geometry", "CAD and engineering geometry"),
    Capability("pdf", "PDF"),
    Capability("office", "Office documents"),
    Capability("audio", "Audio"),
    Capability("video", "Video"),
    Capability("images", "Images"),
    Capability("archives", "Archives and decompression"),
    Capability("code_programming", "Code programming assets"),
)


def capability_ids() -> tuple[str, ...]:
    return tuple(capability.id for capability in CAPABILITIES)

