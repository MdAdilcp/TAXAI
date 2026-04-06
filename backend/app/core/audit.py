"""Audit logging for tax calculations and submissions."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# Simple file-based audit for MVP; replace with DB writer in production
AUDIT_DIR = Path(os.getenv("AUDIT_LOG_DIR", "./audit_logs"))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def audit_log(
    action: str,
    user_id: str | None = None,
    filing_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "user_id": user_id,
        "filing_id": filing_id,
        "details": details or {},
        "ip": ip,
    }
    path = AUDIT_DIR / f"audit_{datetime.utcnow().strftime('%Y%m%d')}.ndjson"
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
