from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.enums import ActorType, AuditOutcome
from app.schemas.common import ORMModel


class AuditEntryOut(ORMModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_type: ActorType
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: AuditOutcome
    context: dict[str, Any]
