"""Retained media extraction for v5 benchmarks; never reads answer labels.

The resulting JSON contains source-derived material and locations. Every lane
receives these same bytes. HTML spans are not pagination evidence. Native PDF
pages and single-page images have intrinsic page boundaries; OCR is explicitly
recorded rather than represented as original digital text.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache
from pathlib import Path

from lxml import etree

from tradingagents.dataflows.pit.official_observations import _json_mapping, _normalize_source_value

SCHEMA = "research_media_input/v1"
FORMATS = {"json", "html", "pdf", "image", "repository_document", "tool_output"}
FIELDS = {"schema_version", "format", "page_number", "engine_versions", "extraction_sha256"}
SHA = re.compile(r"[0-9a-f]{64}")
INLINE_NAMESPACES = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"}
INSTANCE_NAMESPACE = "http://www.xbrl.org/2003/instance"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"


class MediaInputError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def validate_media_input(raw):
    if type(raw) is not dict or type(raw.get("schema_version")) is not str:
        raise MediaInputError("invalid media-input contract")
    selected_version = raw.get("schema_version") == "research_media_input/v2"
    if set(raw) != FIELDS | ({"selection"} if selected_version else set()) or raw["schema_version"] not in {SCHEMA, "research_media_input/v2"} or type(raw["format"]) is not str or raw["format"] not in FORMATS:
        raise MediaInputError("invalid media-input contract")
    if selected_version:
        selection = raw["selection"]
        if raw["format"] != "html" or type(selection) is not dict or set(selection) != {"kind", "ids"} or selection["kind"] != "html_element_ids":
            raise MediaInputError("invalid media selection")
        ids = selection["ids"]
        if type(ids) is not list or not 1 <= len(ids) <= 20 or any(type(item) is not str or not item or len(item) > 256 for item in ids) or len(set(ids)) != len(ids):
            raise MediaInputError("invalid selected HTML element IDs")
    page = raw["page_number"]
    if raw["format"] in {"pdf", "image"}:
        if type(page) is not int or page < 1 or (raw["format"] == "image" and page != 1):
            raise MediaInputError("invalid native page number")
    elif page is not None:
        raise MediaInputError("text and HTML spans cannot claim native page boundaries")
    versions = raw["engine_versions"]
    if type(versions) is not dict or not versions or any(type(k) is not str or type(v) is not str or not v for k, v in versions.items()):
        raise MediaInputError("media extraction engine identity is missing")
    if type(raw["extraction_sha256"]) is not str or SHA.fullmatch(raw["extraction_sha256"]) is None:
        raise MediaInputError("invalid extraction digest")
    return dict(raw)


def _local(tag):
    return str(tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _attrs(node):
    # Inline fact attributes are unqualified, except xsi:nil. An unrelated
    # namespace cannot supply a contextRef, unitRef, scale, or sign.
    attrs = {k.lower(): v for k, v in node.attrib.items() if not k.startswith("{") and ":" not in k}
    for key, value in node.attrib.items():
        if key == f"{{{XSI_NAMESPACE}}}nil" or (key.endswith(":nil") and _namespaces(node).get(key.split(":", 1)[0]) == XSI_NAMESPACE):
            attrs["nil"] = value
    return attrs


def _namespaces(node):
    namespaces = dict(node.nsmap)
    if isinstance(node.tag, str) and node.tag.startswith("{"):
        return namespaces
    # Tolerant HTML parsing exposes xmlns declarations as ordinary attrs.
    for parent in reversed([node, *node.iterancestors()]):
        namespaces.update({k.split(":", 1)[1]: v for k, v in parent.attrib.items() if k.startswith("xmlns:")})
    return namespaces


def _namespace(node):
    tag = node.tag
    if not isinstance(tag, str):
        return None
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return _namespaces(node).get(tag.split(":", 1)[0]) if ":" in tag else _namespaces(node).get(None)


def _node_text(node):
    # ix:exclude does not participate in the XBRL value; its markup is retained.
    parts = [node.text or ""]
    for child in node:
        if isinstance(child.tag, str) and not (_local(child.tag) == "exclude" and _namespace(child) in INLINE_NAMESPACES):
            parts.append(_node_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _numeric(text, attrs, namespaces):
    fmt = attrs.get("format")
    cleaned = text.strip()
    if fmt:
        prefix, sep, name = fmt.partition(":")
        namespace = namespaces.get(prefix) if sep else namespaces.get(None)
        registries = {
            "http://www.xbrl.org/inlineXBRL/transformation/2011-07-31",
            "http://www.xbrl.org/inlineXBRL/transformation/2015-02-26",
            "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
            "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
        }
        if namespace not in registries:
            return None, "unsupported_transform_namespace"
        cleaned = re.sub(r"[\s\u00a0]", "", cleaned)
        if name in {"num-dot-decimal", "numdotdecimal"}:
            if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", cleaned):
                return None, "invalid_transform_input"
            cleaned = cleaned.replace(",", "")
        elif name in {"num-comma-decimal", "numcommadecimal"}:
            if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", cleaned):
                return None, "invalid_transform_input"
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif name in {"fixed-zero", "zerodash"} and cleaned in {"-", "—", "–"}:
            cleaned = "0"
        else:
            return None, "unsupported_transform"
    try:
        if len(cleaned) > 4096 or not re.fullmatch(r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
            return None, "invalid_numeric_text"
        scale_text = attrs.get("scale", "0")
        if not re.fullmatch(r"[+\-]?\d{1,3}", scale_text) or abs(int(scale_text)) > 100:
            return None, "unsupported_scale"
        if attrs.get("sign", "") not in {"", "-"}:
            return None, "invalid_sign"
        with localcontext() as ctx:
            ctx.prec = 4096
            value = Decimal(cleaned).scaleb(int(scale_text))
            if attrs.get("sign") == "-":
                value = -value
        return _normalize_source_value(value), "available"
    except (InvalidOperation, ValueError):
        return None, "invalid_numeric_value"


def _html(raw, selection=None):
    if b"<!DOCTYPE" in raw.upper() and (b"SYSTEM" in raw.upper() or b"ENTITY" in raw.upper()):
        raise MediaInputError("external HTML/XML declarations are unsupported")
    try:
        tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        parser = "xml"
    except etree.XMLSyntaxError:
        tree = etree.fromstring(raw, etree.HTMLParser(no_network=True, recover=True))
        parser = "html"
    if tree is None:
        raise MediaInputError("HTML source has no document")
    elements = list(tree.iter())
    by_id = {}
    for node in elements:
        attrs = _attrs(node)
        if attrs.get("id"):
            if attrs["id"] in by_id:
                raise MediaInputError("HTML source contains duplicate element IDs")
            by_id[attrs["id"]] = node
    doc = tree.getroottree()

    def location(node):
        return {"xpath": doc.getpath(node), "source_line": node.sourceline}

    def markup(node):
        return etree.tostring(node, encoding="unicode", with_tail=False)

    contexts, units, facts, tables = {}, {}, {}, []
    for node in elements:
        local, attrs = _local(node.tag), _attrs(node)
        if local in {"context", "unit"} and _namespace(node) == INSTANCE_NAMESPACE and attrs.get("id"):
            target = contexts if local == "context" else units
            target[attrs["id"]] = {"markup": markup(node), "location": location(node)}
        if local == "table":
            rows = []
            for row in node.iter():
                if _local(row.tag) != "tr":
                    continue
                cells = [{"text": _node_text(cell), "attributes": _attrs(cell), "location": location(cell)} for cell in row if _local(cell.tag) in {"td", "th"}]
                rows.append(cells)
            tables.append({"id": attrs.get("id"), "rows": rows, "location": location(node)})
        if local not in {"nonfraction", "nonnumeric", "fraction"}:
            continue
        fact_id = attrs.get("id") or doc.getpath(node)
        continuation_ids, seen = [], set()
        text, next_id = _node_text(node), attrs.get("continuedat")
        while next_id:
            if next_id in seen or next_id not in by_id or _local(by_id[next_id].tag) != "continuation" or _namespace(by_id[next_id]) not in INLINE_NAMESPACES:
                raise MediaInputError("inline-XBRL continuation is missing or cyclic")
            seen.add(next_id)
            continuation_ids.append(next_id)
            continued = by_id[next_id]
            text += _node_text(continued)
            next_id = _attrs(continued).get("continuedat")
        namespaces = _namespaces(node)
        value, status = (text, "available") if local == "nonnumeric" else _numeric(text, attrs, namespaces)
        if _namespace(node) not in INLINE_NAMESPACES:
            value, status = None, "invalid_inline_namespace"
        elif local == "nonnumeric" and (attrs.get("format") or attrs.get("escape") == "true"):
            value, status = None, "unsupported_nonnumeric_transform"
        if local == "fraction":
            value, status = None, "fraction_requires_explicit_ratio_selection"
        if attrs.get("nil") == "true":
            value, status = None, "nil"
        facts[fact_id] = {"kind": local, "attributes": attrs, "namespaces": {"" if k is None else k: v for k, v in namespaces.items()}, "text": text, "value": value, "status": status, "markup": markup(node), "location": location(node), "continuation_ids": continuation_ids}
    for fact in facts.values():
        attrs = fact["attributes"]
        if attrs.get("contextref") not in contexts or (fact["kind"] != "nonnumeric" and attrs.get("unitref") not in units):
            fact["value"], fact["status"] = None, "missing_context_or_unit"
    continuations = {key: {"markup": markup(node), "location": location(node)} for key, node in by_id.items() if _local(node.tag) == "continuation" and _namespace(node) in INLINE_NAMESPACES}
    material = {"text": _node_text(tree), "original_markup": raw.decode("utf-8"), "tables": tables, "inline_facts": facts, "contexts": contexts, "units": units, "continuations": continuations}
    transformations = [
        {"operation": "parse_retained_markup", "parser": parser},
        {"operation": "inline_fact_transforms", "unsupported_values": "unavailable"},
    ]
    if selection is not None:
        if any(key not in by_id for key in selection["ids"]):
            raise MediaInputError("selected HTML element is missing")
        selected_nodes = [by_id[key] for key in selection["ids"]]
        visible_nodes = {node for selected in selected_nodes for node in selected.iter()}
        paths = {doc.getpath(node) for node in visible_nodes}
        selected_facts = {key: fact for key, fact in facts.items() if fact["location"]["xpath"] in paths}
        context_ids = {f["attributes"].get("contextref") for f in selected_facts.values()}
        unit_ids = {f["attributes"].get("unitref") for f in selected_facts.values()}
        continuation_ids = {key for f in selected_facts.values() for key in f["continuation_ids"]}
        material = {
            "text": "\n".join(_node_text(node) for node in selected_nodes),
            "selected_markup": [{"id": key, "markup": markup(by_id[key]), "location": location(by_id[key])} for key in selection["ids"]],
            "tables": [table for table in tables if table["location"]["xpath"] in paths],
            "inline_facts": selected_facts,
            "contexts": {key: value for key, value in contexts.items() if key in context_ids},
            "units": {key: value for key, value in units.items() if key in unit_ids},
            "continuations": {key: value for key, value in continuations.items() if key in continuation_ids},
        }
        transformations.append({"operation": "select_registered_html_elements", "ids": selection["ids"], "automatic_dependencies": ["context", "unit", "continuation"], "markup_representation": "parsed DOM serialization; original bytes separately bound"})
    return material, transformations


def _command(tool, args):
    executable = shutil.which(tool)
    if not executable:
        raise MediaInputError(f"required local extractor is unavailable: {tool}")
    try:
        completed = subprocess.run([executable, *args], capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaInputError(f"local extraction failed: {tool}") from exc
    if completed.returncode:
        raise MediaInputError(f"local extraction failed: {tool}, exit {completed.returncode}")
    return completed.stdout, completed.stderr


def engine_versions(fmt):
    if fmt == "html":
        return {"lxml": str(etree.LXML_VERSION), "qualification_media": "1"}
    tools = {"pdf": ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"), "image": ("tesseract",)}.get(fmt, ())
    versions = {"qualification_media": "1"}
    for tool in tools:
        stdout, stderr = _command(tool, ["--version" if tool == "tesseract" else "-v"])
        versions[tool] = (stdout or stderr).decode().splitlines()[0]
    return versions


def _ocr(path):
    stdout, _ = _command("tesseract", [str(path), "stdout", "-l", "eng", "--psm", "3", "tsv"])
    words = []
    for row in csv.DictReader(io.StringIO(stdout.decode()), delimiter="\t"):
        if row.get("level") == "5" and row.get("text", "").strip():
            words.append({"text": row["text"], "confidence": row["conf"], "bbox": [int(row[k]) for k in ("left", "top", "width", "height")], "block": int(row["block_num"]), "paragraph": int(row["par_num"]), "line": int(row["line_num"])})
    return {"text": " ".join(w["text"] for w in words), "words": words}


def _pdf_layout(extracted):
    # Some legitimate PDF fonts produce control characters forbidden by XML
    # 1.0. Escape them only for parsing, then restore the exact characters in
    # word text. Never silently drop a glyph or guess its intended punctuation.
    text = extracted.decode("utf-8")
    invalid = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
    prefix = "_TA_XML_" + hashlib.sha256(extracted).hexdigest()[:16] + "_"
    while prefix in text:
        prefix += "_"
    tokens, counts = {}, {}

    def escape(match):
        character = match[0]
        token = prefix + f"{ord(character):x}_"
        tokens[token] = character
        counts[character] = counts.get(character, 0) + 1
        return token

    encoded = invalid.sub(escape, text).encode("utf-8")
    try:
        doc = etree.fromstring(encoded, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise MediaInputError("PDF text layout is malformed") from exc
    words = []
    for node in doc.iter():
        if _local(node.tag) != "word":
            continue
        word = "".join(node.itertext())
        for token, character in tokens.items():
            word = word.replace(token, character)
        bbox = {key: node.get(key) for key in ("xMin", "yMin", "xMax", "yMax")}
        if any(value is None or re.fullmatch(r"[+\-]?\d+(?:\.\d+)?", value) is None for value in bbox.values()):
            raise MediaInputError("PDF word coordinates are invalid")
        words.append({"text": word, "bbox": bbox})
    transformations = []
    if counts:
        transformations.append({"operation": "escape_xml_controls_for_parsing", "characters": [{"codepoint": f"U+{ord(character):04X}", "count": count} for character, count in sorted(counts.items())], "word_text_restored_exactly": True, "original_layout_sha256": hashlib.sha256(extracted).hexdigest()})
    return words, transformations


@lru_cache(maxsize=8)
def _extraction(raw, fmt, page, version_bytes, selection_bytes=None):
    versions = json.loads(version_bytes)
    selection = json.loads(selection_bytes) if selection_bytes else None
    if len(raw) > 64 * 1024 * 1024:
        raise MediaInputError("media input exceeds bounded extraction size")
    if fmt == "html":
        material, transforms = _html(raw, selection)
    elif fmt in {"json", "tool_output", "repository_document"}:
        text = raw.decode("utf-8")
        material = {"text": text, "lines": text.splitlines()}
        if fmt == "json":
            # Preserve number lexemes in material; scalar numeric handling stays
            # in the established exact-decimal source extractor.
            material["json_text"] = text

            def exact(value):
                if isinstance(value, dict):
                    return {k: exact(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [exact(v) for v in value]
                return _normalize_source_value(value) if type(value) is Decimal else value

            material["json_values"] = exact(_json_mapping(raw, label="retained benchmark JSON"))
        transforms = [{"operation": "utf8_decode", "normalization": "none"}]
    else:
        with tempfile.TemporaryDirectory(prefix="ta-retained-media-") as directory:
            target = Path(directory) / ("input.pdf" if fmt == "pdf" else "input.image")
            target.write_bytes(raw)
            if fmt == "image":
                if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
                    raise MediaInputError("only single-page PNG/JPEG originals are supported")
                material = _ocr(target)
                transforms = [{"operation": "ocr", "language": "eng", "psm": 3, "coordinates": "original_image_pixels"}]
            else:
                if not raw.startswith(b"%PDF-"):
                    raise MediaInputError("PDF input does not have a PDF signature")
                info, _ = _command("pdfinfo", [str(target)])
                match = re.search(rb"^Pages:\s+(\d+)\s*$", info, re.MULTILINE)
                if match is None or page > int(match[1]):
                    raise MediaInputError("PDF page does not exist")
                extracted, _ = _command("pdftotext", ["-f", str(page), "-l", str(page), "-bbox-layout", "-enc", "UTF-8", str(target), "-"])
                words, layout_transforms = _pdf_layout(extracted)
                material = {"text": " ".join(w["text"] for w in words), "words": words, "page_count": int(match[1])}
                transforms = [{"operation": "pdf_text_layout", "page": page, "coordinates": "PDF_points"}, *layout_transforms]
                if not words:
                    render = Path(directory) / "page"
                    _command("pdftoppm", ["-f", str(page), "-l", str(page), "-r", "150", "-singlefile", "-png", str(target), str(render)])
                    image = render.with_suffix(".png")
                    material["ocr"] = _ocr(image)
                    material["text"] = material["ocr"]["text"]
                    transforms.extend([{"operation": "render_pdf_page", "dpi": 150, "page": page, "rendered_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}, {"operation": "ocr", "language": "eng", "psm": 3, "coordinates": "rendered_page_pixels"}])
    source = {"schema_version": "research_media_source/v2" if selection is not None else "research_media_source/v1", "original_sha256": hashlib.sha256(raw).hexdigest(), "format": fmt, "page_number": page, "engine_versions": versions, "transformations": transforms, "material": material}
    if selection is not None:
        source["selection"] = selection
    return source


def build_media_input(raw: bytes, *, format: str, page_number: int | None = None, selection=None):
    if type(raw) is not bytes:
        raise MediaInputError("media original must be bytes")
    # Validate shape before invoking any extractor, including missing PDF pages.
    descriptor = {"schema_version": "research_media_input/v2" if selection is not None else SCHEMA, "format": format, "page_number": page_number, "engine_versions": {"qualification_media": "1"}, "extraction_sha256": "0" * 64}
    if selection is not None:
        descriptor["selection"] = selection
    validate_media_input(descriptor)
    versions = engine_versions(format)
    source = canonical(_extraction(raw, format, page_number, canonical(versions), canonical(selection) if selection is not None else None))
    contract = {**descriptor, "engine_versions": versions, "extraction_sha256": hashlib.sha256(source).hexdigest()}
    return validate_media_input(contract), source


def media_source(raw: bytes, contract):
    contract = validate_media_input(contract)
    versions = engine_versions(contract["format"])
    if versions != contract["engine_versions"]:
        raise MediaInputError("registered extraction engine changed")
    selection = contract.get("selection")
    source = canonical(_extraction(raw, contract["format"], contract["page_number"], canonical(versions), canonical(selection) if selection is not None else None))
    if hashlib.sha256(source).hexdigest() != contract["extraction_sha256"]:
        raise MediaInputError("registered media extraction changed")
    return source
