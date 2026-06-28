from difflib import SequenceMatcher

from master_data import CANONICAL_EMPLOYEES_DF, EMPLOYEES_DF

FUZZY_NAME_THRESHOLD = 0.88
FUZZY_NAME_MARGIN = 0.04


NAME_ALIASES = {
    "ahmad": "ahmed",
    "mohamed": "mohammed",
    "muhammad": "mohammed",
    "mohammad": "mohammed",
}


def match_employee(emp_id=None, name=None, client_name=None):
    """
    Match extracted input against canonical HackArena data first, then the
    spreadsheet fallback. Returns (row_or_none, status, candidates).
    Exact Emp ID/name wins; fuzzy matching is only used for strong spelling
    variants, preferably constrained by client context.
    """
    emp_id = str(emp_id).strip().upper() if emp_id else None
    name = str(name).strip() if name else None
    client_name = str(client_name).strip() if client_name else None

    result = _match_in_df(CANONICAL_EMPLOYEES_DF, emp_id, name, client_name)
    if result[1] != "not_found":
        return result

    return _match_in_df(EMPLOYEES_DF, emp_id, name, client_name)


def _match_in_df(df, emp_id=None, name=None, client_name=None):
    if emp_id:
        match = df[df["Emp ID"].astype(str).str.upper() == emp_id]
        if len(match) == 1:
            return match.iloc[0].to_dict(), "matched", []
        if len(match) > 1:
            return None, "ambiguous", match.to_dict(orient="records")
        return None, "not_found", []

    if name and client_name:
        scoped = _filter_by_client(df, client_name)
        exact = scoped[scoped["Full Name"].astype(str).str.lower() == name.lower()]
        if len(exact) == 1:
            return exact.iloc[0].to_dict(), "matched", []
        if len(exact) > 1:
            return None, "ambiguous", exact.to_dict(orient="records")

        fuzzy = _fuzzy_name_matches(scoped, name)
        if len(fuzzy) == 1:
            return fuzzy[0], "matched", []
        if len(fuzzy) > 1:
            return None, "ambiguous", fuzzy
        return None, "not_found", []

    if name:
        exact = df[df["Full Name"].astype(str).str.lower() == name.lower()]
        if len(exact) == 1:
            return exact.iloc[0].to_dict(), "matched", []
        if len(exact) > 1:
            return None, "ambiguous", exact.to_dict(orient="records")

        fuzzy = _fuzzy_name_matches(df, name)
        if len(fuzzy) == 1:
            return fuzzy[0], "matched", []
        if len(fuzzy) > 1:
            return None, "ambiguous", fuzzy

    return None, "not_found", []


def _filter_by_client(df, client_name):
    client = str(client_name).lower()
    first_token = client.split()[0] if client.split() else client
    return df[
        df["Client Name"].astype(str).str.lower().str.contains(client, na=False)
        | df["Client Code"].astype(str).str.lower().str.contains(client, na=False)
        | df["Client Name"].astype(str).str.lower().str.contains(first_token, na=False)
    ]


def _fuzzy_name_matches(df, name):
    if len(df) == 0:
        return []

    target = _normalize_name(name)
    scored = []
    for _, row in df.iterrows():
        candidate = _normalize_name(row.get("Full Name"))
        if not candidate:
            continue
        score = SequenceMatcher(None, target, candidate).ratio()
        if target.split()[-1:] != candidate.split()[-1:]:
            score -= 0.12
        if score >= FUZZY_NAME_THRESHOLD:
            item = row.to_dict()
            item["match_confidence"] = round(score, 3)
            item["match_reason"] = f"Fuzzy name match: '{name}' -> '{row.get('Full Name')}'"
            scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return []
    if len(scored) == 1:
        return [scored[0][1]]
    if scored[0][0] - scored[1][0] >= FUZZY_NAME_MARGIN:
        return [scored[0][1]]
    return [item for _, item in scored]


def _normalize_name(value):
    words = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in str(value or "")).split()
    words = [NAME_ALIASES.get(word, word) for word in words]
    return " ".join(words)
