# #191 — pinned FFmpeg source and notice review

**BLOCKED for complete corresponding-source/NOTICE evidence.** This is a
non-installable documentation kit for owner review, not redistribution clearance.
Only source/license text was downloaded; no executable, binary archive, models or
user device was accessed. No production, packaging, workflow or authorization
change is included. Base: `587dfee76d8778e6bda97d340621ed9d63a193a0`.

## Evidence actually obtained

[Manifest](source-notice-manifest.json) records the Issue #191 binary pins as
**controller-supplied facts**, separately from independently downloaded/hashed
source snapshots and verbatim license texts. Source archive hashes are measured
on the downloaded compressed bytes, not invented binary hashes or a claim of
reproducible output. Archives are not checked in; URLs and exact lengths/digests
allow independent retrieval. GitHub tarballs omit Git history and submodule trees.

- [FFmpeg exact source](https://github.com/FFmpeg/FFmpeg/tree/ad3b795b72388fbb2b216e1e6fd38fba994e1df0):
  retrieved snapshot, SHA256 `b6031e41f717bf7b2c3addb5a88f2cb7f9d86dceca35d48ad45db93033f06d79`.
- [BtbN exact build source](https://github.com/BtbN/FFmpeg-Builds/tree/5ece62897c650b863c1ddda7b6964845344aef2d):
  retrieved snapshot, SHA256 `3399050a6fb3d93fffb6e6a565889ff02c483fe7b8aea09e95a777043309b1af`.
- [Official FFmpeg legal guidance](https://ffmpeg.org/legal.html): direct request
  returned HTTP 403. Read the [official website's source at a pinned revision](https://github.com/FFmpeg/web/blob/2d2f5f72996cdbc9420a5f0dc9c22a97d54871ae/src/legal),
  including exact-source, build instructions, external-library, notice and patent
  guidance. Its sample checklist describes linking LGPLv2.1 libraries; it is not
  evidence that this version3 static executable is LGPLv2.1-only or compliant.

## License boundary

The WPF/observer calls FFmpeg/FFprobe as separate command-line processes; it does
not thereby statically link proprietary WPF objects to libav*. Treat independent
process aggregation separately from a Combined Work determination; process
separation alone is not a universal legal exemption. Each distributed FFmpeg
executable still statically combines libav* and third-party code. Supply its
applicable corresponding source/build material and notices. Do not infer either
"publish all proprietary WPF source" or "no LGPL obligations" from this boundary.

Pinned FFmpeg `LICENSE.md` and BtbN `defaults-lgpl.sh` select LGPLv3 via
`--enable-version3`; preserve **both LGPLv3 and incorporated GPLv3 texts**.
GPLv3 §§1/4–6 govern corresponding source, modification notices and object-code
conveyance; LGPLv3 §§0/4 add library/Combined Work requirements. For applicable
static combinations, assess Minimal Corresponding Source and Corresponding
Application Code/relinking material and any required Installation Information;
for the FFmpeg tools much application code is in the FFmpeg source itself.
Do not substitute the proprietary WPF object files automatically. Check LGPL2.x
external libraries' own terms/version choices as well. A URL to an upstream
commit is not automatically a complete source delivery or valid written offer.

Prefer supplying the actual matching source kit alongside any approved offline
binary distribution; for a future network distribution, provide equivalent source
access with clear directions under the applicable conveyance option. If choosing
an offer instead, owner review must establish its terms, duration, recipients,
fulfilment and hosting responsibility. No offer is made by this document.
Private testing does not authorize later public/commercial distribution. Patent,
trademark and jurisdiction-specific rights remain separate from copyright notices.

## Trace of target `win64 lgpl 8.1`

All paths below refer to the pinned BtbN source above. `util/vars.sh` selects
`variants/win64-lgpl.sh`; that sources `windows-install-static.sh` and
`defaults-lgpl.sh`. The latter sets `--enable-version3 --disable-debug` and
`LICENSE_FILE=COPYING.LGPLv3`. `addins/8.1.sh` sets `GIT_BRANCH=release/8.1`, and
`ffbuild_ffver` returns 801. `images/base-win64/Dockerfile` sets x86_64 MinGW,
static libgcc/libstdc++ and the cross compiler; `generate.sh` traverses
`zz-final.sh` dependencies, checks predicates and assembles configure flags.
`build.sh` clones a branch and runs `./configure` with the assembled environment,
`--pkg-config-flags=--static`, compiler/linker flags, then `make`/`make install`.
`windows-install-static.sh` copies bin/docs/presets, and `build.sh` copies the
selected FFmpeg license to `LICENSE.txt`; this is **not** a full dependency NOTICE
collection or corresponding-source kit.

**Exact archive's full `ffmpeg -version`/`-buildconf` output is unavailable in this
scope.** Issue #191 attests version3, x264/x265 disabled, and no enable-gpl/nonfree;
it does not provide the full configure string. No binary was fetched or executed
to fill that gap. Preserve the controller's existing native artifact and request
its exact stdout/config log, rather than label a reconstructed command "actual".
`recipe-inventory.tsv` records source expressions, not that missing build log.
`build.sh`'s clone of a branch, mutable `:latest` build images, tag-valued recipes
and toolchain inputs mean the two commits alone do not prove byte reproduction.

## Candidate bill of materials and obligation triage

**Verified** means source/recipe/license observation, not proof of linkage.
**Requires inspection** means resolve against actual configure/config.h, linker
map/pkg-config dependencies and built-source trees. **Unavailable** means required
matching material has not been obtained here. `recipe-inventory.tsv` enumerates
127 source recipes with revisions, predicates, dependency expressions, recursive
fetch/modification indicators and recipe hashes. It includes excluded/build-only
recipes deliberately; do not advertise all 127 as shipped libraries.

| Candidate family | Source evidence and license triage | Remaining material |
|---|---|---|
| FFmpeg libav*/CLI and embedded IJG | Verified exact `LICENSE.md`, LGPLv3, GPLv3 and LGPLv2.1 texts. IJG source headers require attribution and modification accounting. | Actual configuration, changes/diff and shipped correspondence; retain per-file permissive notices. |
| GMP; iconv; FriBidi; libaribb24; LAME; TwoLAME; libass/font stack; libbluray/libudfread; GME; libssh; OpenAL; SoXR; libplacebo; ZVBI; librsvg/GLib/Pango | Requires inspection: likely LGPL families or mixed terms, not one blanket LGPLv3 label. Retrieved exact GMP, FriBidi, OpenAL and librsvg texts; **libass exact COPYING is permissive ISC**, not LGPL. OpenAL's COPYING is Library GPLv2; examine source headers for version choices. | Each actual static dependency's full source, license/version choice, notices, patches and rebuild/relink route; libssh COPYING not fetched from its GitLab repository. |
| Chromaprint + bundled KissFFT | Verified exact LICENSE.md: own code MIT but whole described LGPL2.1 due included FFmpeg code. Recipe explicitly selects bundled KissFFT, not FFTW. | Bundle copied FFmpeg/KissFFT source and notices and actual selection evidence; MIT-only claim would be wrong. |
| SRT; ZeroMQ | Verified exact MPL2 license texts, not LGPL. | Identify covered source files/modifications, provide corresponding Source Code Form and MPL2 executable-form notices; inspect any secondary-license choice. |
| zlib; libpng; XZ; Ogg/Vorbis/Theora; VPX/WebP; AOM/dav1d; Opus; SVT-AV1; rav1e; OpenJPEG; OpenMPT; zimg; Snappy; libaribcaption; kvazaar; OpenAPV; uavs3d; VVenC; LCEVCdec | Requires inspection: permissive/mixed upstream families; codec patent and contributor terms may differ. Verified zlib license only in this row. | Actual included sources, copyright/license text and patent grants/limits at exact revisions. A root license does not cover all bundled code. libpng `LICENSE` path fetch failed; inspect alternate names/source tree. |
| JPEG XL, Brotli, Highway, lcms2; shaderc/glslang/SPIR-V; Vulkan/OpenCL/AMF/NV-codec/oneVPL | Verified JPEG XL BSD3 text and PATENTS; recipes reveal recursive Highway and shaderc dependency fetches. Other exact leaf licenses require inspection. CPU-only invocation does not remove compiled-code notices. | Submodule/dependency revisions, source archives, notices/patent statements; distinguish headers, build tools, linked code and runtime-loaded drivers. No GPU runtime use was performed. |
| FreeType, Fontconfig, HarfBuzz, pixman, PCRE2, libffi and Rust crate closure | Requires inspection: mixed notices/dual-license choices. librsvg Cargo.lock retrieved and hashed locally, not treated as all crate sources. | Rust vendor trees/checksums/license files and recursive source sets, selected font license branch, all actual transitive linked notices. |
| OpenSSL | Recipe uses `openssl-3.6.5` tag; exact tag's LICENSE.txt retrieved (Apache2). On Windows FFmpeg configure skips direct enable-openssl, **SRT still depends on OpenSSL**. | Tag now resolves to `c8bd5a57108599ac650bbae77fcabe3109dab2e8`; immutable license bytes match. Reconcile actual build revision/encryption linkage and NOTICE content. NOTICE.md fetch failed, not proof no NOTICE exists. |
| GCC/libstdc++/libgcc, MinGW/winpthreads and mingw-std-threads | Verified static toolchain settings, recipe pins and base image use. Requires inspection of runtime exception/MinGW notices. | Exact toolchain/image digest, runtime source/exception terms and generated headers/build metadata; do not label all compiler binaries as shipped. |
| x264/x265, Xvid, avisynth, frei0r, davs2/xavs2, DVD libraries, rubberband, vid.stab, FDK-AAC | Verified recipe exclusion for LGPL/nonfree predicates; compare actual buildconf. FFTW GPL2 text was retrieved **only for risk inspection**; rubberband depends on FFTW but is excluded, and presence of a recipe does not prove FFTW is linked. | Establish exclusions in actual build outputs. Any unexpected GPL/nonfree linkage is STOP for review, not permission to silently relicense. |
| libcurl, whisper, Linux X11/PulseAudio/libdrm | Source predicates disable curl at FFVER<=900, whisper unconditionally and those Linux-only components for win64. Not asserted shipped. | Reconcile actual build output; transitive dependencies might still be reachable elsewhere. |
| BtbN build scripts | Verified MIT license copied verbatim. | Preserve attribution when redistributing these scripts and any applied changes; MIT scripts do not relicense built FFmpeg. |

All transitive source tarballs and complete dependency notices remain
**unavailable as a matched kit**. Retrieved root license texts alone are partial
evidence. Included license copies for excluded recipes are review evidence only.

## Short private owner-test checklist / STOP conditions

1. Obtain the controller's existing successful artifact evidence (runs
   `41496240941` / artifact `13165574216`, and `41504652827`), full version/buildconf,
   archive LICENSE, config.h/config.log, dependency/link inventory and build logs.
   Bind to the exact archive/exe pins in the manifest; these run results were
   supplied by #191, not independently revalidated as licensing evidence here.
2. Collect FFmpeg and **reachable** dependency sources at the resolved commits,
   recursive submodules, Rust vendor/Cargo.lock/checksums, applied patches/sed
   changes, generated inputs and build/install instructions. Record archive hashes
   and licenses for each; obtain actual toolchain/image provenance and any
   applicable relinking material. Verify matching against the shipped build.
3. Complete THIRD_PARTY notices from exact source headers/licenses, including IJG,
   permissive attributions, MPL source availability and applicable Apache NOTICEs.
   Finish the draft below; record exact source-kit path/digest and recipient access
   directions. Owner reviews the source delivery/offer route, EULA/reverse-
   engineering constraints where applicable, and separate patent questions.
4. Controller may then review private testing under its existing permissions.
   Do not modify UI/installer/workflow in this docs PR; any required notice placement
   belongs to the appropriate owner. No public binary release, install permission,
   commercial clearance or `user_install_allowed=true` follows from this kit.

**STOP:** source/NOTICE/license evidence is sufficient to review these identified
facts and gaps, **not sufficient to close corresponding-source obligations or
approve redistribution**. Missing actual full configure output, matched recursive
sources/changes, complete notices and reviewed delivery/relink provisions remain
release blockers. No unrelated CI tests can resolve these missing materials.

Verbatim upstream license files retain their original whitespace and Markdown
underlines. Git whitespace checking flags four upstream trailing-space lines and
the Chromaprint heading underline as a conflict-marker pattern; hash comparisons
confirm those bytes are upstream originals, not edited licenses or a merge conflict.
