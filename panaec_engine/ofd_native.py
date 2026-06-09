# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""Native OFD source-package reader for PanAEC Engine.

This module reads the OFD source package directly. It does not create PDF,
image, OCR, text, or HTML derivatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import posixpath
from typing import Iterable
from xml.etree import ElementTree
from zipfile import ZipFile


@dataclass(frozen=True)
class OfdNativeEntry:
    path: str
    kind: str
    directory: bool
    uncompressed_size: int
    compressed_size: int


@dataclass(frozen=True)
class OfdRenderedText:
    id: str
    text: str
    x: float
    y: float
    width: float
    height: float
    font_id: str | None
    font_family: str
    font_size: float
    fill: str


@dataclass(frozen=True)
class OfdRenderedPage:
    id: str
    source_path: str
    width: float
    height: float
    objects: tuple[OfdRenderedText, ...]


@dataclass(frozen=True)
class OfdNativeManifest:
    schema: str
    source_format: str
    standard: str
    engine: str
    viewer: str
    source_checksum: str
    derivative_roles: tuple[str, ...]
    can_render_fixed_layout: bool
    native_adapter_required: bool
    entries: tuple[OfdNativeEntry, ...]
    documents: tuple[str, ...]
    pages: tuple[str, ...]
    resources: tuple[str, ...]
    signatures: tuple[str, ...]
    annotations: tuple[str, ...]
    attachments: tuple[str, ...]
    rendered_pages: tuple[OfdRenderedPage, ...]
    notes: tuple[str, ...]


class OfdNativeError(ValueError):
    """Raised when an OFD source package cannot be opened natively."""


def build_ofd_native_manifest(path: str | Path) -> OfdNativeManifest:
    """Open an OFD source package and return its native package manifest."""

    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    checksum = sha256(source_bytes).hexdigest()

    try:
        with ZipFile(source_path) as package:
            entries = _collect_entries(package)
            documents = tuple(entry.path for entry in entries if entry.kind == "document")
            pages = tuple(entry.path for entry in entries if entry.kind == "page")
            resources = tuple(entry.path for entry in entries if entry.kind == "resource")
            signatures = tuple(entry.path for entry in entries if entry.kind == "signature")
            annotations = tuple(entry.path for entry in entries if entry.kind == "annotation")
            attachments = tuple(entry.path for entry in entries if entry.kind == "attachment")
            rendered_pages = _build_rendered_pages(package, documents)
    except Exception as exc:  # pragma: no cover - exact zip/xml exceptions vary
        if isinstance(exc, OfdNativeError):
            raise
        raise OfdNativeError(f"OFD source package could not be opened: {exc}") from exc

    has_root = any(entry.kind == "ofd-root" for entry in entries)
    has_document = bool(documents)

    return OfdNativeManifest(
        schema="panaec.ofd_native_manifest.v1",
        source_format="ofd",
        standard="GB/T 33190-2016",
        engine="PanAEC Engine OFD Native",
        viewer="ofd_native_package_viewer" if has_root and has_document else "ofd_native_adapter_required",
        source_checksum=checksum,
        derivative_roles=(),
        can_render_fixed_layout=bool(rendered_pages),
        native_adapter_required=True,
        entries=entries,
        documents=documents,
        pages=pages,
        resources=resources,
        signatures=signatures,
        annotations=annotations,
        attachments=attachments,
        rendered_pages=rendered_pages,
        notes=(
            "This route reads the OFD source package directly and creates no derivatives.",
            "The package reader supports source XML page/text objects; full digital seal and invoice semantics require a GB/T 33190-2016 runtime adapter.",
            "PDF, image, OCR, HTML, or plain-text exports must be labelled as derivatives and cannot be reported as native OFD display.",
        ),
    )


def _collect_entries(package: ZipFile) -> tuple[OfdNativeEntry, ...]:
    entries: list[OfdNativeEntry] = []
    for info in sorted(package.infolist(), key=lambda item: item.filename):
        path = info.filename.strip("/")
        if not path:
            continue
        entries.append(
            OfdNativeEntry(
                path=path,
                kind=_classify_entry(path, info.is_dir()),
                directory=info.is_dir(),
                uncompressed_size=info.file_size,
                compressed_size=info.compress_size,
            )
        )
    return tuple(entries)


def _classify_entry(path: str, directory: bool) -> str:
    normalized = path.strip("/")
    lower = normalized.lower()
    if directory:
        return "directory"
    if lower == "ofd.xml":
        return "ofd-root"
    if lower.endswith("/document.xml"):
        return "document"
    if lower.endswith("/content.xml") and "/pages/" in lower:
        return "page"
    if lower.endswith("/publicres.xml") or lower.endswith("/documentres.xml") or "/res/" in lower:
        return "resource"
    if "/signatures/" in lower or lower.endswith("/signatures.xml"):
        return "signature"
    if "/annots/" in lower or "/annotations/" in lower:
        return "annotation"
    if "/attachments/" in lower or "/attachs/" in lower:
        return "attachment"
    if lower.endswith(".xml"):
        return "xml"
    return "data"


def _build_rendered_pages(package: ZipFile, documents: Iterable[str]) -> tuple[OfdRenderedPage, ...]:
    rendered_pages: list[OfdRenderedPage] = []

    for document_path in documents:
        document_root = _parse_xml(package.read(document_path))
        document_base = posixpath.dirname(document_path)
        width, height = _document_page_area(document_root)
        fonts = _document_fonts(package, document_root, document_base)
        for page_id, page_path in _document_page_refs(document_root, document_base):
            if page_path not in package.namelist():
                continue
            page_root = _parse_xml(package.read(page_path))
            rendered_pages.append(
                OfdRenderedPage(
                    id=page_id,
                    source_path=page_path,
                    width=width,
                    height=height,
                    objects=_page_text_objects(page_root, fonts),
                )
            )

    return tuple(rendered_pages)


def _parse_xml(data: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise OfdNativeError(f"OFD XML could not be parsed: {exc}") from exc


def _document_page_area(root: ElementTree.Element) -> tuple[float, float]:
    physical_box = _first_text(root, "PhysicalBox")
    values = _number_list(physical_box)
    if len(values) >= 4 and values[2] > 0 and values[3] > 0:
        return values[2], values[3]
    return 210.0, 297.0


def _document_fonts(
    package: ZipFile,
    root: ElementTree.Element,
    document_base: str,
) -> dict[str, str]:
    fonts: dict[str, str] = {}
    for public_res in _elements(root, "PublicRes"):
        public_res_path = _resolve_path(document_base, (public_res.text or "").strip())
        if public_res_path not in package.namelist():
            continue
        public_res_root = _parse_xml(package.read(public_res_path))
        for font in _elements(public_res_root, "Font"):
            font_id = _attr(font, "ID", "id")
            if not font_id:
                continue
            fonts[font_id] = (
                _attr(font, "FontName", "FamilyName", "fontName", "familyName")
                or f"OFD Font {font_id}"
            )
    return fonts


def _document_page_refs(
    root: ElementTree.Element,
    document_base: str,
) -> tuple[tuple[str, str], ...]:
    refs: list[tuple[str, str]] = []
    for page in _elements(root, "Page"):
        base_loc = _attr(page, "BaseLoc", "baseLoc") or ""
        if not base_loc:
            continue
        refs.append((_attr(page, "ID", "id") or f"page-{len(refs) + 1}", _resolve_path(document_base, base_loc)))
    return tuple(refs)


def _page_text_objects(
    root: ElementTree.Element,
    fonts: dict[str, str],
) -> tuple[OfdRenderedText, ...]:
    objects: list[OfdRenderedText] = []
    for text_object in _elements(root, "TextObject"):
        boundary = _number_list(_attr(text_object, "Boundary", "boundary"))
        if len(boundary) < 4:
            continue
        boundary_x, boundary_y, boundary_width, boundary_height = boundary[:4]
        font_id = _attr(text_object, "Font", "font")
        font_size = _number(_attr(text_object, "Size", "size")) or boundary_height or 3.5
        fill = _fill_color(text_object)
        for text_code in _elements(text_object, "TextCode"):
            text = "".join(text_code.itertext())
            if not text:
                continue
            x = boundary_x + (_number(_attr(text_code, "X", "x")) or 0.0)
            y = boundary_y + (_number(_attr(text_code, "Y", "y")) or font_size)
            objects.append(
                OfdRenderedText(
                    id=_attr(text_object, "ID", "id") or f"text-{len(objects) + 1}",
                    text=text,
                    x=x,
                    y=y,
                    width=boundary_width,
                    height=boundary_height,
                    font_id=font_id,
                    font_family=fonts.get(font_id or "", "sans-serif"),
                    font_size=font_size,
                    fill=fill,
                )
            )
    return tuple(objects)


def _fill_color(text_object: ElementTree.Element) -> str:
    for fill_color in _elements(text_object, "FillColor"):
        values = _number_list(_attr(fill_color, "Value", "value"))
        if len(values) >= 3:
            rgb = [int(round(channel * 255 if channel <= 1 else channel)) for channel in values[:3]]
            rgb = [max(0, min(255, channel)) for channel in rgb]
            return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    return "#111827"


def _resolve_path(base: str, loc: str) -> str:
    normalized = loc.strip().lstrip("/")
    if not normalized:
        return ""
    if not base:
        return posixpath.normpath(normalized)
    return posixpath.normpath(posixpath.join(base, normalized))


def _elements(root: ElementTree.Element, local_name: str) -> tuple[ElementTree.Element, ...]:
    return tuple(element for element in root.iter() if _local_name(element.tag) == local_name)


def _first_text(root: ElementTree.Element, local_name: str) -> str:
    for element in _elements(root, local_name):
        return (element.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.rsplit(":", 1)[-1]
    return tag


def _attr(element: ElementTree.Element, *names: str) -> str | None:
    for name in names:
        if name in element.attrib:
            return element.attrib[name]
    lower_names = {name.lower() for name in names}
    for key, value in element.attrib.items():
        if _local_name(key).lower() in lower_names:
            return value
    return None


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _number_list(value: str | None) -> list[float]:
    if not value:
        return []
    numbers: list[float] = []
    for chunk in value.replace(",", " ").split():
        number = _number(chunk)
        if number is not None:
            numbers.append(number)
    return numbers
