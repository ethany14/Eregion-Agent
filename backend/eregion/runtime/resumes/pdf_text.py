"""Resume PDF text extraction shared by the API and the runtime."""
from io import BytesIO

MAX_RESUME_TEXT = 50_000


def extract_pdf_text(content: bytes) -> tuple[str, int]:
    """Selectable text and page count; ValueError with a user-readable reason otherwise."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except Exception as exc:
        raise ValueError("The PDF could not be read.") from exc
    if not text:
        raise ValueError("The PDF does not contain selectable text.")
    if len(text) > MAX_RESUME_TEXT:
        raise ValueError("The extracted resume is longer than 50,000 characters.")
    return text, len(reader.pages)
