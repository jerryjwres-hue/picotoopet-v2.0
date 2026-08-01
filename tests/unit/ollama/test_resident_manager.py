import httpx

from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import ResidentManager, ResidentStatus


def test_resident_manager_preloads_with_negative_keep_alive() -> None:
    """已安装但未运行的主模型必须使用 keep_alive=-1 预加载。"""

    requests: list[httpx.Request] = []
    ps_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal ps_calls
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gpt-oss:20b"}]})
        if request.url.path == "/api/ps":
            ps_calls += 1
            models = [] if ps_calls == 1 else [{"name": "gpt-oss:20b"}]
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        raise AssertionError(request.url.path)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")
    manager = ResidentManager(OllamaClient("http://ollama", client=http), "gpt-oss:20b")

    result = manager.ensure_resident()

    assert result.status is ResidentStatus.RESIDENT
    generate = next(request for request in requests if request.url.path == "/api/generate")
    assert generate.read().decode("utf-8").find('"keep_alive":-1') >= 0


def test_resident_manager_reports_missing_model_without_pull() -> None:
    """主模型缺失时只报告，不在后台擅自下载大模型。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        raise AssertionError("缺失模型时不得继续请求。")

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")
    manager = ResidentManager(OllamaClient("http://ollama", client=http), "gpt-oss:20b")

    assert manager.ensure_resident().status is ResidentStatus.MODEL_MISSING
