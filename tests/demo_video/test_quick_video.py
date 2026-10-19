"""Offline API smoke only: no real local AI or ComfyUI GPU is invoked in CI."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quick_video", ROOT / "scripts/demo_video/quick_video.py")
assert SPEC and SPEC.loader
quick = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quick)


class FakeLocalServices(BaseHTTPRequestHandler):
    """Small deterministic substitute for loopback Ollama and ComfyUI."""
    prompt_id = "12345678-1234-1234-1234-123456789abc"
    posted_prompt: dict | None = None
    model_missing = False

    def _send(self, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: dict) -> None:
        self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802 - HTTP protocol required method name
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/chat":
            assert payload["model"] == "gpt-oss:20b"
            self._json({"message": {"content": json.dumps({
                "title": "项目演示", "voiceover": "展示项目目标",
                "on_screen_text": "项目预览",
                "positive_prompt": "cinematic pet computer animation",
            })}})
        elif self.path == "/prompt":
            self.__class__.posted_prompt = payload["prompt"]
            self._json({"prompt_id": self.prompt_id})
        else:
            self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802 - HTTP protocol required method name
        if self.path == "/object_info":
            info = {node: {"input": {"required": {}}} for node in quick.CLASSES}
            for node, key, model in [
                ("UNETLoader", "unet_name", "wan2.2_ti2v_5B_fp16.safetensors"),
                ("CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
                ("VAELoader", "vae_name", "wan2.2_vae.safetensors"),
            ]:
                info[node]["input"]["required"][key] = [[model] if not self.model_missing else []]
            self._json(info)
        elif self.path == "/history/" + self.prompt_id:
            assert self.posted_prompt is not None
            prefix = self.posted_prompt["10"]["inputs"]["filename_prefix"]
            self._json({self.prompt_id: {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"10": {"gifs": [{
                    "filename": prefix + "_00001.webm", "subfolder": "", "type": "output",
                }]}}
            }})
        elif self.path.startswith("/view?"):
            self._send(bytes.fromhex("1a45dfa3") + b"mock-webm-bytes", "video/webm")
        else:
            self.send_error(404)

    def log_message(self, *args: object) -> None:
        # Keep fake-service logs silent; test assertions own the verdict.
        return


class FirstVideoMockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLocalServices)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.previous = quick.OLLAMA_URL, quick.COMFY_URL
        url = f"http://127.0.0.1:{cls.server.server_port}"
        quick.OLLAMA_URL = quick.COMFY_URL = url

    @classmethod
    def tearDownClass(cls) -> None:
        quick.OLLAMA_URL, quick.COMFY_URL = cls.previous
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.facts = self.root / "facts.md"
        self.facts.write_text("项目名 PicotooPet，目标是本地 AI 视频助手。", encoding="utf-8")
        FakeLocalServices.model_missing = False
        FakeLocalServices.posted_prompt = None

    def test_selected_facts_to_ai_to_single_webm(self) -> None:
        package = quick.prepare(self.facts, self.root / "handoff")
        self.assertEqual(json.loads(package.read_text(encoding="utf-8"))["ai_model"], "gpt-oss:20b")
        video = quick.render(package, self.root / "render", repo_root=ROOT)
        receipt = json.loads((video.parent / "demo-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["prompt_id"], FakeLocalServices.prompt_id)
        self.assertEqual(receipt["sha256"], quick._sha(video.read_bytes()))
        graph = FakeLocalServices.posted_prompt
        self.assertEqual(graph["7"]["inputs"]["length"], 49)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "wan2.2_ti2v_5B_fp16.safetensors")
        self.assertEqual(graph["5"]["inputs"]["text"], "cinematic pet computer animation")

    def test_missing_model_rejects_before_submit(self) -> None:
        package = quick.prepare(self.facts, self.root / "handoff")
        FakeLocalServices.model_missing = True
        with self.assertRaisesRegex(quick.DemoError, "DEMO_COMFY_MODEL_MISSING"):
            quick.render(package, self.root / "render", repo_root=ROOT)
        self.assertIsNone(FakeLocalServices.posted_prompt)

    def test_tampered_profile_rejects_before_submit(self) -> None:
        package = quick.prepare(self.facts, self.root / "handoff")
        doc = json.loads(package.read_text(encoding="utf-8"))
        doc["shot"]["width"] = 8192
        package.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(quick.DemoError, "DEMO_PROFILE_INVALID"):
            quick.render(package, self.root / "render", repo_root=ROOT)
        self.assertIsNone(FakeLocalServices.posted_prompt)

    def test_source_symlink_not_followed(self) -> None:
        link = self.root / "linked.md"
        link.symlink_to(self.facts)
        with self.assertRaisesRegex(quick.DemoError, "DEMO_SOURCE_NOT_FOUND_OR_LINK"):
            quick.prepare(link, self.root / "handoff")


if __name__ == "__main__":
    unittest.main()
