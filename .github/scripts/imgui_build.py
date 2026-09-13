#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
imgui4cj 全平台自动交叉编译 + 打包脚本
======================================
编译 cimgui (Dear ImGui v1.92.x 的 C 封装) + SDL3 平台后端 + bgfx 渲染后端，
输出静态 / 动态库，供 Cangjie FFI 链接（cjpm.toml 以 -l:libimgui.a 链接，
故 MinGW 静态产物名固定为 libimgui.a；MSVC 产物为 imgui.lib，
打包时另存 libimgui.a 副本于 lib_a/，与 bgfx4cj 的约定一致）。

矩阵:
  平台   LINUX / WINDOWS / ANDROID / OPHM / BSD / EMSCRIPTEN / IOS / OSX
  架构   x86_64 / arm64-v8a   (按平台可选)
  模式   debug / release
  库类型 static / shared
  工具链 mingw / msvc / ndk / ohos / emsdk / xcode / native

说明:
  OPHM = OpenHarmony / HarmonyOS：优先使用 NDK 自带的
  ohos.toolchain.cmake；若无则退回 clang --target=*-linux-ohos
  --sysroot=<sdk>/sysroot 的交叉编译方式。
  ImGui 是纯 C/C++ 源码库，本脚本为每个组合在 output/build-<tag>/ 下
  生成最小 CMakeLists.txt 驱动编译（不依赖 xmake，也不复用 cimgui 上游
  的 CMakeLists——后者只编 cimgui 本体、不含 SDL3/bgfx 后端）。

行为约定（与 sdl4cj / openalsoft4cj / bgfx4cj-tpc 的 build.py 一致）：
  1. 启动时传入编译平台清单（默认全部 8 个平台），脚本对
     debug/release x x86_64/arm64-v8a x static/shared 自动排列组合，
     为每个可编译的平台依次编译，并在每个组合编译成功后立即打包为
     规范命名的 zip；
  2. WINDOWS 平台（Windows 主机上）自动尝试 mingw / msvc(Visual Studio)，
     静态库优先 mingw（Cangjie Windows 目标使用 MinGW ABI 的 libimgui.a），
     失败后自动回退 msvc；x86_64 使用 PATH 中的 mingw-w64 gcc，
     arm64-v8a 使用候选目录 / --mingw 指定的 llvm-mingw（aarch64 三元组）；
  3. LINUX / BSD 平台使用本机原生编译器（clang/gcc 自动探测）；
  4. 需要 NDK / emsdk / OHOS SDK 的交叉编译平台（ANDROID、EMSCRIPTEN、
     OPHM、以及非 Windows 主机上的 WINDOWS 交叉编译），会要求开发者
     提供 SDK 路径（命令行参数 > 环境变量 > 交互询问），无法提供则告警跳过；
  5. IOS / OSX 必须在 macOS 上编译（Xcode 生成器），否则告警跳过；
  6. 默认只编译 static（cjpm.toml 消费 -l:libimgui.a 静态库）。shared 产物
     的 SDL3/bgfx 后端在链接期需要 SDL3/bgfx 预编译库，必须通过 --deps-lib
     （或环境变量 IMGUI_DEPS_LIB_PATH）提供这些库所在目录，否则 shared
     组合告警跳过。

用法示例:
  python build.py                                  # 全部平台 static 排列组合
  python build.py --platforms WINDOWS              # 只编指定平台
  python build.py --platforms OPHM --ohos-sdk D:/sdk/native
  python build.py --modes release --arches x86_64
  python build.py --libtype static                 # 只编静态库（默认）
  python build.py --mingw D:/mingw64               # 指定 mingw-w64 工具链
  python build.py --libtype shared \
      --deps-lib D:/workspace/Projects/three.cj/three/libs
                                                   # 编动态库并链接 SDL3/bgfx 产物
                                                   # （目录内需有 libSDL3.a / libbgfx.a 等）
  python build.py --batch --skip-package           # 非交互、只编译不打包
"""

import argparse
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import zipfile

# CI-PATCH: GitHub Windows runner 默认 cp1252 stdout，中文输出会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # CI 扁平化布局：脚本在 .github/scripts/ 下，cxx 根即项目根
# CI-PATCH: 原 GROUP_DIR 已扁平化删除，以下路径均相对 cxx 根解析
GROUP_DIR = os.path.dirname(os.path.abspath(__file__))  # 仅供 --dist 默认值等 CI 侧用途
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")        # cmake 构建产物根目录
DIST_DIR   = os.path.join(SCRIPT_DIR, "dist")          # zip / 日志输出目录
LOG_DIR    = os.path.join(DIST_DIR, "logs")
LEGACY_BUILD_DIR = os.path.join(SCRIPT_DIR, "build")   # 旧版脚本的构建目录

PKG_PREFIX   = "imgui4cj"   # zip 包名前缀
LIB_BASENAME = "imgui"      # 库产物名（MinGW: libimgui.a；MSVC: imgui.lib）

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OPHM", "BSD", "EMSCRIPTEN", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# 平台 -> 支持的架构
PLATFORM_ARCHES = {
    "LINUX":      ["x86_64", "arm64-v8a"],
    "WINDOWS":    ["x86_64", "arm64-v8a"],
    "ANDROID":    ["arm64-v8a", "x86_64"],
    "OPHM":       ["arm64-v8a", "x86_64"],
    "BSD":        ["x86_64"],
    "EMSCRIPTEN": ["x86_64"],
    "IOS":        ["arm64-v8a", "x86_64"],
    "OSX":        ["arm64-v8a", "x86_64"],
}

# 平台 -> bx 平台宏（与 bgfx4cj-tpc 的 xmake/cmake 编译定义保持一致，
# 保证 imgui_impl_bgfx 包含的 bgfx/bx 头文件按目标平台选取代码路径）
BX_PLATFORM_DEFINE = {
    "LINUX":      ["BX_PLATFORM_LINUX=1"],
    "WINDOWS":    ["BX_PLATFORM_WINDOWS=1"],
    "ANDROID":    ["BX_PLATFORM_ANDROID=1"],
    "OPHM":       ["BX_PLATFORM_OPHM=1", "BX_PLATFORM_LINUX=1"],
    "BSD":        ["BX_PLATFORM_BSD=1"],
    "EMSCRIPTEN": ["BX_PLATFORM_EMSCRIPTEN=1"],
    "IOS":        ["BX_PLATFORM_IOS=1"],
    "OSX":        ["BX_PLATFORM_OSX=1"],
}

# OpenHarmony NDK 默认路径（交互询问时的回车默认值）
OHOS_SDK_DEFAULT = r"D:\Venv\OpenHarmonySDK\23\native"
NDK_DEFAULT      = r"D:\Venv\Android\SDK\ndk\23.2.8568313"

# mingw-w64 工具链候选目录（--mingw 未指定时依次探测；
# llvm-mingw 同时提供 x86_64 / aarch64 两个三元组，是 Windows arm64 交叉编译来源）
MINGW_CANDIDATE_DIRS = [
    r"D:\Venv\C_Cpp\llvm-mingw",
    r"D:\Venv\C_Cpp\mingw-w64\x86_64-13.2.0-release-posix-seh-ucrt-rt_v11-rev0\mingw64",
]

# shared 构建链接 SDL3/bgfx 静态依赖时所需的平台系统库清单
# （与 three/cjpm.toml 各 target 的 link-option 对齐；静态库构建不参与链接，无需此项）
SHARED_SYS_LIBS = {
    "WINDOWS": ["imm32", "winmm", "version", "setupapi", "hid", "dinput8",
                "d3d11", "dxgi", "d3dcompiler", "ws2_32"],
    "ANDROID": ["log", "android", "EGL", "GLESv3"],
    "OPHM":    ["EGL", "GLESv3"],
    "LINUX":   ["X11", "Xext", "Xcursor", "Xi", "Xfixes", "Xrandr", "Xrender",
                "GL", "dl", "pthread", "rt", "m"],
    "BSD":     ["X11", "Xext", "Xcursor", "Xi", "Xfixes", "Xrandr", "Xrender",
                "GL", "dl", "pthread", "m"],
    "IOS":     [],
    "OSX":     [],
    "EMSCRIPTEN": [],
}

# Apple 平台 shared 构建所需 framework（与 three/cjpm.toml darwin target 对齐）
SHARE_APPLE_FRAMEWORKS = [
    "Cocoa", "IOKit", "CoreVideo", "CoreFoundation", "OpenGL",
]

LIB_EXTENSIONS    = (".a", ".lib", ".so", ".dll", ".dylib", ".bc", ".wasm")
HEADER_EXTENSIONS = (".h", ".hpp")

# 依赖路径（cxx/ 集中管理后的 sibling 目录）：仅使用头文件
# 目录布局：three.cj/cxx/{sdl,bgfx,imgui,...}/<各自源码与 build.py>
CXX_ROOT     = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
# CI-PATCH: 目录扁平化后，SDL/bgfx 家族直接位于 cxx 根（原 sdl/SDL、bgfx/bgfx 嵌套已移平）
SDL_DIR  = os.path.join(CXX_ROOT, "SDL")
BGFX_DIR = os.path.join(CXX_ROOT, "bgfx")
BX_DIR   = os.path.join(CXX_ROOT, "bx")
BIMG_DIR = os.path.join(CXX_ROOT, "bimg")

# cimgui / 后端源文件（相对 SCRIPT_DIR）
IMGUI_SOURCES = [
    "cimgui/cimgui.cpp",
    "cimgui/cimgui_impl.cpp",
    "cimgui/imgui/imgui.cpp",
    "cimgui/imgui/imgui_draw.cpp",
    "cimgui/imgui/imgui_tables.cpp",
    "cimgui/imgui/imgui_widgets.cpp",
    "cimgui/imgui/imgui_demo.cpp",
    "cimgui/imgui/backends/imgui_impl_sdl3.cpp",
    "imgui_impl_bgfx/imgui_impl_bgfx_capi.cpp",
]

# 编译期头文件包含目录（相对 SCRIPT_DIR）
IMGUI_INCLUDE_DIRS = [
    "cimgui",                    # cimgui.h, cimgui_impl.h, cimconfig.h
    "cimgui/imgui",              # imgui.h, imgui_internal.h
    "cimgui/imgui/backends",     # imgui_impl_sdl3.h
    "imgui_impl_bgfx",           # imgui_impl_bgfx.hpp
]

# 打包头文件时收集的目录（相对 SCRIPT_DIR）及其排除的子目录名
HEADER_PACK_DIRS = [
    ("cimgui",            {"examples", "docs", "generator", "backend_test",
                           "test", ".github", "misc"}),
    ("imgui_impl_bgfx",   set()),
]

# 依赖头文件包含目录（绝对路径，编译时检测；缺失仅告警）
DEPENDENCY_INCLUDES = [
    ("SDL3", os.path.join(SDL_DIR, "include")),
    ("bgfx", os.path.join(BGFX_DIR, "include")),
    ("bx",   os.path.join(BX_DIR, "include")),
    ("bimg", os.path.join(BIMG_DIR, "include")),
]


# ---------------------------------------------------------------------------
# 主机平台检测（与 bgfx / openalsoft 平台命名一致：WINDOWS / LINUX / OSX ...）
# ---------------------------------------------------------------------------
def detect_host():
    s = _platform.system().lower()
    if "windows" in s:
        return "WINDOWS"
    if "darwin" in s:
        return "OSX"          # macOS
    if "linux" in s:
        return "LINUX"
    if any(k in s for k in ("freebsd", "netbsd", "openbsd", "dragonfly")):
        return "BSD"
    return "OTHER"


def machine_arch():
    """返回 python 视角的本机架构（arm64 / x86_64 / ...）"""
    m = _platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    return m


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="imgui4cj 全平台自动交叉编译 + 打包脚本（CMake 构建 cimgui + SDL3/bgfx 后端）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔，可选: " + ",".join(ALL_PLATFORMS)
                         + "（默认全部，OPHM=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单，逗号分隔: debug,release（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单，逗号分隔: x86_64,arm64-v8a（默认全部）")
    ap.add_argument("--libtype", default="static",
                    help="库类型清单，逗号分隔: static,shared（默认仅 static；"
                         "shared 需链接 SDL3/bgfx 预编译产物，必须同时提供 --deps-lib）")
    ap.add_argument("--deps-lib", action="append", default=None,
                    help="shared 构建依赖的预编译库目录（SDL3/bgfx/bx/bimg 等，"
                         "可重复指定或用 ;/, 分隔；也可用环境变量 IMGUI_DEPS_LIB_PATH）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / ANDROID_NDK_ROOT）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OPHM 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--emsdk", default=None,
                    help="Emscripten SDK 路径（或环境变量 EMSDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 工具链目录（Windows 主机上 mingw 回退 / 非 Windows 主机交叉编译 WINDOWS 时用）")
    ap.add_argument("--android-api", type=int, default=24,
                    help="Android 最低 API 级别（默认 24）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认 = CPU 核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 output/、dist/ 与旧版 build/ 目录")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式：不询问 SDK 路径，缺 SDK 的平台直接跳过并告警")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止（默认继续其余组合）")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
    ap.add_argument("--generator", default=None,
                    help="强制指定 CMake 生成器（默认按平台自动选择，如 Ninja / Visual Studio 17 2022 / Xcode）")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def is_windows():
    return os.name == "nt"


def exe_suffix():
    return ".exe" if is_windows() else ""


def find_tool(name):
    """在 PATH 中查找可执行文件，返回绝对路径或 None"""
    p = shutil.which(name)
    return os.path.abspath(p) if p else None


_BATCH_FLAG = False


def args_batch():
    """供 ask() 查询是否处于批处理模式（避免全局传参）"""
    return _BATCH_FLAG


def set_batch_flag(flag):
    global _BATCH_FLAG
    _BATCH_FLAG = flag


def ask(prompt, default=None):
    """交互询问；非交互（--batch 或非 tty）时返回 None"""
    if args_batch():
        return None
    try:
        if not sys.stdin.isatty():
            return None
        full = prompt
        if default:
            full += " [回车默认: %s]" % default
        ans = input(full + ": ").strip()
        return ans if ans else default
    except (EOFError, KeyboardInterrupt):
        return None


# ---------------------------------------------------------------------------
# SDK 路径解析：命令行参数 > 环境变量 > 交互询问
# ---------------------------------------------------------------------------
def resolve_ndk(args):
    """解析 Android NDK 路径（ANDROID 平台需要）"""
    v = (args.ndk
         or os.environ.get("ANDROID_NDK_HOME")
         or os.environ.get("ANDROID_NDK_ROOT"))
    if not v:
        v = ask("请输入 Android NDK 路径", default=NDK_DEFAULT)
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] NDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_ohos_sdk(args):
    """解析 HarmonyOS / OpenHarmony NDK 路径（OPHM 平台需要）"""
    v = (args.ohos_sdk
         or os.environ.get("OHOS_SDK")
         or os.environ.get("OHOS_NDK_HOME"))
    if not v:
        v = ask("请输入 HarmonyOS / OpenHarmony NDK 路径", default=OHOS_SDK_DEFAULT)
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] OHOS SDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_emsdk(args):
    """解析 Emscripten SDK 路径（EMSCRIPTEN 平台需要）"""
    v = args.emsdk or os.environ.get("EMSDK")
    if not v:
        v = ask("请输入 Emscripten SDK (emsdk) 路径")
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] Emscripten SDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_deps_libs(args):
    """
    解析 shared 构建所需的预编译依赖库目录（SDL3/bgfx/bx/bimg 等）。
    来源：--deps-lib 参数（可重复，分隔符 ;/,/os.pathsep）> 环境变量
    IMGUI_DEPS_LIB_PATH > 交互询问。返回存在的目录列表。
    """
    raw = []
    if args.deps_lib:
        raw.extend(args.deps_lib)
    env_v = os.environ.get("IMGUI_DEPS_LIB_PATH")
    if env_v:
        raw.append(env_v)
    if not raw:
        v = ask("请输入 SDL3/bgfx 预编译库所在目录（shared 构建必需，多个目录用 ; 分隔）")
        if v:
            raw.append(v)
    dirs = []
    for item in raw:
        for p in re.split(r"[;," + re.escape(os.pathsep) + r"]", item):
            p = p.strip()
            if p:
                dirs.append(os.path.normpath(p))
    valid = []
    for d in dirs:
        if os.path.isdir(d):
            valid.append(d)
        else:
            print("  [WARN] 依赖库目录不存在: %s" % d)
    return valid


# ---------------------------------------------------------------------------
# 工具链探测
# ---------------------------------------------------------------------------
def probe_mingw(arch, mingw_dir):
    """
    探测 mingw-w64 工具链。返回 (cc, cxx, rc, ar) 或 None。
    arch: x86_64 -> 本机 gcc / x86_64-w64-mingw32-；arm64-v8a -> aarch64-w64-mingw32-
    探测顺序：Windows 主机本机 gcc（仅 x86_64）-> --mingw 指定目录 ->
    MINGW_CANDIDATE_DIRS 候选目录（含 llvm-mingw，提供 aarch64 交叉三元组）-> PATH。
    """
    exe = exe_suffix()
    if arch == "arm64-v8a":
        triples = ["aarch64-w64-mingw32-"]
    else:
        triples = ["x86_64-w64-mingw32-"]
        # Windows 主机上直接使用本机 mingw-w64（gcc/g++/windres 在 PATH）
        if is_windows():
            local = find_tool("gcc" + exe)
            if local and find_tool("g++" + exe):
                ar = find_tool("ar" + exe) or os.path.join(os.path.dirname(local), "ar" + exe)
                rc = find_tool("windres" + exe)
                return (local, find_tool("g++" + exe), rc, ar)

    # 候选工具链根目录（--mingw 优先，随后是内置候选路径）
    search_dirs = []
    if mingw_dir:
        search_dirs.append(mingw_dir)
    search_dirs += [d for d in MINGW_CANDIDATE_DIRS if os.path.isdir(d)]

    for pre in triples:
        # 1) 指定 / 候选目录的 bin/ 下查找三元组前缀工具
        for d in search_dirs:
            bin_dir = os.path.join(d, "bin")
            cand = os.path.join(bin_dir, pre + "gcc" + exe)
            if os.path.exists(cand):
                def _opt(name):
                    p = os.path.join(bin_dir, pre + name + exe)
                    return p if os.path.exists(p) else None
                return (cand,
                        os.path.join(bin_dir, pre + "g++" + exe),
                        _opt("windres"), _opt("ar"))
        # 2) PATH 中查找
        gcc = find_tool(pre + "gcc" + exe)
        gxx = find_tool(pre + "g++" + exe)
        if gcc and gxx:
            rc = find_tool(pre + "windres" + exe)
            ar = find_tool(pre + "ar" + exe)
            return gcc, gxx, rc, ar
    return None


def probe_ndk_toolchain(ndk):
    """
    探测 Android NDK 的 CMake 工具链文件，返回其绝对路径。
    使用 NDK 自带的 <ndk>/build/cmake/android.toolchain.cmake。
    """
    tc = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
    if os.path.isfile(tc):
        return tc
    # 兜底：扫描 build/ 下可能存在的 toolchain 文件
    build_dir = os.path.join(ndk, "build")
    if os.path.isdir(build_dir):
        for root, _dirs, files in os.walk(build_dir):
            if "android.toolchain.cmake" in files:
                return os.path.join(root, "android.toolchain.cmake")
    raise RuntimeError("无法在 NDK 中找到 android.toolchain.cmake: %s" % ndk)


def probe_ohos(sdk, arch):
    """
    探测 OpenHarmony NDK 工具链。返回 (toolchain_file 或 None, target)。
    优先使用 NDK 提供的 ohos.toolchain.cmake；否则返回 None，
    由调用方生成临时 toolchain 文件（clang --target=*-linux-ohos）。
    """
    for tc in (os.path.join(sdk, "build", "cmake", "ohos.toolchain.cmake"),
               os.path.join(sdk, "native", "build", "cmake", "ohos.toolchain.cmake")):
        if os.path.isfile(tc):
            return tc, None
    exe = exe_suffix()
    cc = os.path.join(sdk, "llvm", "bin", "clang" + exe)
    sysroot = os.path.join(sdk, "sysroot")
    if not (os.path.isfile(cc) and os.path.isdir(sysroot)):
        raise RuntimeError(
            "OHOS SDK 结构不完整，需要 <sdk>/llvm/bin/clang 与 <sdk>/sysroot: %s" % sdk)
    target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    return None, target


def _gen_ohos_toolchain(sdk, target, toolchain_dir):
    """生成临时 OHOS CMake 工具链文件（无 ohos.toolchain.cmake 时的回退方案）"""
    os.makedirs(toolchain_dir, exist_ok=True)
    cc = os.path.join(sdk, "llvm", "bin", "clang" + exe_suffix())
    cxx = os.path.join(sdk, "llvm", "bin", "clang++" + exe_suffix())
    sysroot = os.path.join(sdk, "sysroot").replace("\\", "/")
    proc = "aarch64" if target.startswith("aarch64") else "x86_64"
    tc_path = os.path.join(toolchain_dir, "ohos-%s.cmake" % target)
    content = (
        'set(CMAKE_SYSTEM_NAME Linux)\n'
        'set(CMAKE_SYSTEM_PROCESSOR %s)\n'
        'set(CMAKE_C_COMPILER "%s")\n'
        'set(CMAKE_CXX_COMPILER "%s")\n'
        'set(CMAKE_SYSROOT "%s")\n'
        'set(CMAKE_C_FLAGS "--target=%s")\n'
        'set(CMAKE_CXX_FLAGS "--target=%s")\n'
        'set(CMAKE_EXE_LINKER_FLAGS "--target=%s")\n'
        'set(CMAKE_SHARED_LINKER_FLAGS "--target=%s")\n'
        'set(CMAKE_FIND_ROOT_PATH "%s")\n'
        'set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)\n'
        'set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)\n'
        'set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)\n'
    ) % (proc,
         cc.replace("\\", "/"), cxx.replace("\\", "/"), sysroot,
         target, target, target, target, sysroot)
    with open(tc_path, "w", encoding="utf-8") as f:
        f.write(content)
    return tc_path


def probe_emsdk(emsdk):
    """
    返回 emsdk 的 Emscripten CMake 工具链文件路径。
    优先 upstream 布局，退回 emsdk 根目录。
    """
    for base in (os.path.join(emsdk, "upstream", "emscripten"), emsdk):
        tc = os.path.join(base, "cmake", "Modules", "Platform", "Emscripten.cmake")
        if os.path.isfile(tc):
            return tc
    raise RuntimeError("无法在 emsdk 中找到 Emscripten.cmake: %s" % emsdk)


def probe_vs_generators(cmake_exe):
    """
    从 `cmake --help` 解析可用的 Visual Studio 生成器，按版本号降序返回。
    例如 ["Visual Studio 17 2022", "Visual Studio 16 2019", ...]。
    """
    gens = []
    try:
        out = subprocess.check_output([cmake_exe, "--help"], stderr=subprocess.DEVNULL,
                                      universal_newlines=True, errors="replace")
    except Exception:
        return gens
    for line in out.splitlines():
        m = re.match(r"\s*(Visual Studio \d+ \d{4})\b", line)
        if m:
            gens.append(m.group(1))

    def _key(g):
        mm = re.search(r"(\d+) (\d{4})", g)
        return int(mm.group(1)) if mm else 0
    gens.sort(key=_key, reverse=True)
    return gens


def detect_vs_generator():
    """
    通过 vswhere 探测本机实际安装的 Visual Studio 版本，
    返回与之匹配的生成器名（如 "Visual Studio 17 2022"），未找到返回 None。
    """
    vswhere_candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
        r"C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe",
    ]
    for vswhere in vswhere_candidates:
        if not os.path.isfile(vswhere):
            continue
        try:
            out = subprocess.check_output(
                [vswhere, "-latest", "-products", "*",
                 "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationVersion"],
                stderr=subprocess.DEVNULL, universal_newlines=True, errors="replace")
        except Exception:
            continue
        m = re.match(r"\s*(\d+)\.", out)
        if not m:
            continue
        major = int(m.group(1))
        year = {15: 2017, 16: 2019, 17: 2022, 18: 2026}.get(major)
        if year:
            return "Visual Studio %d %d" % (major, year)
    return None


def pick_ninja():
    """返回 ninja 路径或 None"""
    return find_tool("ninja")


# ---------------------------------------------------------------------------
# 可编译性判定（host 系统约束 + SDK 是否就绪）
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    """
    返回 (ok, reason)。
    ctx: dict 携带 ndk / ohos / emsdk / mingw 等已解析的 SDK。
    """
    if platform == "WINDOWS":
        if host == "WINDOWS":
            # Windows 主机：本机 mingw 或 Visual Studio 任一可用即可
            if ctx.get("vs_generators"):
                return True, ""
            tc = probe_mingw("x86_64", ctx.get("mingw"))
            if tc:
                return True, ""
            return False, "Windows 主机上未检测到 Visual Studio 或 mingw-w64 工具链"
        tc = (probe_mingw("x86_64", ctx.get("mingw"))
              or probe_mingw("arm64-v8a", ctx.get("mingw")))
        if tc:
            return True, ""
        return False, "非 Windows 主机且未检测到 mingw-w64 交叉工具链（x86_64/aarch64-w64-mingw32-gcc）"
    if platform == "LINUX":
        if host == "LINUX":
            return True, ""
        return False, "LINUX 目标需要在 Linux 主机上编译（脚本未配置 Linux 交叉工具链）"
    if platform == "BSD":
        if host == "BSD":
            return True, ""
        return False, "BSD 目标需要在 BSD 主机上编译"
    if platform == "ANDROID":
        if ctx.get("ndk"):
            return True, ""
        return False, "缺少 NDK 路径（--ndk / ANDROID_NDK_HOME / 交互提供）"
    if platform == "OPHM":
        if ctx.get("ohos"):
            return True, ""
        return False, "缺少 OpenHarmony (OHOS) NDK 路径（--ohos-sdk / OHOS_SDK / 交互提供）"
    if platform == "EMSCRIPTEN":
        if ctx.get("emsdk"):
            return True, ""
        return False, "缺少 Emscripten SDK 路径（--emsdk / EMSDK / 交互提供）"
    if platform == "IOS":
        if host != "OSX":
            return False, "IOS 必须在 macOS 上编译（当前主机: %s）" % host
        if not find_tool("xcodebuild"):
            return False, "macOS 上未找到 xcodebuild（需要安装 Xcode）"
        return True, ""
    if platform == "OSX":
        if host != "OSX":
            return False, "OSX 必须在 macOS 上编译（当前主机: %s）" % host
        if not find_tool("xcodebuild") and not find_tool("clang"):
            return False, "macOS 上未找到 clang / xcodebuild（需要 Xcode Command Line Tools）"
        return True, ""
    return False, "未知平台: %s" % platform


# ---------------------------------------------------------------------------
# 工具链 / CMake 生成器选择
# ---------------------------------------------------------------------------
def toolchains_for(platform, host, libtype):
    """
    每个平台候选工具链（按优先级）。
    WINDOWS 主机上静态库优先 mingw（Cangjie Windows 目标消费 MinGW ABI 的
    libimgui.a），失败回退 msvc；动态库同样 mingw 优先。
    """
    _ = libtype
    if platform == "WINDOWS" and host == "WINDOWS":
        return ["mingw", "msvc"]
    return ["native"]


def cmake_generator(platform, toolchain, host, ctx, args):
    """选择 CMake 生成器；--generator 可强制指定"""
    if args.generator:
        return args.generator
    if platform == "WINDOWS" and toolchain == "msvc":
        # 优先用 vswhere 探测到的本机 VS 生成器；否则退回 cmake 支持的最新 VS 生成器
        return (ctx.get("vs_generator")
                or ctx.get("vs_generators", ["Visual Studio 17 2022"])[0])
    if platform in ("IOS", "OSX"):
        return "Xcode"
    # 其余平台优先 Ninja（单配置），无 Ninja 时退回 Makefiles
    if pick_ninja():
        return "Ninja"
    return "MinGW Makefiles" if is_windows() else "Unix Makefiles"


def toolchain_cfg(platform, arch, toolchain, host, ctx, args):
    """
    生成平台/工具链专用的 CMake 参数（不含 -S/-B/-G）。
    返回参数列表。
    """
    cfg = []
    if platform == "WINDOWS":
        if toolchain == "msvc":
            # Visual Studio 多配置生成器：-A 指定架构
            arch_map = {"x86_64": "x64", "arm64-v8a": "ARM64"}
            cfg += ["-A", arch_map.get(arch, "x64")]
        else:
            # mingw（Windows 主机本机或非 Windows 主机交叉）
            tc = probe_mingw(arch, ctx.get("mingw"))
            if tc is None:
                raise RuntimeError("缺少 %s 的 mingw-w64 工具链" % arch)
            cc, cxx, rc, ar = tc
            # CMake 写 .cmake 文件时反斜杠需转义，统一用正斜杠
            cc, cxx = cc.replace("\\", "/"), cxx.replace("\\", "/")
            cfg += ["-DCMAKE_C_COMPILER=" + cc, "-DCMAKE_CXX_COMPILER=" + cxx]
            if host != "WINDOWS":
                # 非 Windows 主机交叉编译 Windows 目标
                cfg.append("-DCMAKE_SYSTEM_NAME=Windows")
            if rc:
                cfg.append("-DCMAKE_RC_COMPILER=" + rc.replace("\\", "/"))
            if ar:
                cfg.append("-DCMAKE_AR=" + ar.replace("\\", "/"))
            if host != "WINDOWS":
                # 交叉编译时禁止搜索宿主环境
                cfg += [
                    "-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER",
                    "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY",
                    "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY",
                ]

    elif platform == "ANDROID":
        tc_file = probe_ndk_toolchain(ctx["ndk"])
        abi = "arm64-v8a" if arch == "arm64-v8a" else "x86_64"
        cfg += [
            "-DCMAKE_TOOLCHAIN_FILE=" + tc_file,
            "-DANDROID_ABI=" + abi,
            "-DANDROID_PLATFORM=android-%d" % args.android_api,
            "-DANDROID_STL=c++_static",
        ]

    elif platform == "OPHM":
        sdk = ctx["ohos"]
        tc_file, target = probe_ohos(sdk, arch)
        if tc_file:
            cfg += [
                "-DCMAKE_TOOLCHAIN_FILE=" + tc_file,
                "-DOHOS_ARCH=" + ("arm64-v8a" if arch == "arm64-v8a" else "x86_64"),
                # 静态链接 C++ 运行时，产物自包含（与 sdl4cj 的 OHOS 配置一致）
                "-DOHOS_STL=c++_static",
            ]
        else:
            gen_tc = _gen_ohos_toolchain(sdk, target,
                                         os.path.join(OUTPUT_DIR, "toolchains"))
            cfg += ["-DCMAKE_TOOLCHAIN_FILE=" + gen_tc]

    elif platform == "EMSCRIPTEN":
        tc_file = probe_emsdk(ctx["emsdk"])
        cfg += ["-DCMAKE_TOOLCHAIN_FILE=" + tc_file]

    elif platform == "IOS":
        cfg += [
            "-DCMAKE_SYSTEM_NAME=iOS",
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
        ]
        if arch != "arm64-v8a":
            cfg += ["-DCMAKE_OSX_SYSROOT=iphonesimulator"]

    elif platform == "OSX":
        cfg += [
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
        ]

    return cfg


# ---------------------------------------------------------------------------
# CMakeLists.txt 生成（imgui 无上游可用的 CMake 构建，每个组合生成最小工程）
# ---------------------------------------------------------------------------
def generate_cmake(platform, mode, arch, libtype, build_dir, deps_dirs=None):
    """在 build_dir 下生成 CMakeLists.txt，源文件 / 头文件目录使用绝对路径。
    deps_dirs: shared 构建时存放 SDL3/bgfx 等预编译库的目录清单。"""
    os.makedirs(build_dir, exist_ok=True)
    deps_dirs = deps_dirs or []

    # 收集源文件（绝对路径）
    sources = []
    for src in IMGUI_SOURCES:
        full = os.path.join(SCRIPT_DIR, src)
        if os.path.isfile(full):
            sources.append(full)
        else:
            print("  [WARN] 源文件不存在，跳过: %s" % src)

    # 收集包含目录
    includes = []
    for inc in IMGUI_INCLUDE_DIRS:
        includes.append(os.path.normpath(os.path.join(SCRIPT_DIR, inc)))
    for name, path in DEPENDENCY_INCLUDES:
        if os.path.isdir(path):
            includes.append(path)
        else:
            print("  [WARN] 依赖头文件目录不存在: %s (%s)" % (name, path))

    # 编译定义
    defines = [
        # 禁用 ImGui 多视口（imgui_impl_bgfx 的多视口代码依赖更新版 ImGui API）
        "IMGUI_DISABLE_MULTI_VIEWPORTS",
        # 启用 cimgui SDL3 后端包装
        "CIMGUI_USE_SDL3",
        # 启用 cimgui 非变参包装（igText0 / igBulletText0 等，Cangjie FFI 使用）
        "CIMGUI_VARGS0",
        # bx 要求显式声明 debug 配置（0=release, 1=debug）
        "BX_CONFIG_DEBUG=%d" % (1 if mode == "debug" else 0),
    ]
    defines += BX_PLATFORM_DEFINE.get(platform, [])
    if platform == "WINDOWS":
        defines.append("_WIN32_WINNT=0x0A00")

    cmake_path = os.path.join(build_dir, "CMakeLists.txt")
    lines = []
    lines.append("cmake_minimum_required(VERSION 3.16)")
    lines.append("project(%s LANGUAGES CXX C)" % PKG_PREFIX)
    lines.append("")
    lines.append("set(CMAKE_CXX_STANDARD 20)")
    lines.append("set(CMAKE_CXX_STANDARD_REQUIRED ON)")
    lines.append("")
    lines.append("set(IMGUI_SOURCES")
    for s in sources:
        lines.append('    "%s"' % s.replace("\\", "/"))
    lines.append(")")
    lines.append("")
    lines.append("set(IMGUI_INCLUDES")
    for inc in includes:
        lines.append('    "%s"' % inc.replace("\\", "/"))
    lines.append(")")
    lines.append("")
    lib_kind = "STATIC" if libtype == "static" else "SHARED"
    lines.append("add_library(%s %s ${IMGUI_SOURCES})" % (LIB_BASENAME, lib_kind))
    lines.append("target_include_directories(%s PRIVATE ${IMGUI_INCLUDES})" % LIB_BASENAME)
    lines.append("set_target_properties(%s PROPERTIES" % LIB_BASENAME)
    lines.append('    OUTPUT_NAME "%s"' % LIB_BASENAME)
    lines.append('    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"')
    lines.append('    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"')
    lines.append('    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"')
    lines.append(")")
    if libtype == "shared":
        lines.append("set_target_properties(%s PROPERTIES POSITION_INDEPENDENT_CODE ON)"
                     % LIB_BASENAME)
    lines.append("")
    lines.append("target_compile_definitions(%s PRIVATE" % LIB_BASENAME)
    for d in defines:
        lines.append("    %s" % d)
    # 让 SDL3 等后端实现使用 C 链接，与 cimgui_impl.h 中的 CIMGUI_API 声明保持一致。
    # 否则 imgui_impl_sdl3.h 用 C++ 链接声明这些函数，cimgui_impl.h 再用 extern "C"
    # 重声明会冲突（转义写法与 cimgui 上游 CMakeLists.txt 完全一致：
    # \t 展开为空白、\" 为编译定义里的引号、\( \) 为括号）。
    if platform == "WINDOWS":
        lines.append('    IMGUI_IMPL_API=extern\\t\\"C\\"\\t__declspec\\(dllexport\\)')
    else:
        lines.append('    IMGUI_IMPL_API=extern\\t\\"C\\"\\t')
    lines.append(")")
    lines.append("")
    lines.append("if(MSVC)")
    lines.append("    target_compile_options(%s PRIVATE /MP /utf-8 /wd4267 /wd4244)"
                 % LIB_BASENAME)
    lines.append("    target_compile_definitions(%s PRIVATE _CRT_SECURE_NO_WARNINGS)"
                 % LIB_BASENAME)
    lines.append("else()")
    lines.append("    target_compile_options(%s PRIVATE -Wno-unused-result)"
                 % LIB_BASENAME)
    lines.append("endif()")
    lines.append("")

    if libtype == "shared":
        # shared 构建必须链接 SDL3/bgfx 预编译产物（由 --deps-lib 指定目录）。
        # 收集目录内全部库文件（.a/.lib/.so/.dylib，含 .dll.a 导入库，不含 .dll 本体）；
        # GCC/Clang 用 --start-group/--end-group 包裹以消除静态库间循环依赖顺序问题，
        # MSVC 链接器对静态库顺序不敏感，直接列出即可。
        dep_libs = []
        for d in deps_dirs:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                lf = f.lower()
                if lf.endswith((".a", ".lib", ".so", ".dylib")) and not lf.endswith(".dll"):
                    dep_libs.append(os.path.join(d, f).replace("\\", "/"))
        lines.append("# shared: SDL3/bgfx 等预编译依赖（--deps-lib 目录收集）")
        lines.append("set(IMGUI_DEPS_LIBS")
        for lf in dep_libs:
            lines.append('    "%s"' % lf)
        lines.append(")")
        sys_libs = SHARED_SYS_LIBS.get(platform, [])
        apple = platform in ("IOS", "OSX")
        lines.append("if(MSVC)")
        lines.append("    target_link_libraries(%s PRIVATE ${IMGUI_DEPS_LIBS} %s)"
                     % (LIB_BASENAME, " ".join(sys_libs)))
        lines.append("else()")
        link_items = ['"-Wl,--start-group"', "${IMGUI_DEPS_LIBS}", '"-Wl,--end-group"']
        link_items += sys_libs
        if apple:
            for fw in SHARE_APPLE_FRAMEWORKS:
                link_items += ['"-framework"', '"%s"' % fw]
        lines.append("    target_link_libraries(%s PRIVATE %s)"
                     % (LIB_BASENAME, " ".join(link_items)))
        lines.append("endif()")
        lines.append("")
    elif platform == "WINDOWS":
        # 静态库不参与链接；imm32 仅为与 cimgui 上游 CMakeLists 保持一致而记录
        lines.append("target_link_libraries(%s PRIVATE imm32)" % LIB_BASENAME)
        lines.append("")

    with open(cmake_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return cmake_path


# ---------------------------------------------------------------------------
# 命令执行
# ---------------------------------------------------------------------------
def run(cmd, cwd, env=None, log=None):
    """
    执行命令并实时回显；返回退出码。
    log: 日志文件路径（追加写入全部输出）
    """
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, errors="replace",
        )
    except FileNotFoundError:
        print("  [ERROR] 无法执行: %s" % cmd[0])
        return 1
    except OSError as e:
        print("  [ERROR] 执行 %s 失败: %s" % (cmd[0], e))
        return 1

    lines = []
    try:
        for line in proc.stdout:
            text = line.rstrip("\r\n")
            print("    " + text)
            lines.append(text + "\n")
    finally:
        proc.wait()
    rc = proc.returncode

    if log:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8", errors="replace") as f:
            f.write("$ %s\n" % " ".join(cmd))
            f.writelines(lines)
            f.write("\n")
    return rc


def cmake_path():
    p = find_tool("cmake")
    if not p:
        print("[ERROR] 未找到 cmake，请先安装并加入 PATH（https://cmake.org）")
        sys.exit(1)
    return p


# ---------------------------------------------------------------------------
# EMSCRIPTEN 环境：设置 EMSDK 相关环境变量并扩充 PATH
# ---------------------------------------------------------------------------
def build_env(platform, emsdk):
    env = os.environ.copy()
    if platform == "EMSCRIPTEN" and emsdk:
        env["EMSDK"] = emsdk
        extra = [
            os.path.join(emsdk, "upstream", "emscripten"),
            os.path.join(emsdk, "upstream", "bin"),
            os.path.join(emsdk, "node"),
        ]
        for d in extra:
            if os.path.isdir(d):
                env["PATH"] = d + os.pathsep + env["PATH"]
    return env


# ---------------------------------------------------------------------------
# 构建单个 (平台, 模式, 架构, 库类型, 工具链) 组合
# ---------------------------------------------------------------------------
def build_one(platform, mode, arch, libtype, toolchain, host, args, ctx, log_path):
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    build_dir = os.path.join(OUTPUT_DIR, "build-" + tag)

    # 清空本次组合的构建目录，避免残留
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
    os.makedirs(build_dir, exist_ok=True)

    gen = cmake_generator(platform, toolchain, host, ctx, args)
    is_multi = gen.startswith("Visual Studio") or gen == "Xcode"
    build_type = mode.capitalize()

    # 生成最小 CMake 工程
    generate_cmake(platform, mode, arch, libtype, build_dir,
                   deps_dirs=ctx.get("deps_libs"))

    env = build_env(platform, ctx.get("emsdk"))
    cmake = cmake_path()

    cfg = ["-G", gen]
    if not is_multi:
        cfg.append("-DCMAKE_BUILD_TYPE=" + build_type)
    cfg += toolchain_cfg(platform, arch, toolchain, host, ctx, args)

    print("  [%s/%s/%s] 配置 %s (toolchain=%s, generator=%s) ..."
          % (mode, arch, libtype, platform, toolchain, gen))
    config_cmd = [cmake, "-S", build_dir, "-B", build_dir] + cfg
    if run(config_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    print("  [%s/%s/%s] 编译 %s ..." % (mode, arch, libtype, platform))
    build_cmd = [cmake, "--build", build_dir, "--parallel", str(args.jobs)]
    if is_multi:
        build_cmd += ["--config", build_type]
    if run(build_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False
    return True


# ---------------------------------------------------------------------------
# 打包：收集 include 头文件 + 库文件打成规范命名 zip
# ---------------------------------------------------------------------------
def _collect_headers():
    """返回 (abs_path, zip_rel_path) 头文件清单（zip 内统一放到 include/ 下）"""
    headers = []
    seen = set()
    for root_dir, excluded in HEADER_PACK_DIRS:
        base = os.path.join(SCRIPT_DIR, root_dir)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in excluded]
            for f in files:
                if not f.lower().endswith(HEADER_EXTENSIONS):
                    continue
                full = os.path.join(root, f)
                if full in seen:
                    continue
                seen.add(full)
                rel = os.path.relpath(full, SCRIPT_DIR)
                headers.append((full, rel.replace("\\", "/")))
    return headers


def package(platform, mode, arch, libtype, toolchain, dist_dir):
    name = "%s-%s-%s-%s-%s-%s" % (PKG_PREFIX, platform.lower(), arch, mode, libtype, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    build_dir = os.path.join(OUTPUT_DIR, "build-" + tag)
    if not os.path.isdir(build_dir):
        print("  [WARN] 未找到构建目录 %s，跳过打包" % build_dir)
        return None

    # 收集库产物（.a/.lib/.so/.dll/.dylib/.bc/.wasm）
    lib_files = []
    for root, _dirs, files in os.walk(build_dir):
        # 跳过 CMake 内部目录（.obj/.o 等中间文件不在扩展名清单内，双保险）
        if "CMakeFiles" in root.split(os.sep):
            continue
        for f in files:
            if f.lower().endswith(LIB_EXTENSIONS):
                lib_files.append(os.path.join(root, f))
    if not lib_files:
        print("  [WARN] %s 下没有库文件，跳过打包" % build_dir)
        return None

    # MinGW 产物为 libimgui.a；MSVC 产物为 imgui.lib。
    # 按 bgfx4cj 约定为 .lib 另创建规范命名 lib*.a 副本（放 lib_a/），
    # 匹配 cjpm.toml 的 -l:libimgui.a 链接方式。
    lib_a_dir = os.path.join(OUTPUT_DIR, "lib_a", tag)
    if os.path.isdir(lib_a_dir):
        shutil.rmtree(lib_a_dir, ignore_errors=True)
    a_files = []
    for lf in lib_files:
        if lf.endswith(".lib"):
            a_name = "lib" + os.path.basename(lf).replace(".lib", ".a")
            a_path = os.path.join(lib_a_dir, a_name)
            os.makedirs(lib_a_dir, exist_ok=True)
            shutil.copy2(lf, a_path)
            a_files.append(a_path)

    headers = _collect_headers()
    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件：<name>/include/<相对 cxx/ 的路径>
        for full, rel in headers:
            z.write(full, os.path.join(name, "include", rel))
        # 库文件：<name>/lib/<文件名>（.dll 也放 lib/，与 sdl/openal 打包布局一致）
        for lf in lib_files:
            z.write(lf, os.path.join(name, "lib", os.path.basename(lf)))
        # MSVC .lib 的 lib*.a 副本：<name>/lib_a/<文件名>
        for af in a_files:
            z.write(af, os.path.join(name, "lib_a", os.path.basename(af)))
    return zip_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    set_batch_flag(args.batch)

    if args.clean:
        for d in (OUTPUT_DIR, DIST_DIR, LEGACY_BUILD_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    cmake = cmake_path()
    host = detect_host()
    print("=" * 60)
    print("  imgui4cj 全平台交叉编译 + 打包（cimgui + SDL3/bgfx 后端）")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  cmake:    %s" % cmake)
    print("=" * 60)

    platforms = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    modes     = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    arches    = [a.strip().lower() for a in args.arches.split(",") if a.strip()]
    libtypes  = [t.strip().lower() for t in args.libtype.split(",") if t.strip()]

    for p in platforms:
        if p not in ALL_PLATFORMS:
            print("  [WARN] 未知平台 %s，忽略（可选: %s）" % (p, ",".join(ALL_PLATFORMS)))
    platforms = [p for p in platforms if p in ALL_PLATFORMS]
    for t in libtypes:
        if t not in ALL_LIBTYPES:
            print("  [WARN] 未知库类型 %s，忽略（可选: %s）" % (t, ",".join(ALL_LIBTYPES)))
    libtypes = [t for t in libtypes if t in ALL_LIBTYPES]

    # 依赖头文件目录检查（仅告警）
    for name, path in DEPENDENCY_INCLUDES:
        if not os.path.isdir(path):
            print("  [WARN] 依赖目录不存在: %s -> %s" % (name, path))

    # 预解析各平台所需 SDK（命令行 > 环境变量 > 交互询问）
    vs_gen = detect_vs_generator()
    ctx = {"ndk": None, "ohos": None, "emsdk": None, "mingw": args.mingw,
           "deps_libs": None,
           "vs_generator": vs_gen,
           "vs_generators": probe_vs_generators(cmake)}
    if vs_gen:
        print("  检测到 Visual Studio: %s" % vs_gen)
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")
    if "OPHM" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OPHM 平台因缺少 OHOS SDK 路径被跳过")
    if "EMSCRIPTEN" in platforms:
        ctx["emsdk"] = resolve_emsdk(args)
        if not ctx["emsdk"]:
            print("  [WARN] EMSCRIPTEN 平台因缺少 emsdk 路径被跳过")
    if "shared" in libtypes:
        # shared 必须链接 SDL3/bgfx 预编译产物；无法提供目录时 shared 组合逐个跳过
        ctx["deps_libs"] = resolve_deps_libs(args)
        if ctx["deps_libs"]:
            print("  shared 依赖库目录: %s" % ", ".join(ctx["deps_libs"]))
        else:
            print("  [WARN] shared 构建未提供 --deps-lib 依赖库目录，shared 组合将被跳过")

    dist_dir = os.path.abspath(args.dist)
    results = []   # (name, status, note)
    any_failed = False

    for platform in platforms:
        ok, reason = can_build(platform, host, ctx)
        if not ok:
            print("\n[SKIP] %s：%s" % (platform, reason))
            results.append((platform, "skip", reason))
            continue
        print("\n===== 平台 %s（%s 主机）=====" % (platform, host))

        # 该平台支持的架构
        plat_arches = [a for a in arches if a in PLATFORM_ARCHES.get(platform, [])]
        if not plat_arches:
            print("  [WARN] 平台 %s 不支持任何选定架构 %s，跳过" % (platform, arches))
            results.append((platform, "skip", "架构不匹配"))
            continue

        for mode in modes:
            for arch in plat_arches:
                for libtype in libtypes:
                    combo_name = "%s-%s-%s-%s-%s" % (
                        PKG_PREFIX, platform.lower(), arch, mode, libtype)
                    if libtype == "shared" and not ctx.get("deps_libs"):
                        print("\n[SKIP] %s：shared 构建需 --deps-lib 提供 "
                              "SDL3/bgfx 预编译库目录" % combo_name)
                        results.append((combo_name, "skip",
                                        "shared 缺少 --deps-lib 依赖库目录"))
                        continue
                    toolchains = toolchains_for(platform, host, libtype)
                    done = False
                    for tc in toolchains:
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo_name, tc))
                        log_path = os.path.join(LOG_DIR, combo_name + "-" + tc + ".log")
                        # 工具链缺失（如 mingw 无 arm64 交叉编译器、msvc 无 ARM64 组件）时
                        # 会抛 RuntimeError，捕获后视为该工具链失败，继续回退/下一组合
                        try:
                            build_ok = build_one(platform, mode, arch, libtype, tc,
                                                 host, args, ctx, log_path)
                        except RuntimeError as e:
                            print("  [WARN] %s / %s 工具链不可用: %s" % (combo_name, tc, e))
                            build_ok = False
                        if build_ok:
                            if args.skip_package:
                                print("  [OK] %s 编译成功（--skip-package 不打包）" % combo_name)
                                results.append((combo_name + "-" + tc, "ok", "编译成功"))
                            else:
                                zpath = package(platform, mode, arch, libtype, tc, dist_dir)
                                if zpath:
                                    print("  [OK] %s 编译并打包: %s" % (combo_name, zpath))
                                    results.append((combo_name + "-" + tc, "ok", "zip: " + zpath))
                                else:
                                    print("  [OK] %s 编译成功，但无产物可打包" % combo_name)
                                    results.append((combo_name + "-" + tc, "ok", "编译成功，未打包"))
                            done = True
                            break
                        print("  [FAIL] %s / %s 编译失败，日志: %s" % (combo_name, tc, log_path))
                        if tc != toolchains[-1]:
                            print("  -> 尝试回退工具链 %s ..."
                                  % toolchains[toolchains.index(tc) + 1])
                    if not done:
                        any_failed = True
                        results.append((combo_name, "fail", "编译失败（所有候选工具链）"))
                        if args.stop_on_error:
                            print("\n[STOP] --stop-on-error 触发，停止后续编译")
                            _summary(results)
                            sys.exit(1)

    _summary(results)
    sys.exit(1 if any_failed else 0)


def _summary(results):
    print("\n" + "=" * 60)
    print("  汇总报告")
    print("=" * 60)
    if not results:
        print("  （没有执行任何编译）")
        return
    for name, status, note in results:
        if status == "ok":
            mark = "[OK]  "
        elif status == "skip":
            mark = "[SKIP]"
        else:
            mark = "[FAIL]"
        print("  %s %-52s %s" % (mark, name, note))
    print("=" * 60)


if __name__ == "__main__":
    main()
