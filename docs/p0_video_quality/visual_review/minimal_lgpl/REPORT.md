# #195 / Draft #198 — original-input source and notice reconciliation

**TECHNICAL=PASS; COMPLIANCE=BLOCKED.** Native code/build recipe remains
`9e6a469d70c142853b4089d107e8791f0d7ce61a`, [Run 41562913955](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/41562913955).
No build, VP8/VP9 test, product/receipt edit or executable distribution was performed
for this documentation continuation. The existing native PASS is not a new test
at the documentation SHA.

## Original evidence is now independently readable

The owner supplied the **original** Artifact `13198256716` ZIP (60 members,
18,810,027 bytes). Its SHA256 is
`3187d488a360fc854ef27b693b3f9517cf1f49890d06bd208fc529a24d4677e1`;
independent SHA256 and ZIP CRC checks PASS. It contains source/audit evidence and
no executable/DLL/object/archive-library payload. The earlier GitHub Forbidden
error is historical; **artifact access is no longer a closure blocker**. This is
not a regenerated native artifact.

The original maps independently match the controller's hashes:

| File | SHA256 |
|---|---|
| ffmpeg.map | `0e9f9821ba5f29a221a791bb84479493ebb7b8bd3a0510bc43739cf9294fed23` |
| ffprobe.map | `d0ee7a783aabd2538a210b5dafeeeeb945bfd0e0064b362951c3dce7ab85696c` |

Actual native candidate measurements, recorded in the original status.json:

| Tool | Bytes | SHA256 |
|---|---:|---|
| ffmpeg.exe | 4,246,528 | `f5b853eb90b13697b7c4cc7e84c6e670459f3618e6021883e1bafc5e90e563ca` |
| ffprobe.exe | 4,061,184 | `44f915c3f57f39179250c9b7d5c73bfee4773869e9a17db9702ec9e05efc7f88` |

The actual config has ZLIB=1, GPL=0, VERSION3=1, NETWORK=0, and ffmpeg -L identifies
LGPLv3. The unchanged observer's VP8/VP9 positives and same-length tamper negatives
stand. `SOURCE-EVIDENCE.json` now hashes the actual audit files as well as source
archives/notices. The old `archive_tokens=[]` parser is not used as linkage proof.

## Runtime: chkstk is incorporated, not absent

Both original maps contain `chkstk.S.obj:(.text)` and `___chkstk_ms`:

- ffmpeg RVA `00092c04`, size `0x30` bytes;
- ffprobe RVA `000cb764`, same size/symbol.

This supersedes the historical zero-explicit-runtime search result. At LLVM commit
`e21dc4bd5474d04b8e62d7331362edcc5648d7e5`,
`compiler-rt/lib/builtins/x86_64/chkstk.S` declares
`Apache-2.0 WITH LLVM-exception` and defines that Windows x64 stack-probe function.
Its `../assembly.h` helper is included in the source record.

Independently inspected pinned LLVM-MinGW ZIP (SHA256
`f4f3ad8616c4183ce7b0d72df634400945b41ea9816145fc2430df6003455db7`):
`lib/clang/19/lib/windows/libclang_rt.builtins-x86_64.a` contains exactly one
`chkstk.S.obj`. That raw member is PE-x86-64, defines `___chkstk_ms`, and has the
same `0x30`-byte text size. The complete archive has 170 `.obj` members; intersection
of its full member index with each complete map input-label set is **only
chkstk.S.obj**. This is stronger than searching for the string compiler-rt; it is
still bounded to observed labels, not proof about unlabeled/inlined code.

The original compiler.txt identifies Clang 19.1.6, that exact LLVM commit and
`x86_64-w64-windows-gnu.cfg`. The pinned configuration chains into
`mingw32-common.cfg`, selecting compiler-rt/libunwind/lld. At the same LLVM commit,
`MinGW.cpp` selects CRT/MinGW inputs and `CommonArgs.cpp::AddRunTimeLibs` appends
the builtins archive for compiler-rt. Thus archive/source/member/symbol/size and
driver selection all corroborate the binding. **The original audit does not retain
expanded final linker argv/extraction traces or final executable text bytes**, so
this is not claimed as independent exact-byte/archive provenance attestation.
No absence claim for other runtime or short-import code follows from a grep.

Keep the complete Apache2/LLVM-exceptions text, source and applicable header terms;
compiler code is no longer merely a hypothetical NOTICE entry. No new EXE was
obtained or executed to establish these facts.

## MinGW, UCRT and native imports

The completed [CRT-MEMBERS.tsv](CRT-MEMBERS.tsv) still binds 19 MinGW32 + 32
MinGWex + 6 UCRT-extra source files, with source/member hashes and individual terms.
Three startup bindings remain in SOURCE-EVIDENCE.json: crt2 -> crt/crtexe.c,
crtbegin -> crt/crtbegin.c, crtend -> crt/crtend.c. The exact declared CRT source is
`mingw-w64/mingw-w64@d2ee971046e625c35e8818ac1634b00384342249`, selected by
`llvm-mingw@8400557f2b489b1bf1ed29e0e90eb9c27b19688f/build-mingw-w64.sh`.
Full runtime/project/default licenses and selected source prologues are retained.
PD, ZPL2.1, Lucent/David M. Gay and Keith Marshall terms are not conflated.

[NATIVE-IMPORTS.tsv](NATIVE-IMPORTS.tsv) independently enumerates **196 ffmpeg and
185 ffprobe DLL/symbol imports**, each matched to the exact MinGW `.def`/`.def.in`
export expression and source hash. Conditional export macros remain explicit
expressions, not invented generated files. Native target is x86_64; the shared
`def-include/func.def.in` preprocessing source must remain in the source kit.

Imports are Windows KERNEL32/SHELL32/bcrypt and UCRT API sets. These reports do not
include Windows implementation code. The six mapped UCRT-extra C wrappers **are**
incorporated MinGW code and are accounted for separately. In the pinned toolchain,
libmsvcrt.a and libucrt.a are byte-identical (SHA256
`14fb9e2634dfcb8ef478b54322a0b71b7af5e69af3683729ca5a39b5f638e9f1`);
`lib-common/ucrt.mri` combines API import libraries with libucrt_extra.a. Do not
mistake that combined archive for only Windows DLL stubs. Final expanded import
construction/driver records and active header coverage are not established by
DLL enumeration alone.

## FFmpeg actual linked-source and NOTICE mapping

The maps have 299/283 distinct input **labels**, including the `.obj` above; these
are not source-file counts. [FFMPEG-LINKED-SOURCES.tsv](FFMPEG-LINKED-SOURCES.tsv)
matches the original maps to original compile/windres commands and exact source
hashes: **244 ffmpeg / 228 ffprobe compile/resource inputs**. Ten repeated bare
member names (cpu/file/format/options/pthread/rgb2rgb/swscale/utils/version/yuv2rgb)
are disambiguated with their mapped symbol anchors, checked in the relevant source.
Counting each basename once would lose real inputs.

The ledger distinguishes original C sources, windres manifest resources and the
two generated graph resource C inputs. The original log records gzip/CSS reduction
and ffbuild/bin2c generation; corresponding source is the HTML/CSS, manifest,
bin2c generator and exact recipe, not an invented hash of unavailable generated C.
The HTML contains remote import references, not downloaded/bundled JavaScript
implementation. No browser/network retrieval of those references was performed.
Project-level resource scope is distinguished from file-local license prologues.

Per-file notice findings from actual inputs:

- `libavutil/avsscanf.c`: MIT grant, Copyright 2005–2014 Rich Felker et al.
- `libavformat/oggparsevorbis.c`: MIT grant, Copyright 2005 Michael Ahlberg and
  Måns Rullgård. These two actual linked grants were missing from the early sample.
- `libavutil/mathematics.c` and referenced `libavutil/libm.h`: embedded Boost 1.0
  text beyond the LGPL prologue. Keep original source statements; the binary-only
  exception does not permit dropping source notices.
- `sha.c` / `sha512.c`: retain the exact PD/BSD origin credits with LGPL file terms.
- `demux.c`'s ABSDIFF and img2dec.c's BSD platform vocabulary are **not** extra BSD
  license grants; marker-only classification was corrected.
- No IJG-named translation unit appears in the native compile/map inventory. Full
  source retains its original IJG terms; textual-header/template closure is not
  inferred solely from absent object names.

`licenses/FFmpeg-linked-permissive-notices.txt` preserves the exact additional
source notice blocks. Full LGPLv3 and its incorporated GPLv3, source per-file terms,
zlib and runtime notices remain. [NOTICE-DRAFT.txt](NOTICE-DRAFT.txt) is updated for
confirmed chkstk and MIT contributions, **not renamed final** while the gaps below
remain. The old 21-source sample is retained as historical inspection material;
it is superseded for actual input coverage by the native-linked ledger.

All nine linked zlib objects are independently confirmed in both maps and bound
to original static Makefile rules at `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf`.
The complete matching snapshot/headers/notices are required, not a nine-file subset.
FFmpeg/zlib source archive hashes in the supplied ZIP match the originally pinned
inputs. No source patch or runtime receipt substitution occurred.

## Remaining closure: precise gaps, not artifact access

1. **Active transitive headers/generated inputs and final driver/import extraction
   provenance.** The original ZIP contains config/config_components and compile
   commands, but **no `.d` dependencies, `.rsp` expanded linker inputs or `.objs`
   response files**. The log explicitly creates dependency/response paths and
   removes archive response files. The ledger records actual `-MF` paths (including windres forwarding); the two
   generated C resource commands do not emit `.d` files. The 247 unique expected
   dependency files are not claimed present. Exact active header/template inclusion and
   any associated remaining per-file exceptions are therefore not certified.
   The mapped-input/source/driver evidence above is ready for owner review, with
   the stronger exact archive/byte attestation limitation preserved. Do not rerun
   VP8/VP9, rebuild binaries or invent missing records to erase this gap.
2. **Final NOTICE.** Actual translation-unit grants and known exceptions are now
   mapped, but active header/generated-source coverage and project-level resource
   scope still need final review. Keep the complete source and notice statements;
   the current draft cannot be labelled a finished distribution NOTICE.
3. **Recipient-available complete source delivery.** Immutable source archive URLs,
   measured hashes and rebuild/relink instructions exist; a completed, verified
   distributor source bundle, actual recipient endpoint and reviewed conveyance
   conditions do not. The attached audit ZIP is real evidence, not that completed
   kit. REBUILD-RELINK.md proposes direct corresponding-source delivery rather than
   an invented written offer. No replacement audit artifact or public release is
   created to substitute for missing closure.

**Ready for owner review:** verified original evidence, chkstk source/member/driver
corroboration, completed CRT/zlib bindings, actual FFmpeg input/license ledger,
actual imports and draft source/relink materials. **Not ready:** a claim of full
header/extraction closure, final NOTICE, completed recipient delivery or independent
distribution review. COMPLIANCE stays BLOCKED; no user_install_allowed=true,
production pin, installer, UI/Maotai or release-flow change.
