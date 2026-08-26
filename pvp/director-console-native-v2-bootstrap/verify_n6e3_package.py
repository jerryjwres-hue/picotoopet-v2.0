from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-dir', required=True)
    parser.add_argument('--zip', required=True)
    args = parser.parse_args()
    package = Path(args.package_dir)
    zip_path = Path(args.zip)
    manifest = json.loads((package / 'release-manifest.json').read_text(encoding='utf-8'))

    assert manifest['release_type'] == 'prebuilt'
    assert manifest['target'] == 'win-x64'
    assert manifest['freeze_id'] == 'PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1'
    assert manifest['version'].startswith('2.0.0-n6e3-prebuilt-')
    for key in ('source_build_on_user_pc', 'sdk_install_on_user_pc', 'model_download_on_install', 'media_submission_on_install'):
        assert manifest[key] is False, key

    for entry in manifest['files']:
        path = package / 'payload' / entry['path']
        assert path.is_file(), entry['path']
        assert sha256(path) == entry['sha256'], entry['path']
        assert path.stat().st_size == entry['size_bytes'], entry['path']

    extension = package / 'payload/extension'
    assert not any('__pycache__' in p.parts or p.suffix == '.pyc' or 'tests' in p.parts for p in extension.rglob('*'))
    server = (extension / 'src/pvp_director_native_v2/server_v2.py').read_text(encoding='utf-8')
    for endpoint in ('/api/v2/nodes/batch-delete-preview', '/api/v2/nodes/batch-delete', '/api/v2/deleted/batch-restore-preview', '/api/v2/deleted/batch-restore'):
        assert endpoint in server, endpoint

    for file_name in ('Install-PvpDirectorConsolePrebuilt.N6E3.ps1', 'INSTALL_PVP_DIRECTOR_CONSOLE.cmd', 'README_INSTALL_CN.txt'):
        text = (package / file_name).read_text(encoding='utf-8-sig')
        assert 'N6E22' not in text, file_name
        assert 'N6E3' in text, file_name

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not name.startswith('/') and '..' not in Path(name).parts for name in names)
        assert archive.testzip() is None

    expected_sidecar = zip_path.with_suffix(zip_path.suffix + '.sha256')
    sidecar_digest = expected_sidecar.read_text(encoding='ascii').split()[0]
    assert sidecar_digest == sha256(zip_path)
    print(f'N6E3_PACKAGE_CONTRACT=PASS payload_files={len(manifest["files"])} zip_entries={len(names)} sha256={sidecar_digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
