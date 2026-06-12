# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜
#!/usr/bin/env python3
"""ArchIToken SKP command bridge for licensed SketchUp sidecars.

This command intentionally does not parse SKP bytes. It adapts the local
ArchIToken command ABI (`source output`) to a user-provided HTTP sidecar that is
allowed to run SketchUp Ruby, BIM-Tools IFC Manager, Yulio glTF exporter, or a
similar licensed/isolated exporter.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


IFC_MEDIA_TYPES = {"application/p21", "application/ifc", "text/plain"}
GLB_MEDIA_TYPES = {"model/gltf-binary", "application/octet-stream"}


class SkpSidecarError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bridge SKP conversion to a licensed SketchUp HTTP sidecar.",
    )
    parser.add_argument("paths", nargs="*", help="source.skp output.ifc|output.glb")
    parser.add_argument("--input", dest="input_path", help="source SKP path")
    parser.add_argument("--output", dest="output_path", help="output artifact path")
    parser.add_argument(
        "--target-format",
        choices=("ifc", "glb"),
        help="requested derivative format; defaults from output extension",
    )
    parser.add_argument(
        "--adapter-url",
        help=(
            "SketchUp sidecar base URL or /v1/convert endpoint. Defaults to "
            "SKETCHUP_ADAPTER_URL, ARCHITOKEN_SKP_ADAPTER_URL, then "
            "LICENSED_BIM_ADAPTER_URL."
        ),
    )
    parser.add_argument(
        "--adapter-path",
        default=os.getenv("SKETCHUP_ADAPTER_PATH", "/v1/convert"),
        help="HTTP conversion path when --adapter-url is a base URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("ARCHITOKEN_SKP_ADAPTER_TIMEOUT", "3600")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--source-prefix",
        default=os.getenv("ARCHITOKEN_SKP_SOURCE_PREFIX", ""),
        help="local path prefix to map before sending to the sidecar host.",
    )
    parser.add_argument(
        "--mapped-source-prefix",
        default=os.getenv("ARCHITOKEN_SKP_MAPPED_SOURCE_PREFIX", ""),
        help="remote sidecar path prefix corresponding to --source-prefix.",
    )
    args = parser.parse_args(argv)

    try:
        source, output = resolve_paths(args)
        target_format = args.target_format or infer_target_format(output)
        endpoint = resolve_endpoint(args.adapter_url, args.adapter_path)
        payload = build_payload(source, target_format, args)
        response = post_json(endpoint, payload, args.timeout)
        artifact_bytes = extract_artifact_bytes(response, endpoint, target_format)
        validate_artifact(artifact_bytes, target_format)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(artifact_bytes)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "sourceFormat": "skp",
                    "targetFormat": target_format,
                    "sourcePath": str(source),
                    "outputPath": str(output),
                    "adapterEndpoint": endpoint,
                    "bytes": len(artifact_bytes),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as error:  # noqa: BLE001 - command-line bridge must explain all failures.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "sourceFormat": "skp",
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    source = args.input_path
    output = args.output_path
    if args.paths:
        if source is None:
            source = args.paths[0]
        if len(args.paths) > 1 and output is None:
            output = args.paths[1]
    if not source or not output:
        raise SkpSidecarError("Expected source and output paths.")

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if not source_path.is_file():
        raise SkpSidecarError(f"Source SKP file does not exist: {source_path}")
    if source_path.suffix.lower() != ".skp":
        raise SkpSidecarError(f"Source is not an SKP file: {source_path}")
    return source_path, output_path


def infer_target_format(output: Path) -> str:
    suffix = output.suffix.lower()
    if suffix == ".ifc":
        return "ifc"
    if suffix == ".glb":
        return "glb"
    raise SkpSidecarError(
        "Cannot infer target format from output extension; use --target-format."
    )


def resolve_endpoint(adapter_url: str | None, adapter_path: str | None) -> str:
    base = (
        adapter_url
        or os.getenv("SKETCHUP_ADAPTER_URL")
        or os.getenv("ARCHITOKEN_SKP_ADAPTER_URL")
        or os.getenv("LICENSED_BIM_ADAPTER_URL")
        or ""
    ).strip()
    if not base:
        raise SkpSidecarError(
            "No licensed SketchUp adapter URL configured. Set SKETCHUP_ADAPTER_URL "
            "or pass --adapter-url; this command will not parse SKP locally."
        )
    if not adapter_path:
        return base

    normalized_path = adapter_path.strip()
    if not normalized_path:
        return base
    path_suffix = normalized_path.strip("/")
    if base.rstrip("/").endswith(path_suffix):
        return base
    return urljoin(f"{base.rstrip('/')}/", normalized_path.lstrip("/"))


def build_payload(source: Path, target_format: str, args: argparse.Namespace) -> dict[str, Any]:
    mapped_source = map_source_path(
        source,
        source_prefix=args.source_prefix,
        mapped_source_prefix=args.mapped_source_prefix,
    )
    return {
        "jobId": f"skp-{target_format}-{hashlib.sha256(str(source).encode()).hexdigest()[:16]}",
        "operation": "licensed_bim_convert",
        "sourceFormat": "skp",
        "targetFormat": target_format,
        "sourcePath": mapped_source,
        "hostSourcePath": str(source),
        "sourceFileName": source.name,
        "sourceChecksum": sha256_file(source),
        "outputFormats": [target_format, "properties-index"],
    }


def map_source_path(
    source: Path,
    *,
    source_prefix: str,
    mapped_source_prefix: str,
) -> str:
    source_text = str(source)
    if not source_prefix or not mapped_source_prefix:
        return source_text

    local_prefix = str(Path(source_prefix).expanduser().resolve())
    if source_text != local_prefix and not source_text.startswith(local_prefix + os.sep):
        return source_text

    suffix = source_text[len(local_prefix) :].lstrip(os.sep)
    remote_prefix = mapped_source_prefix.rstrip("\\/")
    if "\\" in remote_prefix:
        suffix = suffix.replace("/", "\\")
        return f"{remote_prefix}\\{suffix}" if suffix else remote_prefix
    return f"{remote_prefix}/{suffix}" if suffix else remote_prefix


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def post_json(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user configured sidecar URL.
            body = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise SkpSidecarError(
            f"SketchUp sidecar HTTP {error.code}: {details[-4000:]}"
        ) from error
    except URLError as error:
        raise SkpSidecarError(f"Cannot reach SketchUp sidecar: {error}") from error

    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise SkpSidecarError("SketchUp sidecar did not return JSON.") from error
    if not isinstance(parsed, dict):
        raise SkpSidecarError("SketchUp sidecar JSON response must be an object.")
    return parsed


def extract_artifact_bytes(
    response: dict[str, Any],
    endpoint: str,
    target_format: str,
) -> bytes:
    artifacts = response.get("artifacts")
    candidates: list[dict[str, Any]] = []
    if isinstance(artifacts, list):
        candidates.extend(item for item in artifacts if isinstance(item, dict))
    candidates.append(response)

    for artifact in candidates:
        if artifact_matches_target(artifact, target_format):
            return read_artifact_bytes(artifact, endpoint)
    raise SkpSidecarError(f"SketchUp sidecar did not return a {target_format.upper()} artifact.")


def artifact_matches_target(artifact: dict[str, Any], target_format: str) -> bool:
    name = str(artifact.get("name") or artifact.get("fileName") or "").lower()
    role = str(artifact.get("role") or "").lower()
    media_type = str(artifact.get("mediaType") or artifact.get("mimeType") or "").lower()
    if target_format == "ifc":
        return name.endswith(".ifc") or "ifc" in role or media_type in IFC_MEDIA_TYPES
    return name.endswith(".glb") or "glb" in role or media_type in GLB_MEDIA_TYPES


def read_artifact_bytes(artifact: dict[str, Any], endpoint: str) -> bytes:
    content_base64 = artifact.get("contentBase64")
    if isinstance(content_base64, str) and content_base64:
        return base64.b64decode(content_base64)

    for key in ("filePath", "path"):
        value = artifact.get(key)
        if isinstance(value, str) and value:
            path = Path(value).expanduser()
            if path.is_file():
                return path.read_bytes()

    for key in ("url", "objectUri"):
        value = artifact.get(key)
        if isinstance(value, str) and value:
            url = value if value.startswith(("http://", "https://")) else urljoin(endpoint, value)
            with urlopen(url, timeout=3600) as response:  # noqa: S310 - user configured artifact URL.
                return response.read()

    raise SkpSidecarError(
        "Artifact must include contentBase64, a readable filePath, or a fetchable url/objectUri."
    )


def validate_artifact(content: bytes, target_format: str) -> None:
    if target_format == "ifc":
        header = content[:4096].decode("utf-8", errors="ignore").upper()
        if "ISO-10303-21" not in header or "FILE_SCHEMA" not in header:
            raise SkpSidecarError("Sidecar returned bytes that are not a readable IFC file.")
        return
    if content[:4] != b"glTF":
        raise SkpSidecarError("Sidecar returned bytes that are not a readable GLB file.")


if __name__ == "__main__":
    raise SystemExit(main())
