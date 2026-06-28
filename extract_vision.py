import os
import base64
import json
import re
from pathlib import Path

from dotenv import load_dotenv

from extract_llm import extract_from_text

try:
    import anthropic
except Exception:
    anthropic = None

try:
    import fitz
except Exception:
    fitz = None

try:
    from PIL import Image
    import pytesseract
except Exception:
    Image = None
    pytesseract = None

load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=api_key) if anthropic and api_key else None

VISION_PROMPT = """You are TIA, an industrial invoice/timesheet capture agent.
Read this document even if it is handwritten, photographed, a screenshot, skewed, noisy, or partly incomplete.
Return ONLY valid JSON with this schema:
{
  "emp_id": string|null,
  "employee_name": string|null,
  "client_name": string|null,
  "client_code": string|null,
  "pay_period": string|null,
  "working_days": number|null,
  "overtime_hours": number|null,
  "leave_days": number|null,
  "reimbursements": [{"category": string|null, "reason": string|null, "amount": number|null}],
  "document_type": string,
  "extracted_text_summary": string,
  "vision_fields": [{"field": string, "value": string|null, "confidence": number, "note": string}],
  "confidence": number,
  "issues": [string]
}
Confidence must be 0.0 to 1.0. If a field is unreadable, set it null and explain in issues. Do not invent master-data values.
"""


def extract_from_image(image_path: str):
    path = Path(image_path)
    if client:
        result = _extract_with_anthropic(path)
        if result.get("confidence", 0) > 0 or result.get("emp_id") or result.get("employee_name"):
            return _normalize_result(result, "AI vision")

    ocr_text, ocr_issues = _extract_local_text(path)
    if ocr_text.strip():
        extracted = extract_from_text(ocr_text)
        extracted.update({
            "document_type": _document_type(path),
            "input_channel": "Portal Upload",
            "extracted_text_summary": _summarize_text(ocr_text),
            "vision_fields": _fields_from_extracted(extracted, source="Local OCR"),
            "ocr_text": ocr_text[:3000],
            "issues": ocr_issues,
        })
        base_conf = float(extracted.get("confidence") or 0)
        extracted["confidence"] = round(min(base_conf, 0.78), 2)
        return extracted

    return {
        "emp_id": None,
        "employee_name": None,
        "client_name": None,
        "client_code": None,
        "working_days": None,
        "overtime_hours": None,
        "leave_days": None,
        "pay_period": None,
        "reimbursements": [],
        "input_channel": "Portal Upload",
        "document_type": _document_type(path),
        "extracted_text_summary": "No reliable machine-readable text could be extracted.",
        "vision_fields": [],
        "confidence": 0.18,
        "issues": ocr_issues + [
            "No AI vision result and local OCR could not read enough text.",
            "Invoice generation is blocked until a human confirms employee, client, period, and working days.",
        ],
    }


def _extract_with_anthropic(path: Path):
    try:
        media_type, image_data = _document_as_vision_payload(path)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }],
        )
        text_response = response.content[0].text.replace("```json", "").replace("```", "").strip()
        return json.loads(text_response)
    except Exception as exc:
        return {
            "confidence": 0.0,
            "issues": [f"AI vision unavailable or failed: {exc}"],
        }


def _document_as_vision_payload(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        if not fitz:
            raise RuntimeError("PDF rendering library is unavailable")
        doc = fitz.open(str(path))
        if doc.page_count == 0:
            raise RuntimeError("PDF has no pages")
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return "image/png", base64.b64encode(pix.tobytes("png")).decode("utf-8")

    media_type = "image/png" if ext == ".png" else "image/jpeg"
    with open(path, "rb") as handle:
        return media_type, base64.b64encode(handle.read()).decode("utf-8")


def _extract_local_text(path: Path):
    issues = []
    ext = path.suffix.lower()

    if ext == ".pdf" and fitz:
        try:
            doc = fitz.open(str(path))
            text = "\n".join(page.get_text("text") for page in doc)
            if text.strip():
                return text, issues + ["Text extracted from PDF layer; handwriting may still require AI vision."]
        except Exception as exc:
            issues.append(f"PDF text extraction failed: {exc}")

    if Image and pytesseract and ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        try:
            text = pytesseract.image_to_string(Image.open(path))
            if text.strip():
                return text, issues + ["Text extracted with local OCR; confidence capped for review safety."]
        except Exception as exc:
            issues.append(f"Local OCR failed: {exc}")

    if ext == ".pdf" and fitz and Image and pytesseract:
        try:
            doc = fitz.open(str(path))
            if doc.page_count:
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img)
                if text.strip():
                    return text, issues + ["PDF rendered and read with local OCR; confidence capped for review safety."]
        except Exception as exc:
            issues.append(f"Rendered PDF OCR failed: {exc}")

    return "", issues


def _normalize_result(result: dict, source: str):
    result.setdefault("input_channel", "Portal Upload")
    result.setdefault("document_type", "Handwritten/image/PDF timesheet")
    result.setdefault("reimbursements", [])
    result.setdefault("issues", [])
    result.setdefault("vision_fields", _fields_from_extracted(result, source=source))
    result["confidence"] = round(float(result.get("confidence") or 0), 2)
    return result


def _fields_from_extracted(extracted: dict, source: str):
    fields = []
    for key, label in [
        ("emp_id", "Employee ID"),
        ("employee_name", "Employee name"),
        ("client_name", "Client"),
        ("working_days", "Working days"),
        ("overtime_hours", "Overtime hours"),
    ]:
        value = extracted.get(key)
        if value not in (None, ""):
            fields.append({"field": label, "value": str(value), "confidence": int((extracted.get("confidence") or 0.5) * 100), "note": source})
    return fields


def _document_type(path: Path):
    if path.suffix.lower() == ".pdf":
        return "PDF or scanned timesheet"
    return "Image, screenshot, or handwritten timesheet"


def _summarize_text(text: str):
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:500]
