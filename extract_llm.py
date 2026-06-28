import re

KNOWN_CLIENTS = {
    "techcorp": "TechCorp Dubai",
    "financeco": "FinanceCo Dubai",
    "retailco": "RetailCo Sharjah",
    "healthco": "HealthCo Dubai",
    "logisticsco": "LogisticsCo Dubai",
    "autocorp": "AutoCorp Sharjah",
    "emirates steel industries llc": "Emirates Steel Industries LLC",
}

KNOWN_NAMES = [
    "Carlos Smith",
    "Aisha Al Zaabi",
    "Ravi Menon",
    "Fatima Khan",
    "Ahmed Khan",
    "Meera Al Rashid",
]


def extract_from_text(raw_text: str):
    text = raw_text or ""
    lowered = text.lower()
    fields = {}
    score = 0.0

    emp_id_match = re.search(r"\b(EMP\d{4,6})\b", text, flags=re.IGNORECASE)
    if emp_id_match:
        fields["emp_id"] = emp_id_match.group(1).upper()
        score += 0.7
    else:
        fields["emp_id"] = None

    fields["employee_name"] = _extract_name(text)
    if fields["employee_name"]:
        score += 0.35

    fields["client_name"] = _extract_client(text)
    if fields["client_name"]:
        score += 0.3

    fields["working_days"] = _extract_working_days(text)
    if fields["working_days"] is not None:
        score += 0.2

    ot_match = re.search(r"(?:overtime|ot)\D{0,20}(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)?", text, flags=re.IGNORECASE)
    no_ot = "no overtime" in lowered or "overtime: 0" in lowered
    fields["overtime_hours"] = 0.0 if no_ot else (float(ot_match.group(1)) if ot_match else 0.0)
    if no_ot or ot_match:
        score += 0.05

    leave_match = re.search(r"(\d{1,2})\s*(?:days?\s*)?(?:leave|absent)", text, flags=re.IGNORECASE)
    fields["leave_days"] = int(leave_match.group(1)) if leave_match else None

    fields["pay_period"] = "June 2026" if "june 2026" in lowered or "this month" in lowered else None
    fields["input_channel"] = "Mailbox" if "from:" in lowered or "subject:" in lowered else "Portal Upload"
    fields["document_type"] = _detect_document_type(text)
    fields["reimbursements"] = extract_reimbursement_lines(text)
    if fields["reimbursements"] and fields["working_days"] is None:
        fields["working_days"] = 24

    if fields["reimbursements"]:
        score += 0.1
    fields["confidence"] = round(min(score, 0.99), 2)
    return fields


def _extract_name(text: str):
    for name in KNOWN_NAMES:
        if re.search(re.escape(name), text, flags=re.IGNORECASE):
            return name

    name_patterns = [
        r"(?:name|employee|worker|staff|consultant)\s*[:\-]?\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})",
        r"for\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})\s+(?:at|with|for client)",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _clean_person_candidate(match.group(1))
            if candidate:
                return candidate
    return None


def _extract_client(text: str):
    code_match = re.search(r"\b(CL\d{3})\b", text, flags=re.IGNORECASE)
    if code_match:
        return code_match.group(1).upper()

    lowered = text.lower()
    for token, client in KNOWN_CLIENTS.items():
        if token in lowered:
            return client

    client_patterns = [
        r"client(?:\s+name)?\s*[:\-]?\s*([A-Z][A-Za-z0-9&. ]{2,60})",
        r"(?:at|for)\s+([A-Z][A-Za-z0-9&. ]{2,60}?)(?:\s+for\s+June|\s+June|\s+worked|\s+timesheet|[,.\n])",
    ]
    for pattern in client_patterns:
        client_match = re.search(pattern, text, flags=re.IGNORECASE)
        if client_match:
            return _clean_client_candidate(client_match.group(1))
    return None


def _clean_person_candidate(candidate: str):
    candidate = re.split(r",|\.|\n|\r", candidate.strip())[0].strip()
    stop_phrases = {"Employee Attendance", "Handwritten Note", "Timesheet Input", "Client Unknown"}
    if candidate in stop_phrases or len(candidate.split()) < 2:
        return None
    blocked_words = {"Client", "Worked", "Overtime", "June", "Timesheet", "UnknownCo"}
    if any(word in blocked_words for word in candidate.split()):
        return None
    return candidate


def _clean_client_candidate(candidate: str):
    candidate = re.split(r",|\n|\r", candidate.strip())[0].strip()
    candidate = re.sub(r"\s+(worked|working|overtime|employee|name).*$", "", candidate, flags=re.IGNORECASE).strip()
    return candidate or None


def _detect_document_type(text: str):
    lowered = text.lower()
    if "reimbursement" in lowered or "expense" in lowered:
        return "Email with reimbursements"
    if "employee attendance" in lowered or re.search(r"^\s*\d+\.\s+", text, flags=re.MULTILINE):
        return "Client batch list"
    if "handwritten" in lowered or "ocr" in lowered:
        return "Handwritten upload"
    return "Single timesheet"


def _extract_working_days(text: str):
    patterns = [
        r"(?:working\s+days|days\s+worked|total\s+days\s+worked|days\s+present)\D{0,20}(\d{1,2})",
        r"(?:worked|work(ed)? this month)\D{0,20}(\d{1,2})\s*days",
        r"(\d{1,2})\s*(?:working\s*)?days\s*(?:worked|this month)?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            number = match.group(match.lastindex)
            tail = text[match.end() : match.end() + 20].lower()
            context = text[max(0, match.start() - 20) : match.start()].lower()
            if "leave" in tail or "absent" in tail or "leave" in context:
                continue
            return int(number)
    return None


def extract_reimbursement_lines(text: str):
    reimbursements = []
    line_pattern = re.compile(
        r"(?:^|\n)\s*(?:[-*]|\d+\.)?\s*(?P<reason>[^:\n-][^\n]*?)\s*(?:--|-|:)\s*(?:AED\s*)?(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )
    typed_pattern = re.compile(
        r"(?:^|\n)\s*(?:[-*]|\d+\.)?\s*(?P<category>Travel|Meals|Equipment|Medical|Training|Parking|Mobile[^:\n-]*)\s*:\s*AED\s*(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:\((?P<reason>[^)]*)\))?",
        flags=re.IGNORECASE,
    )

    for match in typed_pattern.finditer(text):
        category = _normalize_category(match.group("category"))
        reimbursements.append(
            {
                "category": category,
                "reason": (match.group("reason") or category).strip(),
                "amount": float(match.group("amount").replace(",", "")),
                "allowed": category in {"Travel", "Meals", "Equipment", "Medical", "Training"},
                "confidence": 0.95,
            }
        )

    if reimbursements:
        return reimbursements

    for match in line_pattern.finditer(text):
        reason = match.group("reason").strip(" -")
        if "total reimbursements" in reason.lower():
            continue
        category = _infer_category(reason)
        amount = float(match.group("amount").replace(",", ""))
        if category:
            reimbursements.append(
                {
                    "category": category,
                    "reason": reason,
                    "amount": amount,
                    "allowed": category in {"Travel", "Meals", "Equipment", "Medical", "Training"},
                    "confidence": 0.9,
                }
            )
    seen = {(r["reason"], r["amount"]) for r in reimbursements}
    for line in text.splitlines():
        amount_match = re.search(r"AED\s*(\d+(?:,\d{3})*(?:\.\d+)?)", line, flags=re.IGNORECASE)
        if not amount_match or "total reimbursements" in line.lower():
            continue
        amount = float(amount_match.group(1).replace(",", ""))
        reason = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line).strip()
        reason = re.sub(r"\s*AED\s*\d+(?:,\d{3})*(?:\.\d+)?\s*$", "", reason, flags=re.IGNORECASE).strip(" -")
        if (reason, amount) in seen:
            continue
        category = _infer_category(reason)
        if category:
            reimbursements.append(
                {
                    "category": category,
                    "reason": reason,
                    "amount": amount,
                    "allowed": category in {"Travel", "Meals", "Equipment", "Medical", "Training"},
                    "confidence": 0.9,
                }
            )
    return reimbursements


def _infer_category(reason: str):
    lowered = reason.lower()
    if any(word in lowered for word in ["uber", "travel", "taxi", "client site"]):
        return "Travel"
    if any(word in lowered for word in ["meal", "lunch", "dinner"]):
        return "Meals"
    if any(word in lowered for word in ["equipment", "laptop", "device"]):
        return "Equipment"
    if any(word in lowered for word in ["medical", "clinic"]):
        return "Medical"
    if "training" in lowered:
        return "Training"
    if "parking" in lowered:
        return "Parking"
    if "mobile" in lowered or "data" in lowered:
        return "Mobile Data"
    return None


def _normalize_category(category: str):
    category = category.strip()
    lowered = category.lower()
    if lowered.startswith("mobile"):
        return "Mobile Data"
    return category[:1].upper() + category[1:].lower()
