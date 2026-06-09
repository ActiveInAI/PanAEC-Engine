# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""Public identity constants for PanAEC Engine."""

from .markup_native import build_markup_native_manifest
from .ofd_native import build_ofd_native_manifest

ENGINE_NAME = "PanAEC Engine"
SPDX_LICENSE = "AGPL-3.0-only"
COPYRIGHT_OWNER = "潘永胜"

__all__ = [
    "COPYRIGHT_OWNER",
    "ENGINE_NAME",
    "SPDX_LICENSE",
    "build_markup_native_manifest",
    "build_ofd_native_manifest",
]
