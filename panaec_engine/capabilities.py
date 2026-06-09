# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""PanAEC Engine top-level capability identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Capability:
    id: str
    label: str


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry" / "capabilities.json"


def _load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _capabilities_from_registry() -> tuple[Capability, ...]:
    registry = _load_registry()
    return tuple(
        Capability(capability["id"], capability["label"])
        for capability in registry["capabilities"]
    )


def _format_capability_ids_from_registry() -> dict[str, str]:
    registry = _load_registry()
    mapping: dict[str, str] = {}
    for capability in registry["capabilities"]:
        capability_id = capability["id"]
        for format_id in capability["formats"]:
            normalized = str(format_id).strip().lower().lstrip(".")
            if not normalized:
                continue
            if normalized in mapping:
                raise ValueError(f"Duplicate format in PanAEC registry: {normalized}")
            mapping[normalized] = capability_id
    return mapping


CAPABILITIES: tuple[Capability, ...] = _capabilities_from_registry()
FORMAT_CAPABILITY_IDS: dict[str, str] = _format_capability_ids_from_registry()


def capability_ids() -> tuple[str, ...]:
    return tuple(capability.id for capability in CAPABILITIES)


def capability_id_for_extension(extension: str) -> str | None:
    normalized = extension.strip().lower().lstrip(".")
    if not normalized:
        return None
    return FORMAT_CAPABILITY_IDS.get(normalized)


def capability_id_for_filename(filename: str) -> str | None:
    normalized = filename.strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    if not normalized:
        return None
    if normalized in FORMAT_CAPABILITY_IDS:
        return FORMAT_CAPABILITY_IDS[normalized]
    if "." not in normalized:
        return FORMAT_CAPABILITY_IDS.get(normalized)
    return capability_id_for_extension(normalized.rsplit(".", 1)[-1])
