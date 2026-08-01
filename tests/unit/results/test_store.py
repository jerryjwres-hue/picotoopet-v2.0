from pathlib import Path

from picotoopet_core.results.store import ResultStore


def test_result_store_is_content_addressed_atomic_and_preserves_source(tmp_path: Path) -> None:
    """结果存储必须按内容寻址，重复复用且不修改源文件。"""

    source = tmp_path / "protected-source.bin"
    source.write_bytes(b"original evidence")
    original_stat = source.stat()
    store = ResultStore(tmp_path / "result-store")

    first = store.put_file(source, result_type="evidence-copy")
    second = store.put_bytes(b"original evidence", result_type="evidence-copy")

    assert first.object_hash == second.object_hash
    assert first.object_path == second.object_path
    assert first.object_path.read_bytes() == b"original evidence"
    assert source.read_bytes() == b"original evidence"
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert store.verify(first.object_hash) is True
