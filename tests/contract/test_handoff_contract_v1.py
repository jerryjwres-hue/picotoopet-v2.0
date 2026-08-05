import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "handoff" / "v1"
SCHEMAS = CONTRACT / "schemas"
FIXTURES = CONTRACT / "fixtures"
SCHEMA_SET = {
    "handoff.schema.json",
    "handoff_draft.schema.json",
    "acceptance.schema.json",
    "allowed_paths.schema.json",
    "denied_actions.schema.json",
    "cost_budget.schema.json",
    "return_manifest.schema.json",
    "changed_files.schema.json",
    "test_report.schema.json",
    "security_report.schema.json",
}


def _read_json(path: Path) -> dict[str, object]:
    """读取固定 UTF-8 JSON。"""

    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    """注册 Handoff / Return v1 的全部跨文件 Schema。"""

    registry = Registry()
    for path in sorted(SCHEMAS.glob("*.json")):
        schema = _read_json(path)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(str(schema["$id"]), resource)
    return registry


def _validator(schema_name: str) -> Draft202012Validator:
    """返回带完整注册表的 Draft 2020-12 校验器。"""

    schema = _read_json(SCHEMAS / schema_name)
    return Draft202012Validator(schema, registry=_registry())


def _handoff_errors(fixture_name: str) -> list[object]:
    """收集指定 Handoff 攻击 fixture 的全部结构错误。"""

    payload = _read_json(FIXTURES / "invalid" / fixture_name)
    return list(_validator("handoff.schema.json").iter_errors(payload))


def test_handoff_v1_schemas_are_complete_closed_and_valid() -> None:
    """冻结合同必须完整、封闭并通过 Schema 自校验。"""

    assert {path.name for path in SCHEMAS.glob("*.json")} == SCHEMA_SET
    for name in sorted(SCHEMA_SET):
        schema = _read_json(SCHEMAS / name)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_minimal_handoff_fixture_is_valid() -> None:
    """最小批准范围必须能被完整合同接受。"""

    payload = _read_json(FIXTURES / "valid" / "minimal_handoff.json")
    _validator("handoff.schema.json").validate(payload)


def test_protected_source_handoff_is_rejected() -> None:
    """Protected 原件级别不能伪装成允许的外部任务包。"""

    errors = _handoff_errors("protected_source_handoff.json")

    assert errors
    assert any(list(error.absolute_path) == ["sensitivity"] for error in errors)


def test_main_and_out_of_sandbox_write_scope_are_rejected() -> None:
    """外部 Agent 不能编辑 main，也不能写入隔离 worktree 之外。"""

    errors = _handoff_errors("main_write_scope_handoff.json")
    paths = {tuple(error.absolute_path) for error in errors}

    assert errors
    assert ("base_ref",) in paths
    assert any(path[:1] == ("allowed_write",) for path in paths)


def test_valid_handoff_fixture_is_deterministic_and_secret_free() -> None:
    """任务包正例不得含用户目录、局域网地址或凭据字样。"""

    content = (FIXTURES / "valid" / "minimal_handoff.json").read_text(
        encoding="utf-8"
    )
    lowered = content.lower()
    forbidden = (
        "192.168.",
        "zhaoyang",
        "password",
        "credential",
        "appdata",
        "protected/original",
    )

    assert content.endswith("\n")
    assert not any(value in lowered for value in forbidden)
