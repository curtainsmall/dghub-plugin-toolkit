"""Manifest validation logic, matching the DGHub plugin spec (SDK v1)."""

import re
from typing import Any

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

VALID_FIELD_TYPES: frozenset = frozenset({
    "bool", "percent", "duration", "number", "text",
    "select", "channel", "preset", "path",
})

VALID_CAPABILITIES: frozenset = frozenset({"startup_check"})

REQUIRED_MANIFEST_FIELDS = ("id", "name", "version", "sdk")

# ---------------------------------------------------------------------------
# validators
# ---------------------------------------------------------------------------


def validate_manifest(data: dict) -> list[str]:
    """Return a list of error messages (empty = valid)."""
    errors: list[str] = []

    # -- required top-level fields --
    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")

    if not errors:
        # id
        if not isinstance(data["id"], str) or not ID_PATTERN.match(data["id"]):
            errors.append("id 必须匹配模式 ^[a-z][a-z0-9_-]{1,31}$")

        # name
        if not isinstance(data["name"], str) or not data["name"].strip():
            errors.append("name 不能为空")

        # version (semver)
        if not isinstance(data["version"], str) or not SEMVER_PATTERN.match(data["version"]):
            errors.append("version 必须是有效的语义化版本号 (semver)")

        # sdk
        if data.get("sdk") != "1":
            errors.append('sdk 必须是 "1"')

    # -- capabilities --
    caps = data.get("capabilities", {})
    if not isinstance(caps, dict):
        errors.append("capabilities 必须是对象")
    else:
        for key in caps:
            if key not in VALID_CAPABILITIES:
                errors.append(f"未知的 capability: {key}")
        if caps.get("startup_check") and not isinstance(caps["startup_check"], bool):
            errors.append("capabilities.startup_check 必须是布尔值")

    # -- config_schema --
    errors.extend(validate_config_schema(data.get("config_schema", [])))

    # -- entry (optional but must be a string if present) --
    if "entry" in data and data["entry"] is not None:
        if not isinstance(data["entry"], str):
            errors.append("entry 必须是字符串")

    return errors


def validate_config_schema(schema: Any) -> list[str]:
    """Validate the config_schema array."""
    errors: list[str] = []
    if not isinstance(schema, list):
        return ["config_schema 必须是数组"]

    for i, section in enumerate(schema):
        if not isinstance(section, dict):
            errors.append(f"config_schema[{i}] 必须是对象")
            continue
        if "section" not in section:
            errors.append(f"config_schema[{i}] 缺少 section 名称")
        if "fields" not in section or not isinstance(section["fields"], list):
            errors.append(f"config_schema[{i}] 缺少 fields 数组")
            continue
        for j, field in enumerate(section["fields"]):
            errors.extend(validate_field(field, i, j))

    return errors


def validate_field(field: Any, section_idx: int, field_idx: int) -> list[str]:
    """Validate a single config field."""
    errors: list[str] = []
    if not isinstance(field, dict):
        return [f"config_schema[{section_idx}].fields[{field_idx}] 必须是对象"]

    # required: key, type, label
    if "key" not in field or not isinstance(field["key"], str):
        errors.append(f"config_schema[{section_idx}].fields[{field_idx}] 缺少 key")
    if "type" not in field or field.get("type") not in VALID_FIELD_TYPES:
        valid = ", ".join(sorted(VALID_FIELD_TYPES))
        errors.append(
            f"config_schema[{section_idx}].fields[{field_idx}].type "
            f"必须是以下之一: {valid}"
        )
    if "label" not in field or not isinstance(field.get("label"), str):
        errors.append(f"config_schema[{section_idx}].fields[{field_idx}] 缺少 label")

    # type-specific checks
    ftype = field.get("type")
    if ftype == "select" and "options" not in field:
        errors.append(
            f"config_schema[{section_idx}].fields[{field_idx}] "
            f"type=select 时需要提供 options"
        )

    return errors


def is_valid_manifest(data: dict) -> bool:
    """Quick check — returns True if manifest is valid."""
    return len(validate_manifest(data)) == 0
