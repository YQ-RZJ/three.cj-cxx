# three.cj-cxx

**three.cj-cxx** 是仓颉 3D 引擎运行时 [three.cj](https://atomgit.com/) 的原生依赖层项目：集中托管引擎所需全部 C/C++ 原生库（三方 vendored 源码 + 自研桥接库），并提供一套跨平台 CI 构建体系（`.github/workflows/` + `.github/scripts/`），产出仓颉侧 FFI 绑定包（`bgfx4cj`、`sdl4cj`、`jolt4cj`、`openalsoft4cj` 等）可链接的静态/动态库产物。

> three.cj 项目通过 CI 产物（`native-libs-<platform>-<arch>.zip`，归包至其 `libs/` 目录）消费本项目的构建结果；本项目不包含任何仓颉源码。

## 项目结构

```
cxx/
├── bgfx.cmake/            # 渲染后端（内嵌 bgfx / bimg / bx 及其 3rdparty 嵌套依赖）
├── SDL/                   # 窗口与输入（SDL3）
├── cimgui/                # 即时模式 UI C API（内嵌 Dear ImGui）
├── imgui_impl_bgfx/       # ImGui 的 bgfx 渲染后端
├── JoltPhysics/           # 物理引擎（joltc 依赖其 Jolt 源码）
├── joltc/                 # Jolt 的 C API 封装
├── LuaJIT/                # Lua 解释器与 JIT
├── miniaudio/             # 单头音频引擎
├── openal-soft/           # 音频（OpenAL 实现，内嵌 ghc_filesystem 等）
├── openssl/               # TLS / 加解密（内嵌全量 crypto/ssl 源码）
├── tracy/                 # 实时性能剖析器
├── tlsbridge/             # 自研：OpenSSL 线程桥（httpclient4cj 的 TLS 后端）
├── dlbridge/              # 自研：动态库装载桥（httpclient4cj 动态加载 OpenSSL）
├── requireCJLib/          # 自研：CMake 助手（原生库链接仓颉运行时，含导入桩）
├── requireCJLib-ark/      # 自研：NAPI 变体（仅 OHOS）
├── build.py / clean.py    # 本地一键构建/清理
└── .github/               # CI 工作流与构建组脚本（含 collect_dist.py 归包）
```

## 库清单（含嵌套子依赖）

> 上层仓库内的 `3rdparty/`、`external/` 等嵌套子项目一并列出；版本为编写时源码快照，升级以各子目录内版本头文件为准。

### 渲染后端 — bgfx.cmake

| 库 | 版本 | 协议 | 说明 |
|---|---|---|---|
| bgfx | submodule @ `73d1585f` | BSD-2-Clause | 跨平台渲染抽象（Vulkan/Metal/D3D12/GLES） |
| bx | 随 bgfx | BSD-2-Clause | 基础库（容器/数学/线程） |
| bimg | 随 bgfx | BSD-2-Clause | 图像编解码框架 |
| shaderc_capi / geometryc_capi / bimg_capi | 随 bgfx.cmake | BSD-2-Clause | 本项目构建的 C API 封装层 |
| ↳ bgfx/3rdparty：glslang、spirv-tools、spirv-cross、spirv-headers、khronos、dawn、dear-imgui、directx-headers、metal-cpp、meshoptimizer、stb、cgltf、renderdoc、h264、l-smash、sdf、native_app_glue、d3d4linux 等 | 各随上游 | 各自协议 | bgfx 内嵌三方 |
| ↳ bimg/3rdparty：astc-encoder、dav1d、libavif、etcpak、etc1、etcpack、libsquish、lodepng、nvtt、edtaa3、iqa 等 | 各随上游 | 各自协议 | 纹理编解码三方 |
| ↳ bx/3rdparty：catch 等 | 随上游 | MIT | 测试与基础三方 |

### 窗口 / UI / 输入

| 库 | 版本 | 协议 | 说明 |
|---|---|---|---|
| SDL（SDL3） | 3.5.0 | zlib | 窗口、事件、输入；内嵌 `external/`（LPdir 等） |
| cimgui | 1.92.9 | MIT | Dear ImGui 的 C API 绑定（内嵌 imgui 源码） |
| imgui_impl_bgfx | 随 bgfx | MIT | ImGui 渲染后端（bgfx 实现） |

### 音频

| 库 | 版本 | 协议 | 说明 |
|---|---|---|---|
| openal-soft | 3.18.2 | LGPL-2.1 | OpenAL 实现（含 EFX）；内嵌 ghc_filesystem 等 |
| miniaudio | 0.11.24 | MIT-0 | 单头音频引擎（`openalsoft4cj` 的备用后端） |

### 物理 / 脚本

| 库 | 版本 | 协议 | 说明 |
|---|---|---|---|
| JoltPhysics | 3.16（JPH API 202） | MIT | 物理引擎（刚体/软体/载具/角色） |
| joltc | 随 Jolt | MIT | Jolt 的 C API 封装（供 `jolt4cj`） |
| LuaJIT | 2.1（rolling） | MIT | Lua 解释器与 JIT（供 `luajit4cj`） |

### 网络 / 安全

| 库 | 版本 | 协议 | 说明 |
|---|---|---|---|
| OpenSSL | 3.6.4 | Apache-2.0 | TLS 与加解密（内嵌完整 crypto/ssl 树） |
| tlsbridge（自研） | 同项目 | 同项目 | OpenSSL 线程/回调桥（供 `httpclient4cj`） |
| dlbridge（自研） | 同项目 | 同项目 | 运行时动态装载桥 |

### 剖析 / 运行时对接（自研）

| 组件 | 说明 |
|---|---|
| tracy | 实时剖析器（0.14.1，BSD-3-Clause；供 `tracy4cj`） |
| requireCJLib | CMake 助手：原生库链接仓颉运行时；含无运行时环境的导入桩 `cangjie-runtime-stub.def` |
| requireCJLib-ark | NAPI 变体（仅 OHOS，产出 `librequirecj_napi`） |

## 构建产物

CI 按平台工作流（windows/linux/macos/android/ohos/ios）产出 `native-libs-<platform>-<arch>.zip`：

- **架构**：x86_64 / arm64-v8a
- **模式**：debug / release × static / shared
- 静态包：`.a` / `.lib`；动态包：`.so` / `.dll` / `.dylib` 及配套导入库（`.dll.a` / `.lib`）
- 本地构建：`python build.py`（各平台参数见 `.github/scripts/` 内组脚本帮助）

Windows 工具链注意：必须使用与仓颉 SDK 同代的 **llvm-mingw 20220906（LLVM 15，msvcrt 变体）**——更新版本（LLVM 16+）编出的 C++ 归档引用 `std::exception_ptr::__from_native_exception_pointer`，与仓颉运行时自带的 libc++ 15 链接时报 undefined。

## 许可证

- 本项目（自研组件：joltc / tlsbridge / dlbridge / requireCJLib(-ark) / 构建脚本）以 **Apache-2.0** 许可发布，全文见根目录 [LICENSE](./LICENSE)。
- 各三方库遵循上表所列许可证，全文见各子目录（bgfx 系嵌套三方以各 `3rdparty/` 内声明的为准）。
- 分发时须一并保留各库许可证文本（CI 归包已保留）。
