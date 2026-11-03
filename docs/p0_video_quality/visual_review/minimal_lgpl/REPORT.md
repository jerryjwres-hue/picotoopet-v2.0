# #195 — minimal native Windows CPU candidate

Isolated experiment, not a replacement receipt or distributable binary. Frozen
PicotooPet base: `587dfee76d8778e6bda97d340621ed9d63a193a0`. Current native status:
**UNVERIFIED until the isolated workflow runs**; **COMPLIANCE=BLOCKED**.

The unchanged VisualReview calls are exercised with real candidate FFmpeg/FFprobe,
not mocks. Repository production T2V/I2V WebM workflows specify VP9; independent
96-frame/4-second VP9 fixtures cover that format, with VP8 as an additional test.
Six base64 fixture records contain actual bytes/lengths/SHA256 and generator
arguments/version. A preinstalled CPU FFmpeg encoded synthetic solid colors in
this development environment, independently of the decoder-only candidate; no
user files, GPU, model or ComfyUI. Its encoder executable is not distributed or
included in the candidate. All source attributes were measured using ffprobe.

## Fixed inputs and narrow surface

The workflow checks every archive hash before extracting or running it:

| Input | Exact source/release | SHA256 |
|---|---|---|
| FFmpeg source | `FFmpeg/FFmpeg` `ad3b795b72388fbb2b216e1e6fd38fba994e1df0` | `b6031e41f717bf7b2c3addb5a88f2cb7f9d86dceca35d48ad45db93033f06d79` |
| zlib source | `madler/zlib` `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf` (v1.3.1) | `d9e270d46252734aa49770fbc544125391617956266f220bd63216c834f3a522` |
| Windows LLVM-MinGW build tools | `mstorsjo/llvm-mingw` release `20241217`, UCRT x86_64 ZIP | `f4f3ad8616c4183ce7b0d72df634400945b41ea9816145fc2430df6003455db7` |
| MSYS2 shell/utilities, build-only | `msys2/msys2-installer` release `2025-02-21`, base x86_64 TAR.XZ | `850589091e731d14b234447084737ca62aee1cc1e3c10be62fcdc12b8263d70b` |

Full upstream URLs are literal in the isolated workflow. Source and LLVM hashes
were measured from these upstream downloads; MSYS2 hash is its upstream published
`.sha256` value, rechecked on download by CI. These pins select inputs, not an
independent assertion of upstream signing, legal clearance or bit reproducibility.
No rolling package installation, PATH-discovered FFmpeg, or BtbN binary is used.
The pinned LLVM distribution supplies the compiler, binutils and GNU make; MSYS2
supplies the build shell/utilities. They are build inputs, not upload payloads.
The hosted runner OS/.NET bootstrap remains separately recorded by Actions; one
successful run cannot establish a reproducible toolchain or complete runtime source.

Native source build selects static zlib only as an explicit external library,
using its original `win32/Makefile.gcc` static target. FFmpeg uses built-in VP8,
VP9 and PNG decoders, PNG encoder, Matroska/image2, file/pipe, swscale and the
scale/pad/tile/format/buffer/sink/null/trim/setpts filters needed by the CLI.
External autodetection, network, hardware accelerators, x86 assembler, GPL/nonfree,
audio resampling/device APIs and other programs are disabled. Version3 is selected
explicitly, retaining LGPLv3 and incorporated GPLv3 source license texts. No FFmpeg
source patch or product-code edit is made. Native dependency selections/config,
actual linker maps and COFF imports decide the real linked inventory, not this
planned list. Compiler/runtime and system imports must still be assessed.

## Native evidence and exact acceptance

The one workflow builds on `windows-2025` and invokes the unchanged observer twice
with exactly three WebMs per codec. It checks all nine frame hashes/lengths,
source identity, timestamps, 320×180 frames, a 976×556 sheet and its report SHA256.
A second invocation after same-length source byte tampering must exit 2 with
UNVERIFIED. No VLM arguments are supplied. Exact version/buildconf, configure
command/config.log/config.mak/config headers, verbose build logs, link maps,
imports, binary lengths/hashes and report evidence are retained on success/failure.

Artifact allowlist: evidence, matching FFmpeg/zlib **source** archives and source
licenses only. Candidate EXE, DLL, object/archive libraries, toolchain ZIP and
MSYS2 archive stay under RUNNER_TEMP and are never uploaded. No installer/package,
release or user_install_allowed=true. Missing inputs, native compiler/build or
compatibility errors fail the job and preserve exact logs; do not expand scope to
fix unrelated product/packaging work. Native result/Run ID will be reported with
the final source SHA, not inferred from a Linux cross-build.

## Source/NOTICE closure and recommendation criterion

Compared with #191's broad 127-recipe candidate index, the intended explicit
external library footprint is one zlib rather than the large BtbN pack. This is a
hypothesis until native configuration, link maps and tests confirm it. The actual
archive-member inventory and runtime imports are uploaded for review. Distinguish
FFmpeg's own libav* static modules from additional external libraries.

Corresponding sources are the exact FFmpeg and zlib snapshots, unmodified build
recipe and logs. LGPLv3/GPLv3 and FFmpeg per-file permissive/IJG notices, zlib
copyright/notice, and MinGW/compiler runtime exception/source provenance must be
independently reviewed. Source archives alone do not establish exact compiled
closure, relinking sufficiency, source-offer/hosting obligations or patents. The
WPF process boundary is unchanged and does not waive obligations on the standalone
FFmpeg tools. No compliance or redistribution PASS is asserted.

Recommend replacing the broad-pack *candidate route* only if native VP9 (actual
workflow), VP8, PNG/grid/tamper tests succeed and exact linked/source inventory is
substantially smaller. Otherwise STOP with the exact failing build/test command
and next missing input. Controller retains all decisions about #190/#192/#193/#194,
real-media review, audited production pins, licensing and deployment.
