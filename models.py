"""Job data model for queuectl."""
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class Job:
    """Represents a background job in the queue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    command: str = ""
    state: str = "pending"
    attempts: int = 0
    max_retries: int = 3
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    next_retry_at: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None
    priority: int = 0
    run_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)