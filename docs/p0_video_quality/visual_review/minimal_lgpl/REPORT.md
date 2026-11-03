# #195 / Draft #198 — minimal FFmpeg source and notice closure

**TECHNICAL=PASS; COMPLIANCE=BLOCKED.** Native source SHA:
`9e6a469d70c142853b4089d107e8791f0d7ce61a`, [Run 41562913955](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/41562913955).
Unchanged VisualReview passed VP8/VP9 three-WebM, nine PNG/grid/hash and actual
same-length source-tamper -> UNVERIFIED tests. This review does not rebuild or
repeat those tests, modify product pins, or authorize distributing/installing EXEs.

## Evidence boundary and actual linked footprint

The [controller's original-map review](https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/198#pullrequestreview-5746413698)
of artifact `13198256716` reports 299 distinct `.o` labels for ffmpeg and 283 for
ffprobe. Each includes 19 `lib64_libmingw32_a-*`, 32 `lib64_libmingwex_a-*`, six
`lib64_libucrt_extra_a-*`, three startup objects and the same nine zlib objects below. `archive_tokens=[]` is an
incomplete parser result, **not absence of static linkage**. Do not subtract counts
to assert that all remaining inputs are FFmpeg; `.obj`, short-import records,
section inputs and compiler builtins need separate inspection.

Controller-reported candidate measurements (not redistributed):

| Tool | Bytes | SHA256 |
|---|---:|---|
| ffmpeg.exe | 4,246,528 | `f5b853eb90b13697b7c4cc7e84c6e670459f3618e6021883e1bafc5e90e563ca` |
| ffprobe.exe | 4,061,184 | `44f915c3f57f39179250c9b7d5c73bfee4773869e9a17db9702ec9e05efc7f88` |

The native source/audit ZIP digest is
`3187d488a360fc854ef27b693b3f9517cf1f49890d06bd208fc529a24d4677e1`.
Its download through `gh run download` returned Forbidden during this documentation
review. Native counts, imports and binary measurements above therefore cite the
controller's original-artifact inspection, not a new independent map inspection.
The controller subsequently supplied exact 19+32+6 names in
[comment 6593944728](https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/198#issuecomment-6593944728),
[comment 6593948295](https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/198#issuecomment-6593948295) and
[comment 6593952369](https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/198#issuecomment-6593952369).
No further artifact download was attempted. Source/license snapshots and the
pinned LLVM distribution already obtained were inspected locally
without executing tools. [SOURCE-EVIDENCE.json](SOURCE-EVIDENCE.json) distinguishes
these authorities and records measured source/license/archive hashes.

## Exact CRT provenance: what is established and what is missing

[LLVM-MinGW 20241217's immutable recipe](https://github.com/mstorsjo/llvm-mingw/blob/8400557f2b489b1bf1ed29e0e90eb9c27b19688f/build-mingw-w64.sh)
sets `MINGW_W64_VERSION=d2ee971046e625c35e8818ac1634b00384342249` and
`DEFAULT_MSVCRT=ucrt`. The corresponding [full MinGW-w64 source](https://github.com/mingw-w64/mingw-w64/tree/d2ee971046e625c35e8818ac1634b00384342249)
was retrieved/hashed. `build-llvm.sh` selects LLVM `llvmorg-19.1.6`, resolving to
`e21dc4bd5474d04b8e62d7331362edcc5648d7e5`.

The pinned native input ZIP has SHA256
`f4f3ad8616c4183ce7b0d72df634400945b41ea9816145fc2430df6003455db7`.
Its x86_64 `COPYING`, `COPYING.MinGW-w64.txt` and runtime COPYING **exactly match**
the declared MinGW source revision. Actual libmingw32/libmingwex/startup file hashes
are recorded in the evidence JSON. This establishes the release recipe's precise
source selection and consistent notices, not byte-reproducibility or an independent
attestation proving every binary member was built from an unmodified checkout.
The upstream build workflow permits version overrides for scheduled builds; its
release workflow extracts push-build artifacts. Keep the original release/build
parameters if owner review requires stronger source-to-binary binding.

| Native input | Source binding at the exact MinGW revision | License disposition |
|---|---|---|
| 19 selected `lib64_libmingw32_a-*.o` | `mingw-w64-crt/Makefile.am`: `lib64_libmingw32_a_SOURCES=$(src_libmingw32)` | All 19 exact sources and file-local/default terms mapped in CRT-MEMBERS.tsv. |
| 32 selected `lib64_libmingwex_a-*.o` | `lib64_libmingwex_a_SOURCES=$(src_libmingwex) $(src_libmingwex64) $(src_dfp_math)` | All 32 mapped; gdtoa/Lucent, Marshall grants, ZPL2.1 and PD distinctions retained. |
| Six UCRT-extra objects | `lib64_libucrt_extra_a_SOURCES=$(src_ucrtbase64)`; `lib-common/ucrt.mri` incorporates libucrt_extra into the UCRT import archive | All six resolve to MinGW C wrappers, with explicit PD prologues. These are incorporated code, not the Windows DLL implementation. |
| crt2.o | Makefile copies `lib64/crt1.o`, compiled from `crt/crtexe.c` | Source explicitly public domain; retain DISCLAIMER.PD and included-header terms. |
| crtbegin.o / crtend.o | `crt/crtbegin.c` / `crt/crtend.c` | Both source files explicitly public domain; same disclaimer/header qualification. |

The distribution has 31 available libmingw32 members and 289 libmingwex members.
**These are not the selected 19+32**; this review does not invent a subset.
`licenses/MinGW-runtime.txt` contains the redistributable runtime notices, including
BSD/permissive terms; `MinGW-COPYING.txt` has the ZPL2.1 default and exceptions;
`MinGW-project.txt` explains which project notices do not automatically apply to
generated binaries. Do not call all CRT code GPL, LGPL or public-domain-only.
[CRT-MEMBERS.tsv](CRT-MEMBERS.tsv) now gives all **57 exact member -> source**
bindings, full source SHA256, immutable URL, file-local/default disposition and
original-map comment. All 57 labels were also found exactly once in the pinned
x86_64 archives; each archive member was hashed locally without executing it.
Makefile source lists resolve ambiguous names: `strtof.o`
is `gdtoa/strtof.c`, not `stdio/strtof.c`; x86_64 `scalbn.o` is
`math/x86/scalbn.S`, not ARM/softmath. `cfguard` source selection is conditional
on CFGUARD and matches the two mapped CFGuard labels. Corresponding source prologues
are transcribed in `licenses/MinGW-selected-file-notices.txt`.

The file-level distinctions are material: most startup/MinGW32/UCRT wrapper sources
explicitly declare PD; unmarked files such as `cinitexe.c` use the project's
ZPL2.1 default rather than an invented PD grant. `mingw_sformat.c` explicitly
carries ZPL2.1. gdtoa files carry Lucent/David M. Gay permission, documentation
notice/no-endorsement and warranty terms; `mingw_pformat.c` combines those with
Keith Marshall's unrestricted grant/no-warranty text. Other Marshall printf
wrappers have their own grant. Full-source/header and embedded-notice retention
remains required; file prologue review alone is not all transitive header closure.

Windows imports reported in the review are KERNEL32/SHELL32/bcrypt and UCRT API-set
DLLs. An OS import list does not exclude statically linked import thunks/wrappers
or compiler runtime code. Check original verbose link argv, all archive/member and
section inputs, symbols, and compiler default startup/runtime libraries. Inspect
`.obj` and short COFF-import inputs as well as `.o`. Resolve each non-OS wrapper to
MinGW source/`.def` and its terms; Windows OS DLL implementation is a separate
system-library question, not code copied by this PR.

If compiler-rt/builtins are present, use the exact LLVM commit above and its
component source, not GCC's runtime license. `compiler-rt-LICENSE.txt` is Apache2
with LLVM exceptions (including embedded-object permissions); preserve third-party
per-file terms. The component license was checked against the immutable commit.
The controller reports zero explicit compiler-rt/builtins/libgcc/libunwind/libatomic
member names across both maps/build/config logs. Independently, the pinned ZIP's
`bin/mingw32-common.cfg` exactly matches source: `-rtlib=compiler-rt`,
`-unwindlib=libunwind`, `-stdlib=libc++`, `-fuse-ld=lld`. At the exact LLVM commit,
`clang/lib/Driver/ToolChains/MinGW.cpp` selects startup CRT objects and MinGW32/
MinGWex and calls `AddRunTimeLibs` for the non-libgcc runtime. This is positive
driver/source evidence of runtime selection, not merely a grep. Archive selection
does not establish how many members were extracted. **Builtins presence/absence
and any remaining import-code/header exceptions stay unverified**; do not invent
member names. Keep the complete relevant runtime source/licenses in the proposed
kit conservatively and reconcile actual pulled inputs before final closure.

## Nine zlib objects — confirmed applicability, source correspondence checked

Exact source: [zlib 51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf](https://github.com/madler/zlib/tree/51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf).

| Confirmed linked object | Source |
|---|---|
| inflate.o | inflate.c |
| adler32.o | adler32.c |
| zutil.o | zutil.c |
| inffast.o | inffast.c |
| crc32.o | crc32.c |
| inftrees.o | inftrees.c |
| uncompr.o | uncompr.c |
| deflate.o | deflate.c |
| trees.o | trees.c |

All nine exact source files were independently hashed. The archived original
`win32/Makefile.gcc` lists them in OBJS; `.c.o` compiles with CC/CFLAGS and the
`libz.a` target archives OBJS. The existing workflow invokes only that static
target with `PREFIX=x86_64-w64-mingw32-`, original `-O3 -Wall` defaults, no source
patch and no zlib DLL. Compiler arguments/object hashes in the original log remain
the build correspondence evidence; source hashing alone is not object equality.
`zlib.h`, `zconf.h`, deflate/inflate/CRC/table headers and the entire unmodified
snapshot belong in the kit. Keep its original notices and mark any future source
changes. zlib's license permits commercial use subject to its terms; it is not an
LGPL source-offer license, nor clearance for the entire executable.

## FFmpeg file-level terms and NOTICE

The exact [FFmpeg source](https://github.com/FFmpeg/FFmpeg/tree/ad3b795b72388fbb2b216e1e6fd38fba994e1df0)
and root LICENSE/COPYING texts are retained by URL/hash and verbatim license copies.
LGPLv2.1-or-later file grants combine under the selected **LGPLv3**, including the
GPLv3 terms incorporated by LGPLv3. `CONFIG_GPL=0` excludes optional GPL components;
it does not erase permissive notices in LGPL-covered files. Source is unchanged
relative to the pinned snapshot; do not label upstream authors' earlier changes
as changes made by this task.

The evidence ledger hashes 21 specifically inspected source files and retains
their original notice comment blocks in `licenses/FFmpeg-source-notices.txt`; it is **not**
a complete native-linked translation-unit/header ledger. Preserve these exceptions:

- `libavutil/mathematics.c` and `libavutil/libm.h`: embedded Boost Software License
  1.0 passages, beyond the initial LGPL header. Keep original statements in source;
  the text's machine-executable exception must not be mistaken for a source-copy
  exception. Do not inspect only the first comment block.
- `libavutil/sha.c`: credits public-domain SHA-1 and BSD-derived SHA-2 origins.
  Preserve the exact upstream attribution and review applicable source notices.
- `compat/getopt.c`: LGPL wrapper/file notice and copied public-domain AT&T origin.
- `libavcodec/jfdctfst.c`, `jfdctint_template.c`, `jrevdct.c`: IJG source terms and
  changes/acknowledgment conditions identified by LICENSE.md. Whether these code
  paths survive this binary's link must be checked; no JPEG encoder was selected.
  Retain notices in the complete source even when not linked. A conservative
  draft acknowledgment is provided, without claiming these objects are present.
- `tests/reference.pnm`: Expat source-data exception; not a runtime component merely
  because the full source archive contains it. GPL build/test tools and disabled
  optional codecs likewise do not become shipped components by source presence.

[NOTICE-DRAFT.txt](NOTICE-DRAFT.txt) combines available texts and explicit remaining
slots. Complete file/header notice reconciliation against actual map/config inputs
is still required before calling it a final distribution notice. The separate WPF
process boundary is unchanged; it neither statically links WPF objects to libav*
nor waives standalone FFmpeg source/relink obligations.

## Owner approval readiness

| Material | State |
|---|---|
| Existing native functional evidence, candidate measurements and linked counts | Ready for owner review, attributed to original run/review; no retest. |
| Exact FFmpeg/zlib source, nine zlib source mappings, original build flags | Source evidence ready; original native logs needed for independent object reconciliation. |
| Declared MinGW/LLVM source versions, full CRT source, matching runtime notices, startup mappings | Ready for owner review as documented provenance; not a reproducibility attestation. |
| Recipient rebuild/relink procedure | Draft ready in REBUILD-RELINK.md; not executed again or certified as a completed delivery. |
| Exact 51 MinGW + 6 UCRT wrapper + 3 startup source/version/file-license bindings | Ready for owner review; 57-row hashed ledger plus three startup records and full notice texts. |
| Complete compiler/import/header input coverage and FFmpeg per-file notice reconciliation | **BLOCKED**: zero literal matches do not settle runtime extraction; 21 inspected FFmpeg units are not a complete mapped source/header ledger. |
| Final recipient source bundle, notice placement, source-access/offer route and terms permitting required relink/debugging | **BLOCKED** pending finished ledger and owner-reviewed delivery. |

Use only the existing native artifact and controller extraction to finish any
remaining runtime/header/FFmpeg input reconciliation; the exact 57-member list
is no longer missing. No artifact redownload or rebuild is requested here. Package
matching sources/notices/recipes with hashes, verify recipient availability and
have the owner review the applicable obligations. Patent and
trademark questions remain separate. No `user_install_allowed=true`, legal approval,
production receipt replacement or full-release/Maotai gate change follows here.
