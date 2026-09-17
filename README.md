# three.cj-cxx

**three.cj-cxx** is the native dependency layer of [three.cj](https://atomgit.com/), a 3D engine runtime written in the Cangjie programming language. It hosts all C/C++ native libraries required by the engine (vendored third-party sources + in-house bridging libraries) and provides a cross-platform CI build system (`.github/workflows/` + `.github/scripts/`) that produces static/dynamic library artifacts for the Cangjie-side FFI binding packages (`bgfx4cj`, `sdl4cj`, `jolt4cj`, `openalsoft4cj`, ...).

> The three.cj project consumes this project's build artifacts (via CI archives `native-libs-<platform>-<arch>.zip`, packaged into its `libs/` directory); this project contains no Cangjie source code.

## Project Structure

```
cxx/
├── bgfx.cmake/            # Rendering backend (embeds bgfx / bimg / bx and their 3rdparty deps)
├── SDL/                   # Windowing & input (SDL3)
├── cimgui/                # Immediate-mode UI C API (embeds Dear ImGui)
├── imgui_impl_bgfx/       # bgfx rendering backend for ImGui
├── JoltPhysics/           # Physics engine (joltc builds on its Jolt sources)
├── joltc/                 # C API wrapper for Jolt
├── LuaJIT/                # Lua interpreter & JIT
├── miniaudio/             # Single-header audio engine
├── openal-soft/           # Audio (OpenAL implementation, embeds ghc_filesystem etc.)
├── openssl/               # TLS / cryptography (embeds the full crypto/ssl tree)
├── tracy/                 # Real-time profiler
├── tlsbridge/             # In-house: OpenSSL threading bridge (TLS backend for httpclient4cj)
├── dlbridge/              # In-house: dynamic-loading bridge (httpclient4cj loads OpenSSL dynamically)
├── requireCJLib/          # In-house: CMake helpers (link native libs against the Cangjie runtime, with import stub)
├── requireCJLib-ark/      # In-house: NAPI variant (OHOS only)
├── build.py / clean.py    # One-shot local build/clean
└── .github/               # CI workflows & build-group scripts (incl. collect_dist.py packaging)
```

## Library Inventory (including nested sub-dependencies)

> Nested sub-projects inside upstream repos (`3rdparty/`, `external/`, ...) are listed as well; versions are source snapshots at the time of writing — consult each subdirectory's version headers when upgrading.

### Rendering Backend — bgfx.cmake

| Library | Version | License | Notes |
|---|---|---|---|
| bgfx | submodule @ `73d1585f` | BSD-2-Clause | Cross-platform rendering abstraction (Vulkan/Metal/D3D12/GLES) |
| bx | tracks bgfx | BSD-2-Clause | Foundation library (containers/math/threads) |
| bimg | tracks bgfx | BSD-2-Clause | Image codec framework |
| shaderc_capi / geometryc_capi / bimg_capi | tracks bgfx.cmake | BSD-2-Clause | C API wrappers built by this project |
| ↳ bgfx/3rdparty: glslang, spirv-tools, spirv-cross, spirv-headers, khronos, dawn, dear-imgui, directx-headers, metal-cpp, meshoptimizer, stb, cgltf, renderdoc, h264, l-smash, sdf, native_app_glue, d3d4linux, ... | per upstream | various | third-party deps embedded in bgfx |
| ↳ bimg/3rdparty: astc-encoder, dav1d, libavif, etcpak, etc1, etcpack, libsquish, lodepng, nvtt, edtaa3, iqa, ... | per upstream | various | texture codec third-party deps |
| ↳ bx/3rdparty: catch, ... | per upstream | MIT | test & foundation third-party deps |

### Windowing / UI / Input

| Library | Version | License | Notes |
|---|---|---|---|
| SDL (SDL3) | 3.5.0 | zlib | Windowing, events, input; embeds `external/` (LPdir etc.) |
| cimgui | 1.92.9 | MIT | C API bindings for Dear ImGui (embeds imgui sources) |
| imgui_impl_bgfx | tracks bgfx | MIT | ImGui rendering backend (bgfx implementation) |

### Audio

| Library | Version | License | Notes |
|---|---|---|---|
| openal-soft | 3.18.2 | LGPL-2.1 | OpenAL implementation (with EFX); embeds ghc_filesystem etc. |
| miniaudio | 0.11.24 | MIT-0 | Single-header audio engine (fallback backend for `openalsoft4cj`) |

### Physics / Scripting

| Library | Version | License | Notes |
|---|---|---|---|
| JoltPhysics | 3.16 (JPH API 202) | MIT | Physics engine (rigid/soft bodies, vehicles, characters) |
| joltc | tracks Jolt | MIT | C API wrapper for Jolt (consumed by `jolt4cj`) |
| LuaJIT | 2.1 (rolling) | MIT | Lua interpreter & JIT (consumed by `luajit4cj`) |

### Networking / Security

| Library | Version | License | Notes |
|---|---|---|---|
| OpenSSL | 3.6.4 | Apache-2.0 | TLS & cryptography (embeds the full crypto/ssl tree) |
| tlsbridge (in-house) | this project | this project | OpenSSL threading/callback bridge (for `httpclient4cj`) |
| dlbridge (in-house) | this project | this project | runtime dynamic-loading bridge |

### Profiling / Runtime Integration (in-house)

| Component | Notes |
|---|---|
| tracy | Real-time profiler (0.14.1, BSD-3-Clause; consumed by `tracy4cj`) |
| requireCJLib | CMake helpers: link native libraries against the Cangjie runtime; includes the import stub `cangjie-runtime-stub.def` for environments without the runtime |
| requireCJLib-ark | NAPI variant (OHOS only; produces `librequirecj_napi`) |

## Build Artifacts

CI produces `native-libs-<platform>-<arch>.zip` per platform workflow (windows/linux/macos/android/ohos/ios):

- **Architecture**: x86_64 / arm64-v8a
- **Mode**: debug / release × static / shared
- Static packages: `.a` / `.lib`; shared packages: `.so` / `.dll` / `.dylib` plus import libraries (`.dll.a` / `.lib`)
- Local build: `python build.py` (per-platform options in each group script's help under `.github/scripts/`)

Windows toolchain note: use the **llvm-mingw 20220906 (LLVM 15, msvcrt variant)** matching the Cangjie SDK generation — newer releases (LLVM 16+) emit C++ archives referencing `std::exception_ptr::__from_native_exception_pointer`, which is undefined when linked against the libc++ 15 bundled with the Cangjie runtime.

## Licenses

- This project (in-house components: joltc / tlsbridge / dlbridge / requireCJLib(-ark) / build scripts) is released under the **Apache-2.0** license; see the root [LICENSE](./LICENSE) for the full text.
- Each third-party library remains under its own license listed above; full texts live in each subdirectory (for bgfx-family nested third-party deps, the declarations inside each `3rdparty/` apply).
- Keep each library's license text intact when redistributing (the CI archives already preserve them).
