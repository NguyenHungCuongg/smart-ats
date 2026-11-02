"""Document Extraction (FR-C2.1): raw text from a JD or CV Document."""

from copy import copy
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

# A DOCX is a ZIP: 300 KiB can unzip to 100 MiB of XML, which python-docx parses whole into
# ~1.5 GB of RAM. Twice the 10 MB upload limit of FR-A1.2 leaves room for any real DOCX.
MAX_DOCX_UNZIPPED_BYTES = 20 * 1024 * 1024


class ExtractionError(Exception):
    """A document whose text cannot be extracted; `code` goes to the Upload Batch item (ERD)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


def document_type(data: bytes) -> Literal["pdf", "docx", "txt"] | None:
    """pdf, docx or txt, told by magic bytes as extract_text does (NFR-SEC-07), never by the
    file name or Content-Type."""
    if _is_pdf(data):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        # Any ZIP starts so (XLSX, JAR…): a DOCX is one holding a Word document.
        try:
            names = ZipFile(BytesIO(data)).namelist()
        except Exception:
            # A malformed archive raises BadZipFile, NotImplementedError, UnicodeDecodeError…
            return None
        return "docx" if "word/document.xml" in names else None
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in decoded else "txt"


def extract_text(data: bytes) -> str:
    """Text of a PDF with a text layer, a DOCX or a UTF-8 text file, told apart by magic bytes."""
    text = _read(data)
    if not text.strip():
        # ponytail: a scan with a few stray glyphs still passes; phase-2 OCR fallback needs a ratio.
        raise ExtractionError("NO_TEXT", "the document has no text layer (scanned or empty)")
    return text


def _read(data: bytes) -> str:
    try:
        if _is_pdf(data):
            return _pdf(data)
        if data.startswith(b"PK\x03\x04"):
            return _docx(data)
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ExtractionError("UNSUPPORTED_FORMAT", "not a PDF, DOCX or UTF-8 text file") from e
    except ExtractionError:
        raise
    except FileNotDecryptedError as e:
        raise ExtractionError("ENCRYPTED_PDF", "the PDF is password-protected") from e
    except Exception as e:
        # Parsers raise many exception types on malformed input; all mean the same to the caller.
        raise ExtractionError("UNREADABLE", f"the file is damaged ({type(e).__name__})") from e


def _is_pdf(data: bytes) -> bool:
    # Some writers put a newline before the header, and readers open such a file; any other
    # byte there means it is not a PDF.
    return data.lstrip().startswith(b"%PDF")


def _pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages)


def _docx(data: bytes) -> str:
    _check_unzipped_size(data)
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


def _check_unzipped_size(data: bytes) -> None:
    # The declared sizes are the attacker's, and ZipFile.read inflates a whole entry before
    # cutting it to its declared size. So unzip every entry in small reads, past what it
    # declares, counting the real bytes.
    archive = ZipFile(BytesIO(data))
    unzipped = 0
    for entry in archive.infolist():
        if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
            # zipfile inflates bzip2 and LZMA without a bound; Word writes neither.
            raise ExtractionError("UNREADABLE", "the DOCX uses an unsupported compression")
        entry = copy(entry)
        entry.file_size = MAX_DOCX_UNZIPPED_BYTES + 1
        with archive.open(entry) as stream:
            while chunk := stream.read(64 * 1024):
                unzipped += len(chunk)
                if unzipped > MAX_DOCX_UNZIPPED_BYTES:
                    limit = MAX_DOCX_UNZIPPED_BYTES // 2**20
                    raise ExtractionError(
                        "DOCX_TOO_LARGE", f"the DOCX unzips to more than {limit} MiB"
                    )
