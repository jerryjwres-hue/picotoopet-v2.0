"""Merge only Owner Structured Review routes into the frozen Mac Core OpenAPI contract."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

_PATH_PREFIX = "/api/v1/owner-structured-reviews/"
_SCHEMA_REF_PREFIX = "#/components/schemas/"


def _schema_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_SCHEMA_REF_PREFIX):
            refs.add(ref.removeprefix(_SCHEMA_REF_PREFIX))
        for item in value.values():
            refs.update(_schema_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_schema_refs(item))
    return refs


def _security_schemes(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        security = value.get("security")
        if isinstance(security, list):
            for requirement in security:
                if isinstance(requirement, dict):
                    names.update(str(name) for name in requirement)
        for item in value.values():
            names.update(_security_schemes(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_security_schemes(item))
    return names


def merge_owner_review_contract(
    frozen: dict[str, Any], generated: dict[str, Any]
) -> dict[str, Any]:
    selected_paths = {
        path: value
        for path, value in generated.get("paths", {}).items()
        if path.startswith(_PATH_PREFIX)
    }
    if len(selected_paths) != 3:
        raise ValueError("OWNER_REVIEW_OPENAPI_PATH_SET_INVALID")

    generated_components = generated.get("components", {})
    generated_schemas = generated_components.get("schemas", {})
    required = _schema_refs(selected_paths)
    pending = list(required)
    while pending:
        name = pending.pop()
        schema = generated_schemas.get(name)
        if not isinstance(schema, dict):
            raise ValueError(f"OWNER_REVIEW_OPENAPI_SCHEMA_MISSING:{name}")
        for dependency in _schema_refs(schema) - required:
            required.add(dependency)
            pending.append(dependency)

    result = json.loads(json.dumps(frozen))
    result.setdefault("paths", {}).update(selected_paths)
    components = result.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for name in sorted(required):
        schemas[name] = generated_schemas[name]
    generated_security = generated_components.get("securitySchemes", {})
    security = components.setdefault("securitySchemes", {})
    for name in sorted(_security_schemes(selected_paths)):
        if name not in generated_security:
            raise ValueError(f"OWNER_REVIEW_OPENAPI_SECURITY_MISSING:{name}")
        security[name] = generated_security[name]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    frozen = json.loads(arguments.output.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="picotoopet-owner-review-openapi-") as temporary:
        app = create_app(
            AppSettings(
                paths=RuntimePaths.from_root(Path(temporary) / "runtime"),
                api_token="owner-review-contract-device-token",
            )
        )
        try:
            generated = app.openapi()
        finally:
            app.state.services.close()
    merged = merge_owner_review_contract(frozen, generated)
    arguments.output.write_text(
        json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
