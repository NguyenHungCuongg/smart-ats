"""Document Extraction (FR-C2.1): raw text from a JD or CV Document."""

from io import BytesIO

from docx import Document
from docx.table import Table
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
        # ponytail: a scan with a few stray glyphs still passes; OCR fallback (GĐ 2) needs a ratio.
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
    lines = []
    for block in Document(BytesIO(data)).iter_inner_content():
        if isinstance(block, Table):
            # ponytail: nested tables, headers and footers are skipped; add them if CVs need it.
            lines += ["\t".join(cell.text for cell in row.cells) for row in block.rows]
        else:
            lines.append(block.text)
    return "\n".join(lines)
