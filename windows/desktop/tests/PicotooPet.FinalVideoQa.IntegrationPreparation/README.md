# Final Video QA — Independent Integration Preparation (C010B)

This directory contains standalone test-only assets, not C010A production code or a second C010A implementation. No Goal Center wiring.

## Media fixture tools

Requires Python 3.10+, ffmpeg/ffprobe, libx264, native AAC. On Windows, from this folder:

    py -3 generate_media_fixtures.py --output .\_generated-qa-fixtures
    py -3 verify_media_fixtures.py --fixtures .\_generated-qa-fixtures
    py -3 -m unittest -v test_preparation_contracts.py

Use an EMPTY disposable output directory. Twenty indexed synthetic media expectations are generated, covering three C005 24fps profiles and negative codec/pixel/fps/duration/audio/stream/hash/decode cases. The fixture oracle checks its own test files; fixture PASS is NOT a C010A QA result and is NOT a Windows E2E acceptance. Missing FFmpeg/ffprobe => UNVERIFIED (exit code 2). Do not commit generated MP4s.

## C009A master manifest negative staging

After a genuine C009A/B master is available in an isolated test root, run:

    py -3 stage_master_manifest_mutations.py --artifact-dir C:\isolated\Master\v1\<job-key>\<MasterInputDigest> --output .\_staged-negative

This validates known C009A v1 manifest fields, then creates isolated copies of real source bits with 17 negative modifications. It never fabricates a fake authoritative master, never edits the input and never invokes unknown C010A APIs. Null manifest-hash variants are NOT_APPLICABLE_TO_SPECIMEN.

## Actual C010A API integration status

The real C010A API has now landed on PR #71. Its audited SHA is
b418777f1e3f72e1eb394a26a1e6202e62e718cc.

New independent C010B tests are in the sibling directory
PicotooPet.FinalVideoQa.IntegrationTests. Its Windows workflow composes C010B
test-only files into a disposable C010A checkout without merge/rebase. Those
tests use the actual FinalVideoQaService.VerifyAsync, receipt/result contracts,
and compile-linked upstream test fixtures.

The 20 synthetic-media fixture oracle cases remain separate from production QA.
The 17 staged MasterManifest mutations still require genuine master specimens.
See coverage_scenarios.json for per-case mapping. Native Windows C010B workflow run 38021044347 completed SUCCESS (15/15 groups, 4/4 real video modes); the 39 mapped cases are marked COVERED_BY_PASS_NATIVE_WINDOWS_SUITE. This is group coverage, not 39 independent test methods.

Do not alter C010A production or reinterpret C009B's mux-only MasterVideoMediaProbe
as the complete final QA probe.

See docs/testing/C010B_FINAL_VIDEO_QA_INTEGRATION_MATRIX_V1.md for the current matrix.
