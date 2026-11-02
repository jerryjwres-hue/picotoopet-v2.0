# Exact native Windows FFmpeg configure evidence — Issue #191 addendum

This is the **observed** (not reconstructed) native `ffmpeg.exe -hide_banner -version` configuration from the exact three-tool candidate used in the controller's actual synthetic 3×WebM CPU end-to-end run.

- GitHub native run: [`41496240941`](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/41496240941), artifact ID `13165574216` (`P0Q2-UNAPPROVED-Observer-Supply-Candidate-3`).
- Controller's independently downloaded GitHub artifact ZIP: **147,631,143 bytes**, SHA256 `c3ccfe9f4d5d58b8dd41a27b82cc2a54b1c535e1ce33952c201ee2b36f49b587`.
- ZIP entry `ffmpeg-version.txt`: **2,431 raw bytes**, SHA256 `eae75193f2bd03d00a746e5fe6be599dd96c5d6b097535ae21adaf61ac2d43ad`.
- ZIP entry `ffprobe-version.txt`: **2,404 raw bytes**, SHA256 `c199ad92745990d9aceb8e42162c6006ccc81efa3e1d79cb3d8c955d6575ab52`.
- Exact pinned executable: `ffmpeg.exe` 131,782,656 bytes, SHA256 `896537df94a49decaab75e9d5c9e19fdf1e8335f7f8e2f719cb917132063e06c`.
- Runtime version: `n8.1.3-29-gad3b795b72-20261101`; compiler GCC `16.2.0`, crosstool-NG `1.29.0.7_b1a94f6`.

## Full observed configuration

```text
configuration: --prefix=/ffbuild/prefix --pkg-config-flags=--static --pkg-config=pkg-config --cross-prefix=x86_64-w64-mingw32- --arch=x86_64 --target-os=mingw32 --enable-version3 --disable-debug --disable-w32threads --enable-pthreads --enable-iconv --enable-zlib --enable-libxml2 --enable-libvmaf --enable-fontconfig --enable-libharfbuzz --enable-libfreetype --enable-libfribidi --enable-lcms2 --enable-vulkan --enable-libshaderc --enable-libdav1d --enable-libvorbis --enable-librav1e --enable-librsvg --disable-libxcb --disable-xlib --disable-libpulse --enable-gmp --enable-lzma --enable-liblcevc-dec --enable-opencl --enable-amf --enable-libaom --disable-avisynth --enable-chromaprint --disable-libdavs2 --disable-libdvdread --disable-libdvdnav --disable-libfdk-aac --enable-ffnvcodec --enable-cuda-llvm --disable-frei0r --enable-libgme --enable-libkvazaar --enable-libaribb24 --enable-libaribcaption --enable-libass --enable-libbluray --enable-libjxl --enable-libmp3lame --enable-libopus --enable-libplacebo --enable-librist --enable-libssh --enable-libtheora --enable-libvpx --enable-libwebp --enable-libzmq --enable-lv2 --enable-libvpl --enable-openal --enable-liboapv --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenh264 --enable-libopenjpeg --enable-libopenmpt --disable-librubberband --enable-schannel --enable-sdl2 --enable-libsnappy --enable-libsoxr --enable-libsrt --enable-libsvtav1 --enable-libtwolame --enable-libuavs3d --disable-libdrm --enable-vaapi --enable-vapoursynth --disable-libvidstab --enable-libvvenc --disable-whisper --disable-libx264 --disable-libx265 --disable-libxavs2 --disable-libxvid --enable-libzimg --enable-libzvbi --extra-cflags=-DLIBTWOLAME_STATIC --extra-cxxflags= --extra-libs=-lgomp --extra-ldflags=-pthread --extra-ldexeflags= --cc=x86_64-w64-mingw32-gcc --cxx=x86_64-w64-mingw32-g++ --ar=x86_64-w64-mingw32-gcc-ar --ranlib=x86_64-w64-mingw32-gcc-ranlib --nm=x86_64-w64-mingw32-gcc-nm --extra-version=20261101
```

## Bounded conclusion

- The previously missing **actual executable configuration string** is now evidenced by hashed raw native output, including positive and excluded features. It is not a proof of the original compiler invocation, final resolved dependency closure or exact object linkage.
- `--enable-version3` is present; `--enable-gpl` and `--enable-nonfree` are absent. LGPLv3 and exact third-party library obligations require separate license review.
- Some flags can identify optional loaders/headers rather than actually embedded binary code. Actual linked libraries, patches, dependency-source closure and precise reproducibility still require build logs, config headers, link maps and corresponding source delivery.
- GitHub source archive pointers and upstream versions do not themselves fulfill a matching source delivery or relink-material obligation.
- **COMPLIANCE REMAINS BLOCKED**; this addendum does not approve internal/public EXE distribution, set `user_install_allowed`, modify Worker/Core/C011, or request a GPU run.
