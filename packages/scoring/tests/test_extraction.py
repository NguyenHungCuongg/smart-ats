import tracemalloc
import zipfile
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from smart_ats_scoring.extraction import MAX_DOCX_UNZIPPED_BYTES, ExtractionError, extract_text


def _pdf(*lines: str, password: str | None = None, owner_password: str | None = None) -> bytes:
    """A one-page PDF whose text layer holds `lines`; no lines gives a blank page."""
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    if lines:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        shows = " ".join(f"({line}) Tj 0 -14 Td" for line in lines)
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 72 720 Td {shows} ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    if password is not None:
        writer.encrypt(password, owner_password, algorithm="AES-256")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_with_text_layer() -> None:
    text = extract_text(_pdf("Backend Developer", "Python, PostgreSQL"))

    assert "Backend Developer" in text
    assert "Python, PostgreSQL" in text


def test_docx_paragraphs_and_tables() -> None:
    doc = Document()
    doc.add_paragraph("Nguyễn Văn A")
    doc.add_table(rows=1, cols=2).rows[0].cells[1].text = "FastAPI, Docker"
    out = BytesIO()
    doc.save(out)

    text = extract_text(out.getvalue())

    assert "Nguyễn Văn A" in text
    assert "FastAPI, Docker" in text


def test_utf8_text_with_bom() -> None:
    assert extract_text("\ufeffTuyển Backend Developer".encode()) == "Tuyển Backend Developer"


def test_password_protected_pdf_is_encrypted_pdf() -> None:
    with pytest.raises(ExtractionError) as error:
        extract_text(_pdf("Secret CV", password="secret"))

    assert error.value.code == "ENCRYPTED_PDF"


def test_pdf_with_only_an_owner_password_opens() -> None:
    # Edit/print restrictions only: readers open it without asking for a password.
    assert "Restricted CV" in extract_text(_pdf("Restricted CV", password="", owner_password="o"))


@pytest.mark.parametrize(
    "data", [b"%PDF-1.7\nnot a real pdf", b"PK\x03\x04not a real docx"], ids=["pdf", "docx"]
)
def test_corrupt_file_is_unreadable(data: bytes) -> None:
    with pytest.raises(ExtractionError) as error:
        extract_text(data)

    assert error.value.code == "UNREADABLE"


@pytest.mark.parametrize(
    "data",
    [b"\xff\xd8\xff\xe0\x00\x10JFIF", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ids=["jpeg", "doc"],
)
def test_other_formats_are_unsupported(data: bytes) -> None:
    with pytest.raises(ExtractionError) as error:
        extract_text(data)

    assert error.value.code == "UNSUPPORTED_FORMAT"


def _empty_docx() -> bytes:
    out = BytesIO()
    Document().save(out)
    return out.getvalue()


@pytest.mark.parametrize(
    "data", [_pdf(), _empty_docx(), b" \n\t "], ids=["scanned-pdf", "empty-docx", "blank-txt"]
)
def test_document_without_text_is_no_text(data: bytes) -> None:
    with pytest.raises(ExtractionError) as error:
        extract_text(data)

    assert error.value.code == "NO_TEXT"


def test_docx_header_and_text_box() -> None:
    # CV templates often put contact details in the header and lay out columns in text boxes.
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "an.nguyen@example.com"
    box = parse_xml(
        f'<w:r {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml">'
        "<w:pict><v:shape><v:textbox><w:txbxContent>"
        "<w:p><w:r><w:t>Kỹ năng: Kubernetes</w:t></w:r></w:p>"
        "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    doc.add_paragraph("Kinh nghiệm")._p.append(box)
    out = BytesIO()
    doc.save(out)

    text = extract_text(out.getvalue())

    assert "an.nguyen@example.com" in text
    assert "Kỹ năng: Kubernetes" in text


def _bomb(declared_size: int | None) -> bytes:
    """Tens of KiB that unzip to more XML than a worker should hold, declaring `declared_size`
    in the central directory if given: zipfile trusts that number, an attacker writes it."""
    bomb = BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b" " * (MAX_DOCX_UNZIPPED_BYTES + 1))
    data = bytearray(bomb.getvalue())
    if declared_size is not None:
        central = data.index(b"PK")
        data[central + 24 : central + 28] = declared_size.to_bytes(4, "little")
    assert len(data) < 100 * 1024
    return bytes(data)


@pytest.mark.parametrize("declared_size", [None, 1], ids=["honest", "lying"])
def test_docx_that_unzips_past_the_limit_is_too_large(declared_size: int | None) -> None:
    bomb = _bomb(declared_size)
    tracemalloc.start()

    with pytest.raises(ExtractionError) as error:
        extract_text(bomb)

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert error.value.code == "DOCX_TOO_LARGE"
    assert peak < MAX_DOCX_UNZIPPED_BYTES / 4


def test_docx_compressed_with_bzip2_is_unreadable() -> None:
    # zipfile inflates bzip2 without a bound, so even a small read could hold a whole bomb.
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_BZIP2) as z:
        z.writestr("word/document.xml", b" " * (MAX_DOCX_UNZIPPED_BYTES + 1))

    with pytest.raises(ExtractionError) as error:
        extract_text(archive.getvalue())

    assert error.value.code == "UNREADABLE"
