# PVP Director Console Native v2 — N6E Prebuilt Release Bootstrap

This isolated Draft-PR subtree exists only to move the PVP Windows build boundary off the user's PC and onto GitHub `windows-2025` CI.

- `source.part*.b64` reassembles the frozen N6E source bundle produced from the N6D4 checkpoint plus the approved prebuilt-release migration.
- `SOURCE_BUNDLE.sha256` pins the source bundle SHA-256.
- `SOURCE_MANIFEST_SHA256.txt` lists the SHA-256 of every source file inside the bundle.
- The workflow expands the bundle, runs 60 backend tests, 39 Native source contracts, 11 release contracts, Python compileall, .NET 10.0.302 WPF build/publish, Native EXE self-test, final prebuilt ZIP verification under Windows PowerShell 5.1, then uploads the installer artifact.
- The final user installer never runs `dotnet restore/build/publish`, installs an SDK, downloads a model, or submits a ComfyUI generation task.
- This branch must remain Draft/Open/Unmerged until native Windows CI and real-machine installation acceptance are green.

Frozen architecture boundary remains `PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1`.
