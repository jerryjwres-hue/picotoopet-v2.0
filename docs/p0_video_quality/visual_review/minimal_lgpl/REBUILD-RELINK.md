# Matching-source / rebuild / relink instructions for owner review

**Documentation only; not executed again. COMPLIANCE=BLOCKED.** Target the one
known native run/source in REPORT.md. Do not run on the user's daily computer,
replace a production receipt, distribute candidates, or restart Windows CI for
this documentation amendment. Existing build and VP8/VP9 PASS remains unchanged.

## Versioned kit content

Use SOURCE-EVIDENCE.json's immutable URLs, exact revisions and compressed-byte
SHA256/lengths. Preserve original archives and compare hashes before extraction.
A recipient-ready kit must include:

1. Full FFmpeg and zlib snapshots used by the native run, full COPYING/LICENSE and
   source/header notices, original zlib `win32/Makefile.gcc` and all generated-table
   headers it consumes. No cherry-picked nine-source subset in place of full zlib.
2. Full MinGW-w64 snapshot at the declared CRT commit and relevant LLVM source at
   the declared LLVM commit, including compiler-rt and shared LLVM/CMake build
   inputs if required. The measured compiler-rt component archive is useful source
   evidence, **not automatically a complete standalone LLVM build kit**. Retain
   matching MinGW/LLVM build scripts and all applicable licenses/exceptions.
3. Exact original build recipe: repository workflow
   `.github/workflows/p0q2-minimal-lgpl-cpu-audit.yml` at
   `9e6a469d70c142853b4089d107e8791f0d7ce61a`; no live branch substitution.
   Include original configure argv/config.log/config.mak/config_components.h,
   verbose build/link logs, real maps/imports, tool versions and fixed input hashes.
   These records must come from artifact 13198256716, not a reconstructed success.
4. Documentation identifying source changes. This candidate uses unpatched pinned
   FFmpeg/zlib source; future changes must be dated/described and supplied. Preserve
   MinGW/LLVM upstream build transformations rather than asserting no toolchain
   modifications without original release evidence.
5. Final per-file NOTICE ledger, source-kit manifest and reviewed recipient access
   directions. A manifest URL alone is not a fulfilled source delivery or written
   offer. CRT-MEMBERS.tsv now binds all 51 MinGW and six UCRT-extra members to source;
   the three startup mappings are in SOURCE-EVIDENCE.json. Remaining compiler/
   header/FFmpeg input coverage and final recipient delivery still need review.

The toolchain ZIP/MSYS2 base hashes remain in the original workflow; supply them
only through an authorized build-input route, with their own terms reviewed.
An owner-controlled clean build environment may use these to rebuild FFmpeg while
maintaining access to source for incorporated runtimes. This is not a requirement
that the end user compile or a permission to ship the developer toolchain.

## Rebuild the original application and linked libraries

The authoritative commands are the **unchanged pinned workflow above**. On an
approved isolated Windows build environment:

- Verify/extract fixed FFmpeg/zlib source, LLVM-MinGW and MSYS2 inputs. Use a POSIX
  LLVM bin directory in the MSYS PATH (`cygpath -u`); native drive-letter PATH
  fragments are split incorrectly by the POSIX shell. Use the pinned GNU make.
- In zlib, invoke the original static `libz.a` target with
  `-f win32/Makefile.gcc PREFIX=x86_64-w64-mingw32-` and explicit MSYS `SHELL`.
  Copy only the original headers and static library into the isolated prefix.
- Configure **inside** the extracted FFmpeg tree, as the successful native run did.
  Retain all original target/compiler/module flags. Native GNU make cannot read
  the previous out-of-tree MSYS `/d/...` source path. No source patch is needed.
- Build ffmpeg.exe/ffprobe.exe with the original map options; keep actual link
  commands/imports/configs and new candidate hashes. Do not infer bit equality:
  timestamps/paths and toolchain build provenance require separate analysis.

Actual configuration selects static built-in VP8/VP9/PNG, image2/Matroska,
file/pipe, required filters and zlib; disables autodetection/network/hardware/GPL/
nonfree. LGPL version3 is selected. The exact flag list is in the pinned recipe and
original log, not this prose summary. The tested media fixtures and observer stay
unchanged; no new invocation is required for the current documentation task.

## Modify and relink

For an authorized recipient/library-modification exercise, retain the FFmpeg CLI
application source (`fftools` and supporting code), library source, zlib source,
headers and all necessary scripts/configs so the application can be recombined
with a modified compatible library. LGPLv3 §4(d)(0) permits Corresponding Application
Code in source and/or object form; supplying source plus a sufficient build route
may avoid requiring the old application's object files. Sufficiency is still an
owner review question, not established by a source archive alone.

After documented library changes, clean stale objects, rebuild the affected static
library/headers and rebuild/relink the CLI using the original flags/map targets.
Supply modified sources/patches and regenerated build instructions as required.
Do not demand proprietary WPF object/source disclosure solely because it invokes
these independent command-line programs; assess each actual combination. Retain
terms permitting required library modification and debugging/reverse engineering,
and applicable Installation Information. OS system-library treatment must be
assessed separately from MinGW wrappers/compiler runtime code incorporated into
the executable.

No relink was performed by this amendment. It supplies a concrete draft route;
the original artifact, full linked-file reconciliation and a complete available
source kit/delivery mechanism are still required before the owner can approve
source/notice closure. No legal, patent or distribution PASS is claimed.


## Concrete delivery route to prepare, not an asserted existing service

For a future authorized **digital** binary delivery, the narrow proposed route is
GPLv3 §6(d) direct corresponding-source access at the binary's designated download
place (or an equivalently accessible source service clearly identified there),
with equivalent access and no additional charge. Include LGPLv3 §4(d)(0)
application source/build/relink materials and applicable notices. This proposal is
not selection or fulfilment of a written offer; no offer is made by this document.

After the two remaining input/license reconciliations, assemble a source-only
versioned archive tied to **both exact candidate EXE SHA256s** in REPORT.md, containing
all required original/modified/generated sources or generators/configuration,
recipe/log provenance, final notices and sufficient rebuild/relink material. Verify
its archive member inventory, hashes and available source contents. Do not insert
an EXE, toolchain binary ZIP or installable payload into that source archive.

Before calling delivery complete, record the actual source archive filename,
length/SHA256, recipient-readable location, complete source manifest, terms
permitting the required modification/relink/debugging, and responsible distributor
availability/maintenance arrangement. Verify recipient access and continued
availability under the chosen conveyance conditions. Do not rely on the Actions
artifact's seven-day retention or a local workspace file as the lasting fulfilment
mechanism. No target hosting location/terms have been approved or published here.
A concrete source-only review kit can be staged for owner review once its contents
are complete; this task does not authorize public release or binary distribution.
