from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "windows/desktop/src/PicotooPet.Desktop/Services"
TESTS = ROOT / "windows/desktop/tests/PicotooPet.PostProductionMaster.SmokeTests"


def read(name: str) -> str:
    return (SERVICES / name).read_text(encoding="utf-8")


def test_c009a_owns_only_new_service_and_isolated_test_files() -> None:
    expected = {
        "PostProductionMasterContracts.cs",
        "PostProductionMasterSourceVerifier.cs",
        "PostProductionMasterArtifactCatalog.cs",
        "PostProductionMasterCompositorService.cs",
    }
    assert expected <= {path.name for path in SERVICES.glob("PostProductionMaster*.cs")}
    assert (SERVICES / "IMasterVideoComposer.cs").is_file()
    assert (TESTS / "PicotooPet.PostProductionMaster.SmokeTests.csproj").is_file()
    assert (TESTS / "Program.cs").is_file()


def test_composer_boundary_has_no_caller_media_or_executable_authority() -> None:
    boundary = read("IMasterVideoComposer.cs")
    assert "IMasterVideoComposer" in boundary
    assert "MasterVideoCompositionRequest" in boundary
    for forbidden in ("Executable", "Codec", "Bitrate", "Filter", "Arguments"):
        assert forbidden not in boundary


def test_master_contract_freezes_profiles_errors_and_exact_catalog() -> None:
    contracts = read("PostProductionMasterContracts.cs")
    catalog = read("PostProductionMasterArtifactCatalog.cs")
    assert 'MasterProfileId = "postproduction.master.v1"' in contracts
    assert 'AudioProfileId = "audio.aac-lc.48k.mono.128k.v1"' in contracts
    assert "NARRATION_SEGMENT_TOO_LONG" in contracts
    assert "MASTER_ARTIFACT_CONFLICT" in contracts
    assert "MasterVideoArtifact" in contracts
    assert "FindVerifiedExactAsync" in catalog
    assert "EnumerateFileSystemEntries" in catalog


def test_source_verifier_rehashes_all_three_upstream_artifact_classes() -> None:
    verifier = read("PostProductionMasterSourceVerifier.cs")
    assert verifier.count("Sha256FileAsync") >= 4
    assert verifier.count("AssertNoLinkEscape") >= 2
    assert "VerifyFinalVideoAsync" in verifier
    assert "VerifyOverlayAsync" in verifier
    assert "VerifyNarrationAsync" in verifier
    assert "sampleFrames * 1_000L" in verifier
    assert "NarrationSegmentTooLong" in verifier


def test_manifest_and_identity_exclude_text_paths_and_timestamps() -> None:
    contracts = read("PostProductionMasterContracts.cs")
    compositor = read("PostProductionMasterCompositorService.cs")
    identity_body = contracts.split("internal static class MasterInputIdentity", 1)[1]
    assert "CreatedAt" not in identity_body
    assert "FilePath" not in identity_body
    assert "WavPath" not in identity_body
    assert ".Text," not in identity_body
    assert "MasterManifest" in compositor
    assert "segment.Text," not in compositor
    assert "private static void WriteNullable" in contracts


def test_async_manifest_reader_keeps_cancellation_last_for_windows_analyzers() -> None:
    verifier = read("PostProductionMasterSourceVerifier.cs")
    assert "string code,\n        CancellationToken cancellationToken)" in verifier


def test_service_uses_identity_scoped_atomic_directory_promotion() -> None:
    service = read("PostProductionMasterCompositorService.cs")
    assert "Directory.Move" in service
    catalog = read("PostProductionMasterArtifactCatalog.cs")
    assert 'OutputFileName = "master.mp4"' in catalog
    assert 'ManifestFileName = "master-manifest.json"' in catalog
    assert "FindVerifiedExactAsync" in service
    assert "IMasterVideoComposer" in service
