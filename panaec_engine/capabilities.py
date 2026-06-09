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

FORMAT_CAPABILITY_IDS: dict[str, str] = {
    "3dm": "bim_openbim",
    "7z": "archives",
    "aac": "audio",
    "avi": "video",
    "bcf": "bim_openbim",
    "bmp": "images",
    "brep": "cad_geometry",
    "c": "code_programming",
    "cobie": "bim_openbim",
    "cpp": "code_programming",
    "cs": "code_programming",
    "dng": "images",
    "doc": "office",
    "docx": "office",
    "dwg": "cad_geometry",
    "dxf": "cad_geometry",
    "flac": "audio",
    "gbxml": "bim_openbim",
    "git": "code_programming",
    "go": "code_programming",
    "gz": "archives",
    "h": "code_programming",
    "ids": "bim_openbim",
    "ifc": "bim_openbim",
    "ifczip": "bim_openbim",
    "iges": "cad_geometry",
    "igs": "cad_geometry",
    "ipynb": "code_programming",
    "java": "code_programming",
    "jpeg": "images",
    "jpg": "images",
    "js": "code_programming",
    "json": "code_programming",
    "jsx": "code_programming",
    "lock": "code_programming",
    "m4a": "audio",
    "mkv": "video",
    "mov": "video",
    "mp3": "audio",
    "mp4": "video",
    "obj": "cad_geometry",
    "odb": "office",
    "odg": "office",
    "odp": "office",
    "ods": "office",
    "odt": "office",
    "ofd": "pdf",
    "ogg": "audio",
    "pdf": "pdf",
    "ply": "cad_geometry",
    "png": "images",
    "pointcloud": "cad_geometry",
    "ppt": "office",
    "pptx": "office",
    "py": "code_programming",
    "rar": "archives",
    "raw": "images",
    "rfa": "bim_openbim",
    "rs": "code_programming",
    "rvt": "bim_openbim",
    "skp": "bim_openbim",
    "stl": "cad_geometry",
    "step": "cad_geometry",
    "stp": "cad_geometry",
    "svg": "images",
    "tar": "archives",
    "tgz": "archives",
    "tif": "images",
    "tiff": "images",
    "toml": "code_programming",
    "ts": "code_programming",
    "tsx": "code_programming",
    "wav": "audio",
    "webm": "video",
    "webp": "images",
    "xls": "office",
    "xlsx": "office",
    "yaml": "code_programming",
    "yml": "code_programming",
    "zip": "archives",
}


def capability_ids() -> tuple[str, ...]:
    return tuple(capability.id for capability in CAPABILITIES)


def capability_id_for_extension(extension: str) -> str | None:
    normalized = extension.strip().lower().lstrip(".")
    if not normalized:
        return None
    return FORMAT_CAPABILITY_IDS.get(normalized)
