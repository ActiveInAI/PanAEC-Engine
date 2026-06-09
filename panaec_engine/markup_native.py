# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 潘永胜

"""Native source reader for XML, HTML, XHTML, and plain text assets."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


SUPPORTED_MARKUP_FORMATS = frozenset({"xml", "html", "htm", "xhtml", "txt"})


@dataclass(frozen=True)
class MarkupNativeManifest:
    schema: str
    source_format: str
    engine: str
    viewer: str
    source_checksum: str
    derivative_roles: tuple[str, ...]
    encoding: str
    byte_size: int
    line_count: int
    root_tag: str | None
    element_count: int
    title: str | None
    links: tuple[str, ...]
    text_preview: str
    native_adapter_required: bool
    notes: tuple[str, ...]


class MarkupNativeError(ValueError):
    """Raised when a markup or text source file cannot be opened natively."""


def build_markup_native_manifest(
    path: str | Path,
    source_format: str | None = None,
) -> MarkupNativeManifest:
    """Open an XML/HTML/XHTML/TXT source file without creating derivatives."""

    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    checksum = sha256(source_bytes).hexdigest()
    normalized_format = _normalize_format(source_format or source_path.suffix)
    decoded, encoding = _decode_source(source_bytes)

    if normalized_format == "txt":
        return _build_text_manifest(source_bytes, decoded, encoding, checksum, normalized_format)
    if normalized_format in {"html", "htm"}:
        return _build_html_manifest(source_bytes, decoded, encoding, checksum, normalized_format)
    if normalized_format in {"xml", "xhtml"}:
        return _build_xml_manifest(source_bytes, decoded, encoding, checksum, normalized_format)

    raise MarkupNativeError(f"Unsupported markup source format: {normalized_format}")


def _build_text_manifest(
    source_bytes: bytes,
    decoded: str,
    encoding: str,
    checksum: str,
    source_format: str,
) -> MarkupNativeManifest:
    return MarkupNativeManifest(
        schema="panaec.markup_native_manifest.v1",
        source_format=source_format,
        engine="PanAEC Engine Markup Native",
        viewer="source_text_native_viewer",
        source_checksum=checksum,
        derivative_roles=(),
        encoding=encoding,
        byte_size=len(source_bytes),
        line_count=_line_count(decoded),
        root_tag=None,
        element_count=0,
        title=None,
        links=(),
        text_preview=_preview(decoded),
        native_adapter_required=False,
        notes=(
            "This route reads the plain-text source bytes directly and creates no derivatives.",
            "Preview text, syntax highlighting, search indexes, or rendered HTML must not replace the source file record.",
        ),
    )


def _build_html_manifest(
    source_bytes: bytes,
    decoded: str,
    encoding: str,
    checksum: str,
    source_format: str,
) -> MarkupNativeManifest:
    parser = _HtmlSourceParser()
    parser.feed(decoded)
    parser.close()

    return MarkupNativeManifest(
        schema="panaec.markup_native_manifest.v1",
        source_format=source_format,
        engine="PanAEC Engine Markup Native",
        viewer="source_html_native_viewer",
        source_checksum=checksum,
        derivative_roles=(),
        encoding=encoding,
        byte_size=len(source_bytes),
        line_count=_line_count(decoded),
        root_tag=parser.root_tag,
        element_count=parser.element_count,
        title=parser.title,
        links=tuple(parser.links),
        text_preview=_preview(decoded),
        native_adapter_required=False,
        notes=(
            "This route reads the HTML source directly and creates no PDF, image, OCR, or text derivative.",
            "HTML visual preview must be sandboxed and must preserve source-code switching, checksum, and save-back boundaries.",
        ),
    )


def _build_xml_manifest(
    source_bytes: bytes,
    decoded: str,
    encoding: str,
    checksum: str,
    source_format: str,
) -> MarkupNativeManifest:
    try:
        root = ElementTree.fromstring(source_bytes)
    except ElementTree.ParseError as exc:
        raise MarkupNativeError(f"XML source could not be parsed: {exc}") from exc

    return MarkupNativeManifest(
        schema="panaec.markup_native_manifest.v1",
        source_format=source_format,
        engine="PanAEC Engine Markup Native",
        viewer="source_xml_native_viewer",
        source_checksum=checksum,
        derivative_roles=(),
        encoding=encoding,
        byte_size=len(source_bytes),
        line_count=_line_count(decoded),
        root_tag=_strip_namespace(root.tag),
        element_count=sum(1 for _ in root.iter()),
        title=_first_named_text(root, "title"),
        links=tuple(_xml_links(root)),
        text_preview=_preview(decoded),
        native_adapter_required=False,
        notes=(
            "This route reads the XML source directly and creates no PDF, image, OCR, HTML, or text derivative.",
            "Schema validation, publication readiness, and regulatory conclusions require registered validators or rule adapters.",
        ),
    )


def _normalize_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if normalized not in SUPPORTED_MARKUP_FORMATS:
        raise MarkupNativeError(f"Unsupported markup source format: {normalized}")
    return normalized


def _decode_source(source_bytes: bytes) -> tuple[str, str]:
    if source_bytes.startswith(b"\xef\xbb\xbf"):
        return source_bytes.decode("utf-8-sig"), "utf-8-sig"

    for encoding in ("utf-8", "gb18030"):
        try:
            return source_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    return source_bytes.decode("utf-8", errors="replace"), "utf-8-replacement"


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _preview(text: str, limit: int = 4096) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _first_named_text(root: ElementTree.Element, name: str) -> str | None:
    expected = name.lower()
    for element in root.iter():
        if _strip_namespace(element.tag).lower() == expected:
            text = "".join(element.itertext()).strip()
            if text:
                return text
    return None


def _xml_links(root: ElementTree.Element) -> list[str]:
    links: list[str] = []
    for element in root.iter():
        for key, value in element.attrib.items():
            if _strip_namespace(key).lower() in {"href", "src", "url"} and value:
                links.append(value)
    return links


class _HtmlSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_tag: str | None = None
        self.element_count = 0
        self.links: list[str] = []
        self.title: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.root_tag is None:
            self.root_tag = normalized
        self.element_count += 1
        if normalized == "title":
            self._in_title = True
        for name, value in attrs:
            if value and name.lower() in {"href", "src"}:
                self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            title = "".join(self._title_parts).strip()
            self.title = title or self.title

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
