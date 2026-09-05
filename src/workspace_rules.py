"""Pure validation helpers for multi-company workspaces and intake roots."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Iterable


MAX_COMPANY_NAME_CHARS = 100
MAX_INTAKE_FILES_PER_SCAN = 250
MAX_INTAKE_FILE_BYTES = 2 * 1024 * 1024
_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,79}$")


def normalize_company_name(value: object) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    if not 2 <= len(name) <= MAX_COMPANY_NAME_CHARS:
        raise ValueError("Company name must be between 2 and 100 characters")
    if any(ord(character) < 32 for character in name):
        raise ValueError("Company name contains unsupported control characters")
    return name


def new_company_workspace_id(name: str) -> str:
    normalized = normalize_company_name(name)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")[:40]
    slug = slug or "company"
    return f"company-{slug}-{uuid.uuid4().hex[:8]}"


def validate_workspace_id(value: object) -> str:
    workspace_id = str(value or "").strip().casefold()
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ValueError("Workspace ID is invalid")
    return workspace_id


def scoped_external_id(workspace_id: str, external_id: object) -> str:
    """Return an internal ID that cannot collide with another company."""

    workspace = validate_workspace_id(workspace_id)
    supplied = re.sub(r"\s+", " ", str(external_id or "")).strip()
    if not supplied or len(supplied) > 160 or any(ord(character) < 32 for character in supplied):
        raise ValueError("Source record ID must be between 1 and 160 characters")
    if workspace in {"business", "personal"}:
        # Preserve the stable identifiers used by the bundled demonstration.
        return supplied
    return f"{workspace}--{supplied}"


def validate_intake_root(value: object, *, forbidden_roots: Iterable[Path] = ()) -> Path:
    supplied = str(value or "").strip()
    if not supplied or len(supplied) > 1_000:
        raise ValueError("Choose an existing intake folder")
    original = Path(supplied).expanduser()
    if original.is_symlink():
        raise ValueError("An intake root cannot be a symbolic link")
    try:
        resolved = original.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Choose an existing intake folder") from exc
    if not resolved.is_dir():
        raise ValueError("The intake path must be a folder")
    if resolved == Path(resolved.anchor):
        raise ValueError("A drive root is too broad for an intake folder")
    for forbidden in forbidden_roots:
        try:
            if resolved == forbidden.expanduser().resolve(strict=False):
                raise ValueError("Choose a dedicated intake folder, not this broad application or profile root")
        except OSError:
            continue
    return resolved


def discover_intake_json(root: Path, *, include_subfolders: bool) -> tuple[list[Path], list[str]]:
    iterator = root.rglob("*.json") if include_subfolders else root.glob("*.json")
    discovered: list[Path] = []
    errors: list[str] = []
    for path in sorted(iterator, key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        if len(discovered) >= MAX_INTAKE_FILES_PER_SCAN:
            errors.append(f"Scan stopped at the {MAX_INTAKE_FILES_PER_SCAN}-file safety limit")
            break
        try:
            if path.stat().st_size > MAX_INTAKE_FILE_BYTES:
                errors.append(f"{path.name}: file exceeds the 2 MB safety limit")
                continue
        except OSError:
            errors.append(f"{path.name}: file could not be inspected")
            continue
        discovered.append(path)
    return discovered, errors


__all__ = [
    "MAX_INTAKE_FILE_BYTES",
    "MAX_INTAKE_FILES_PER_SCAN",
    "discover_intake_json",
    "new_company_workspace_id",
    "normalize_company_name",
    "scoped_external_id",
    "validate_intake_root",
    "validate_workspace_id",
]
