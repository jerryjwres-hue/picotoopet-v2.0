import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT       = Path(__file__).resolve().parents[2]
CONTRACT   = ROOT / "contracts" / "connector" / "v1"
SCHEMAS    = CONTRACT / "schemas"
FIXTURES   = CONTRACT / "fixtures"
SCHEMA_SET = {
    "connector_event.schema.json",
    "project_manifest.schema.json",
    "artifact_manifest.schema.json",
    "writeback_request.schema.json",
    "writeback_result.schema.json",
    "connector_error.schema.json",
}


def _read_json(path: Path) -> dict[str, object]:
    """读取固定 UTF-8 JSON，避免测试受平台默认编码影响。"""

    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    """把全部合同 Schema 注册到同一 Draft 2020-12 解析器。"""

    registry = Registry()
    for path in sorted(SCHEMAS.glob("*.json")):
        schema   = _read_json(path)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(str(schema["$id"]), resource)
    return registry


def _validator(schema_name: str) -> Draft202012Validator:
    """返回支持跨文件引用的合同校验器。"""

    schema = _read_json(SCHEMAS / schema_name)
    return Draft202012Validator(schema, registry=_registry())


def test_connector_v1_schemas_are_complete_closed_and_valid() -> None:
    """冻结合同必须完整存在、封闭字段并通过 Schema 自校验。"""

    assert {path.name for path in SCHEMAS.glob("*.json")} == SCHEMA_SET
    for name in sorted(SCHEMA_SET):
        schema = _read_json(SCHEMAS / name)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_minimal_connector_event_fixture_is_valid() -> None:
    """最小正例必须能被完整跨文件合同接受。"""

    payload = _read_json(FIXTURES / "valid" / "minimal_connector_event.json")
    _validator("connector_event.schema.json").validate(payload)


def test_path_escape_writeback_is_rejected_for_target_uri() -> None:
    """字段齐全的写回请求仍必须因目录逃逸目标被拒绝。"""

    payload = _read_json(FIXTURES / "invalid" / "path_escape_writeback.json")
    errors  = list(_validator("writeback_request.schema.json").iter_errors(payload))

    assert errors
    assert any(list(error.absolute_path) == ["target_uri"] for error in errors)
    assert not any(list(error.absolute_path) == ["request_digest"] for error in errors)


def test_all_valid_fixtures_are_deterministic_and_secret_free() -> None:
    """发布正例不得含用户路径、令牌或运行时随机值。"""

    forbidden = (
        "192.168.",
        "zhaoyang",
        "token",
        "password",
        "credential",
        "appdata",
    )
    for path in sorted((FIXTURES / "valid").glob("*.json")):
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        assert content.endswith("\n")
        assert not any(value in lowered for value in forbidden)
