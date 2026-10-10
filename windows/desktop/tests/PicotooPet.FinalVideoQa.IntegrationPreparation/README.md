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

## API gates

Base: ef71d84868e9fc4afd1e8b8f7203d72aa4e12415 (C009A/B). C010A production QA/receipt callable types were not present on this base, so all receipt/restart/lineage/candidate assertions remain BLOCKED_C010A_API. Frozen names from the implementation brief are targets, not implemented invocation signatures; do not invent one. Add a test adapter here ONLY once the actual API lands. Do not modify C010A production files.

C009B FixedMasterVideoProcessRunner exists, but MasterVideoMediaProbe does not contain all stream-index/chapter/per-stream-duration/full-decode facts needed for final C010A QA. Do not substitute this oracle as production QA.

See docs/testing/C010B_FINAL_VIDEO_QA_INTEGRATION_MATRIX_V1.md and coverage_scenarios.json for the full matrix.
