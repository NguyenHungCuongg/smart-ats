"""Document Extraction (FR-C2.1): raw text from a JD or CV Document."""

from io import BytesIO

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError


class ExtractionError(Exception):
    """A document whose text cannot be extracted; `code` goes to the Upload Batch item (ERD)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


def extract_text(data: bytes) -> str:
    """Text of a PDF with a text layer, a DOCX or a UTF-8 text file, told apart by magic bytes."""
    text = _read(data)
    if not text.strip():
        # ponytail: a scan with a few stray glyphs still passes; phase-2 OCR fallback needs a ratio.
        raise ExtractionError("NO_TEXT", "the document has no text layer (scanned or empty)")
    return text


def _read(data: bytes) -> str:
    try:
        if data.startswith(b"%PDF"):
            return _pdf(data)
        if data.startswith(b"PK\x03\x04"):
            return _docx(data)
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ExtractionError("UNSUPPORTED_FORMAT", "not a PDF, DOCX or UTF-8 text file") from e
    except FileNotDecryptedError as e:
        raise ExtractionError("ENCRYPTED_PDF", "the PDF is password-protected") from e
    except Exception as e:
        # Parsers raise many exception types on malformed input; all mean the same to the caller.
        raise ExtractionError("UNREADABLE", f"the file is damaged ({type(e).__name__})") from e


def _pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages)


def _docx(data: bytes) -> str:
    # Every paragraph, wherever it sits: CV templates put contact details in headers and
    # lay out columns with tables and text boxes. Headers come first, footers last.
    document = Document(BytesIO(data))
    rels = document.part.rels.values()
    headers = [rel.target_part.element for rel in rels if rel.reltype == RT.HEADER]
    footers = [rel.target_part.element for rel in rels if rel.reltype == RT.FOOTER]
    # ponytail: a text box saved with a VML fallback is read twice; harmless for the LLM.
    return "\n".join(
        "".join(text.text or "" for text in paragraph.iter(qn("w:t")))
        for part in [*headers, document.element.body, *footers]
        for paragraph in part.iter(qn("w:p"))
    )
