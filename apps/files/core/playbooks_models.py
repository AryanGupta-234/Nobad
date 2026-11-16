from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
import uuid


class PlaybookSafetyTier(StrEnum):
    SAFE = "safe"                    # Safe / read-only commands (e.g. ss -tulpn)
    SUDO = "sudo"                    # Requires root privileges (e.g. certbot renew)
    DESTRUCTIVE = "destructive"      # Destructive / resource purging (e.g. docker prune)


class PlaybookCategory(StrEnum):
    SECURITY = "security"            # Security, SSL certificates, firewalls
    MAINTENANCE = "maintenance"      # Package cleanup, disk, system logs
    NETWORK = "network"              # Sockets, ports, DNS, routing
    DOCKER = "docker"                # Containers, images, volumes
    DATABASE = "database"            # PostgreSQL, MySQL, Redis
    CUSTOM = "custom"                # Team & personal custom workflows


@dataclass(slots=True)
class PlaybookVariable:
    key: str                         # Placeholder in script e.g. "DOMAIN" -> {{DOMAIN}}
    label: str                       # User-facing label e.g. "Target Domain"
    default_value: str = ""          # Default string or boolean ("true"/"false")
    var_type: str = "text"           # "text", "boolean", "number", "choice"
    options: list[str] = field(default_factory=list) # Options if var_type is "choice"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "default_value": self.default_value,
            "var_type": self.var_type,
            "options": self.options,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlaybookVariable:
        return cls(
            key=str(data.get("key", "")),
            label=str(data.get("label", "")),
            default_value=str(data.get("default_value", "")),
            var_type=str(data.get("var_type", "text")),
            options=list(data.get("options", [])),
            description=str(data.get("description", "")),
        )


@dataclass(slots=True)
class PlaybookRecipe:
    id: str
    title: str
    category: PlaybookCategory | str
    safety: PlaybookSafetyTier | str
    safety_label: str
    description: str
    script_template: str
    variables: list[PlaybookVariable] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    is_prebundled: bool = True
    is_favorite: bool = False
    runtime_estimate: str = "~5s"
    last_run_summary: str = "Never run"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": str(self.category),
            "safety": str(self.safety),
            "safety_label": self.safety_label,
            "description": self.description,
            "script_template": self.script_template,
            "variables": [v.to_dict() for v in self.variables],
            "steps": self.steps,
            "is_prebundled": self.is_prebundled,
            "is_favorite": self.is_favorite,
            "runtime_estimate": self.runtime_estimate,
            "last_run_summary": self.last_run_summary,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlaybookRecipe:
        variables = [PlaybookVariable.from_dict(v) for v in data.get("variables", [])]
        created = datetime.now()
        if "created_at" in data and isinstance(data["created_at"], str):
            try:
                created = datetime.fromisoformat(data["created_at"])
            except Exception:
                pass
        return cls(
            id=str(data.get("id", str(uuid.uuid4()))),
            title=str(data.get("title", "")),
            category=str(data.get("category", PlaybookCategory.CUSTOM)),
            safety=str(data.get("safety", PlaybookSafetyTier.SAFE)),
            safety_label=str(data.get("safety_label", "Safe")),
            description=str(data.get("description", "")),
            script_template=str(data.get("script_template", "")),
            variables=variables,
            steps=list(data.get("steps", [])),
            is_prebundled=bool(data.get("is_prebundled", False)),
            is_favorite=bool(data.get("is_favorite", False)),
            runtime_estimate=str(data.get("runtime_estimate", "~5s")),
            last_run_summary=str(data.get("last_run_summary", "Never run")),
            created_at=created,
        )


@dataclass(slots=True)
class PlaybookExecutionRecord:
    id: str
    recipe_id: str
    recipe_title: str
    profile_id: str | None
    started_at: datetime
    duration_ms: int
    exit_code: int
    status: str                       # "success", "failed", "cancelled"
    log_output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recipe_id": self.recipe_id,
            "recipe_title": self.recipe_title,
            "profile_id": self.profile_id,
            "started_at": self.started_at.isoformat(),
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "status": self.status,
            "log_output": self.log_output,
        }
