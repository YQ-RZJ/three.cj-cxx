#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bgfx4cj (bgfx.cmake) 全平台自动交叉编译 + 打包脚本（CMake 版）
=============================================================
bgfx/bx/bimg/geometryc/shaderc 及三个 C API 包装库已合并为 bgfx.cmake
单 CMake 工程（本仓库根下 bgfx.cmake/），本脚本替代旧 xmake 版
bgfx_build.py，参数约定与旧版保持兼容：

  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a
  - 平台:   LINUX WINDOWS ANDROID OHOS BSD EMSCRIPTEN IOS OSX
  - 库类型: static / shared（对应 BGFX_LIBRARY_TYPE）
  - 库清单: --libs bx,bimg,bimg_capi,bgfx,geometryc_capi,shaderc_capi
    （CMake 单工程一次性编译全部目标，--libs 仅做名称校验以兼容 CI 分发，
    不做单库裁剪）

  OHOS = OpenHarmony / HarmonyOS：使用 OHOS NDK 的 llvm/bin/clang +
  --target=*-linux-ohos --sysroot=<sdk>/sysroot 交叉编译（CMake 选项
  BX_PLATFORM_OHOS=ON；hilog 输出、EGL 库名回退等 OHOS 定制由该宏启用，
  渲染走 GLES30 路径）。

行为约定：
  1. 启动时传入编译平台清单（默认全部 8 个平台），脚本对
     debug/release x x86_64/arm64-v8a x static/shared 自动排列组合，
     为每个可编译的平台依次配置+编译，并在每个组合编译成功后立即打包为
     规范命名的 zip（bgfx4cj-<platform>-<arch>-<mode>-<libtype>-<toolchain>.zip）；
  2. WINDOWS 平台（Windows 主机上）自动尝试 msvc / mingw，优先 msvc，
     失败后自动回退 mingw；
  3. 其余平台优先使用 clang 工具链；
  4. 需要 NDK / emsdk 等 SDK 的交叉编译平台（ANDROID、OHOS、EMSCRIPTEN、
     以及非 Windows 主机上的 WINDOWS 交叉编译），会要求开发者提供 SDK 路径
     （命令行参数 > 环境变量 > 交互询问）后再推进编译，无法提供则告警跳过；
  5. IOS / OSX 必须在其自身系统（macOS）上编译：脚本检测到自身运行在
     macOS 上才放行，否则告警跳过。

用法示例：
  python bgfx_build.py                             # 全部平台排列组合
  python bgfx_build.py --platforms ANDROID,WINDOWS # 只编指定平台
  python bgfx_build.py --platforms ANDROID --ndk D:/ndk
  python bgfx_build.py --platforms OHOS --ohos-sdk D:/ohos-sdk
  python bgfx_build.py --modes release --arches x86_64
  python bgfx_build.py --libtype static            # 只编静态库
  python bgfx_build.py --batch                     # 非交互（不询问，缺 SDK 即跳过）
"""

import argparse
import os
import platform as _platform
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

# CI-PATCH: --libs 选择性构建（默认全量；未知库名直接报错）。
# bgfx.cmake 为单 CMake 工程，一次配置编译全部目标；此处仅校验库名以
# 兼容 ci_build.py 的全局 --libs 分发，不做单库裁剪。
_ALLOWED_LIBS = ['bx', 'bimg', 'bimg_capi', 'bgfx', 'geometryc_capi', 'shaderc_capi']


def parse_libs_arg(libs_str, allowed, group):
    if not libs_str:
        return list(allowed)
    wanted = [s.strip().lower() for s in libs_str.split(",") if s.strip()]
    unknown = [w for w in wanted if w not in allowed]
    if unknown:
        sys.exit("[%s] --libs 未知库名: %s（可选：%s）"
                 % (group, ",".join(unknown), ",".join(allowed)))
    return [w for w in allowed if w in set(wanted)]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# CI-PATCH: 脚本位于 <root>/.github/scripts/ 下，仓库根即 cxx 根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "bgfx.cmake")          # CMake 工程根（含 CMakeLists.txt）
BUILD_ROOT = os.path.join(ROOT, "build", "bgfx")    # CMake 构建目录根（clean.py 清 ROOT/build）
DIST_DIR = os.path.join(ROOT, "dist")               # zip / 日志输出目录
LOG_DIR = os.path.join(DIST_DIR, "logs")

# 头文件集合（打包进 zip 的 include/）
HEADER_DIRS = [
    os.path.join(SRC_DIR, "bgfx", "include", "bgfx"),
    os.path.join(SRC_DIR, "bimg", "include", "bimg"),
    os.path.join(SRC_DIR, "bx", "include", "bx"),
    os.path.join(SRC_DIR, "bx", "include", "compat"),
    os.path.join(SRC_DIR, "bx", "include", "tinystl"),
]

# C API 包装库头文件（打包进 include/）
CAPI_HEADERS = [
    "bimg_capi/bimg_capi.h",
    "geometryc_capi/geometryc_capi.h",
    "shaderc_capi/shaderc_capi.h",
]

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OHOS", "BSD", "EMSCRIPTEN", "IOS", "OSX"]
ALL_MODES = ["debug", "release"]
ALL_ARCHES = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES = ["static", "shared"]

# OpenHarmony NDK 默认路径（交互询问时作为回车默认值）
NDK_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

LIB_EXTENSIONS = (".a", ".lib", ".so", ".dll", ".dylib", ".so.py3", ".bc", ".wasm")


# ---------------------------------------------------------------------------
# 主机平台检测
# ---------------------------------------------------------------------------
def detect_host():
    s = _platform.system().lower()
    if "windows" in s:
        return "WINDOWS"
    if "darwin" in s:
        return "OSX"
    if "linux" in s:
        return "LINUX"
    if any(k in s for k in ("freebsd", "netbsd", "openbsd", "dragonfly")):
        return "BSD"
    return "OTHER"


def machine_arch():
    m = _platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    return m


def is_windows():
    return _platform.system().lower().startswith("win")


def exe_suffix():
    return ".exe" if is_windows() else ""


# ---------------------------------------------------------------------------
# 交互（--batch 时禁用）
# ---------------------------------------------------------------------------
_BATCH_FLAG = False


def ask(prompt, default=None):
    if _BATCH_FLAG:
        return default
    try:
        s = input("%s%s: " % (prompt, ("（回车默认: %s）" % default) if default else ""))
    except EOFError:
        return default
    s = s.strip()
    return s if s else default


def parse_args():
    ap = argparse.ArgumentParser(
        prog="bgfx_build.py",
        description="bgfx4cj (bgfx.cmake) 全平台自动交叉编译 + 打包脚本（CMake 版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔，可选: " + ",".join(ALL_PLATFORMS)
                         + "（默认全部，OHOS=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单，逗号分隔: debug,release（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单，逗号分隔: x86_64,arm64-v8a（默认全部）")
    ap.add_argument("--libtype", default=",".join(ALL_LIBTYPES),
                    help="库类型清单，逗号分隔: static,shared（默认全部）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（或环境变量 OHOS_SDK）")
    ap.add_argument("--emsdk", default=None,
                    help="Emscripten SDK 路径（或环境变量 EMSDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 根目录（Windows 交叉/回退工具链）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 输出目录（默认 dist/）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4, help="并行编译任务数")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单：bx,bimg,bimg_capi,bgfx,geometryc_capi,shaderc_capi"
                         "（仅校验名称以兼容 CI 分发；CMake 单工程不做单库裁剪）")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式（缺 SDK 即跳过）")
    ap.add_argument("--skip-package", action="store_true", help="只编译不打包")
    ap.add_argument("--stop-on-error", action="store_true", help="首个失败即停止")
    ap.add_argument("--clean", action="store_true", help="启动前清理构建目录")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# SDK 路径解析：命令行参数 > 环境变量 > 交互询问
# ---------------------------------------------------------------------------
def resolve_ndk(args):
    v = (args.ndk
         or os.environ.get("ANDROID_NDK_HOME")
         or os.environ.get("ANDROID_NDK_ROOT")
         or os.environ.get("OHOS_SDK"))
    if not v:
        v = ask("请输入 Android NDK 路径", default=NDK_DEFAULT)
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] NDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_ohos_sdk(args):
    v = (args.ohos_sdk
         or os.environ.get("OHOS_SDK")
         or os.environ.get("OHOS_NDK_HOME"))
    if not v:
        v = ask("请输入 HarmonyOS / OpenHarmony NDK 路径", default=NDK_DEFAULT)
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] OHOS SDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_emsdk(args):
    v = args.emsdk or os.environ.get("EMSDK")
    if not v:
        v = ask("请输入 Emscripten SDK (emsdk) 路径")
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] Emscripten SDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


# ---------------------------------------------------------------------------
# 工具链探测
# ---------------------------------------------------------------------------
def probe_ohos(sdk, arch):
    """探测 OpenHarmony NDK：<sdk>/llvm/bin/clang[.exe] + <sdk>/sysroot，target 为 *-linux-ohos"""
    exe = exe_suffix()
    # CI-PATCH: 统一正斜杠——DevEco 本机安装路径含空格（"C:\Program
    # Files\HuaWei DevEco..."），反斜杠路径写入 CMake cache 时 "C:\Program"
    # 的 \P 被当转义解析报 Syntax error（本机实测）；正斜杠 Windows 原生
    # 兼容且对 CI 无空格路径无影响。
    sdk = sdk.replace("\\", "/")
    bin_dir = os.path.join(sdk, "llvm", "bin")
    cc = os.path.join(bin_dir, "clang" + exe)
    cxx = os.path.join(bin_dir, "clang++" + exe)
    sysroot = os.path.join(sdk, "sysroot")
    # CI-PATCH2: os.path.join 在 Windows 上用反斜杠拼接（sdk 已是正斜杠
    # 也会得到混合分隔符 "native\llvm\bin"），必须对最终结果再归一一次
    cc = cc.replace("\\", "/")
    cxx = cxx.replace("\\", "/")
    sysroot = sysroot.replace("\\", "/")
    if not (os.path.isfile(cc) and os.path.isfile(cxx) and os.path.isdir(sysroot)):
        raise RuntimeError(
            "OHOS SDK 结构不完整，需要 <sdk>/llvm/bin/clang 与 <sdk>/sysroot: %s" % sdk)
    target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    return cc, cxx, cc, sysroot, target


def probe_emsdk(emsdk):
    exe = ".bat" if is_windows() else ""
    for base in (os.path.join(emsdk, "upstream", "emscripten"), emsdk):
        emcc = os.path.join(base, "emcc" + exe)
        emxx = os.path.join(base, "em++" + exe)
        if os.path.exists(emcc) and os.path.exists(emxx):
            return emcc, emxx
    raise RuntimeError("无法在 emsdk 中找到 emcc/em++: %s" % emsdk)


def _fwd(p):
    """CI-PATCH: 路径统一正斜杠——含空格的 Windows 路径（C:\\Program
    Files\\...）以反斜杠形态写入 CMake cache 时 "\\P" 被当转义解析报
    Syntax error（本机实测 mingw/ohos 均踩过）；正斜杠 Windows 原生兼容。"""
    return p.replace("\\", "/") if p else p


def find_tool(name):
    """在 PATH 中查找工具，返回完整路径或 None"""
    exe = name if name.endswith(exe_suffix()) else name + exe_suffix()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, exe)
        if os.path.isfile(cand):
            return cand
    return None


def probe_mingw(arch, mingw_dir):
    """探测 mingw-w64 交叉/本机工具链前缀，返回 (cc, cxx, ld) 或 None"""
    triples = {"x86_64": "x86_64-w64-mingw32-", "arm64-v8a": "aarch64-w64-mingw32-"}
    pre = triples.get(arch, triples["x86_64"])
    gcc_name = pre + "gcc" + exe_suffix()
    gxx_name = pre + "g++" + exe_suffix()
    # CI-PATCH: llvm-mingw 只带 triple-clang 包装（无 -gcc 别名），补 clang 探测
    if mingw_dir and os.path.isdir(mingw_dir):
        bin_dir = os.path.join(mingw_dir, "bin")
        cc = os.path.join(bin_dir, gcc_name)
        if not os.path.exists(cc):
            cc = os.path.join(bin_dir, pre + "clang" + exe_suffix())
        if os.path.exists(cc):
            cxx = os.path.join(bin_dir, gxx_name)
            if not os.path.exists(cxx):
                cxx = os.path.join(bin_dir, pre + "clang++" + exe_suffix())
            return _fwd(cc), _fwd(cxx), _fwd(cc)
    gcc = find_tool(gcc_name)
    gxx = find_tool(gxx_name)
    if gcc and gxx:
        return _fwd(gcc), _fwd(gxx), _fwd(gcc)
    return None


# ---------------------------------------------------------------------------
# 可编译性判定（host 系统约束 + SDK 是否就绪）
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    if platform == "WINDOWS":
        if host == "WINDOWS":
            return True, ""
        if probe_mingw("x86_64", ctx.get("mingw")) or probe_mingw("arm64-v8a", ctx.get("mingw")):
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
    if platform == "OHOS":
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
        if not find_tool("xcrun"):
            return False, "macOS 上未找到 xcrun（需要安装 Xcode）"
        return True, ""
    if platform == "OSX":
        if host != "OSX":
            return False, "OSX 必须在 macOS 上编译（当前主机: %s）" % host
        if not find_tool("xcrun") and not find_tool("clang"):
            return False, "macOS 上未找到 clang / xcrun（需要 Xcode Command Line Tools）"
        return True, ""
    return False, "未知平台: %s" % platform


def toolchains_for(platform, host, libtype=None):
    """每个平台候选工具链（按优先级）：WINDOWS 主机上 mingw 优先，失败回退 msvc"""
    _ = libtype
    if platform == "WINDOWS" and host == "WINDOWS":
        # CI-PATCH: 统一 MinGW 优先——ci_deps 依赖库的工具链必须一致
        # （MSVC .lib 与 MinGW 的 C++ name mangling 不兼容：MS 是
        # ?xxx@bgfx@@、MinGW 是 _ZN4bgfx…，混用链接必出 undefined
        # reference，windows x86_64 imgui job 实测）。
        return ["mingw", "msvc"]
    return ["clang"]


# ---------------------------------------------------------------------------
# CMake 配置生成
# 返回 (cache 变量 dict, env 覆盖 dict)
# ---------------------------------------------------------------------------
def cmake_config(platform, mode, arch, libtype, toolchain, host, ctx):
    cache = {}
    env_over = {}

    # 通用
    cache["CMAKE_BUILD_TYPE"] = "Debug" if mode == "debug" else "Release"
    cache["BGFX_LIBRARY_TYPE"] = "STATIC" if libtype == "static" else "SHARED"
    # CI-PATCH2: shaderc_capi 的 GLSL 编译后端（SHADERC_CONFIG_HAS_GLSLANG）
    # 依赖 glslang/spirv-cross CMake targets，它们只在 BGFX_BUILD_TOOLS_
    # SHADER=ON 时定义；全 OFF 时 capi 探测降级 GLSLANG=0 桩，运行期所有
    # GLSL/ESSL 编译报 "GLSL compiler is not compiled in."（OHOS 300_es
    # 实测，log.log 2026-09-17）。
    # 注意 BGFX_BUILD_TOOLS_SHADER 是 cmake_dependent_option，依赖条件为
    # BGFX_BUILD_TOOLS——TOOLS=OFF 时子开关可能被强制回落 OFF（CMP0126
    # 行为随 CMake 版本变化），不可靠。故 TOOLS=ON + 显式关掉 bin2c/
    # geometry/texture 三个子工具，只编 shaderc（glslang+spirv-cross）。
    cache["BGFX_BUILD_TOOLS"] = "ON"
    cache["BGFX_BUILD_TOOLS_SHADER"] = "ON"
    cache["BGFX_BUILD_TOOLS_BIN2C"] = "OFF"
    cache["BGFX_BUILD_TOOLS_GEOMETRY"] = "OFF"
    cache["BGFX_BUILD_TOOLS_TEXTURE"] = "OFF"
    cache["BGFX_BUILD_EXAMPLES"] = "OFF"
    cache["BGFX_BUILD_TESTS"] = "OFF"
    cache["BGFX_INSTALL"] = "OFF"
    cache["BX_AMALGAMATED"] = "OFF"
    cache["BGFX_AMALGAMATED"] = "OFF"

    # ---- OHOS（OpenHarmony / HarmonyOS）：OHOS NDK clang 交叉 ----
    if platform == "OHOS":
        sdk = ctx.get("ohos")
        if not sdk:
            raise RuntimeError("OHOS 需要 OHOS SDK 路径")
        cc, cxx, _ld, sysroot, target = probe_ohos(sdk, arch)
        cache["BX_PLATFORM_OHOS"] = "ON"
        cache["OHOS_SDK"] = sdk.replace("\\", "/")
        cache["CMAKE_SYSTEM_NAME"] = "Linux"
        cache["CMAKE_SYSTEM_PROCESSOR"] = "aarch64" if arch == "arm64-v8a" else "x86_64"
        # CI-PATCH3: sysroot 走 CMAKE_SYSROOT 专用变量——DevEco 本机路径
        # 含空格，--sysroot 塞在 *_FLAGS 里会在 make 调 clang 时按空格
        # 分词（本机实测 clang: error: no such file or directory:
        # 'Files/HuaWei/DevEco'）；CMAKE_SYSROOT 由 CMake 引用传递不分词。
        # --target 无空格，保留在 flags。
        cache["CMAKE_SYSROOT"] = sysroot
        cross = "--target=%s" % target
        # __linux__ 由 ohos target 自动定义；显式补 BX_PLATFORM_LINUX=1 以防万一
        cache["CMAKE_C_FLAGS"] = "-DBX_PLATFORM_LINUX=1 " + cross
        cache["CMAKE_CXX_FLAGS"] = "-DBX_PLATFORM_LINUX=1 " + cross
        cache["CMAKE_EXE_LINKER_FLAGS"] = cross
        cache["CMAKE_SHARED_LINKER_FLAGS"] = cross
        cache["CMAKE_C_COMPILER"] = cc
        cache["CMAKE_CXX_COMPILER"] = cxx
        return cache, env_over

    # ---- ANDROID：NDK toolchain 文件交叉 ----
    if platform == "ANDROID":
        ndk = ctx.get("ndk")
        if not ndk:
            raise RuntimeError("ANDROID 需要 NDK 路径")
        tc = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
        if not os.path.isfile(tc):
            raise RuntimeError("NDK 缺少 toolchain 文件: %s" % tc)
        cache["CMAKE_TOOLCHAIN_FILE"] = tc
        cache["ANDROID_ABI"] = "arm64-v8a" if arch == "arm64-v8a" else "x86_64"
        cache["ANDROID_PLATFORM"] = "android-24"
        mk = find_tool("ninja")
        if mk:
            cache["CMAKE_MAKE_PROGRAM"] = mk
        return cache, env_over

    # ---- EMSCRIPTEN：emcc 交叉 ----
    if platform == "EMSCRIPTEN":
        emsdk = ctx.get("emsdk")
        if not emsdk:
            raise RuntimeError("EMSCRIPTEN 需要 emsdk 路径")
        cc, cxx = probe_emsdk(emsdk)
        cache["CMAKE_SYSTEM_NAME"] = "Emscripten"
        cache["CMAKE_C_COMPILER"] = cc
        cache["CMAKE_CXX_COMPILER"] = cxx
        env_over["EMSDK"] = emsdk
        for d in (os.path.join(emsdk, "upstream", "emscripten"),
                  os.path.join(emsdk, "upstream", "bin"), os.path.join(emsdk, "node")):
            if os.path.isdir(d):
                env_over["PATH"] = d + os.pathsep + "{PATH}"
        return cache, env_over

    # ---- IOS：macOS + Xcode 交叉 ----
    if platform == "IOS":
        cache["CMAKE_SYSTEM_NAME"] = "iOS"
        if arch == "arm64-v8a":
            cache["CMAKE_OSX_SYSROOT"] = "iphoneos"
            cache["CMAKE_OSX_ARCHITECTURES"] = "arm64"
        else:
            cache["CMAKE_OSX_SYSROOT"] = "iphonesimulator"
            cache["CMAKE_OSX_ARCHITECTURES"] = "x86_64"
        return cache, env_over

    # ---- OSX：macOS 原生 clang ----
    if platform == "OSX":
        cache["CMAKE_OSX_ARCHITECTURES"] = "arm64" if arch == "arm64-v8a" else "x86_64"
        return cache, env_over

    # ---- WINDOWS：msvc 原生 / mingw（本机或交叉）----
    if platform == "WINDOWS":
        if toolchain == "mingw":
            tc = probe_mingw(arch, ctx.get("mingw"))
            if tc is None:
                raise RuntimeError("缺少 %s 的 mingw-w64 工具链" % arch)
            cc, cxx, _ld = tc
            cache["CMAKE_SYSTEM_NAME"] = "Windows"
            # CI-PATCH: 显式设置 CMAKE_SYSTEM_NAME 后 CMake 不再自动探测
            # 处理器架构，CMAKE_SYSTEM_PROCESSOR 为空——bx.cmake 的
            # -msse4.2 注入条件匹配失败，bx 编译报 _mm_round_ps
            # "target specific option mismatch"（本机实测）。显式补齐。
            cache["CMAKE_SYSTEM_PROCESSOR"] = "x86_64" if arch == "x86_64" else "aarch64"
            cache["CMAKE_C_COMPILER"] = cc
            cache["CMAKE_CXX_COMPILER"] = cxx
            cache["CMAKE_MAKE_PROGRAM"] = _fwd(find_tool("mingw32-make") or find_tool("make"))
            mk = find_tool("ninja")
            if mk:
                cache["CMAKE_MAKE_PROGRAM"] = _fwd(mk)
            # CI-PATCH: MinGW shared 构建必须 --export-all-symbols——
            # bgfx.cmake 的 WINDOWS_EXPORT_ALL_SYMBOLS 只对 MSVC 生效，
            # MinGW/ld 默认仅导出 dllexport 符号（本机实测：libbgfx.dll
            # 只导出 57 个 C API 符号、bgfx:: C++ 符号 0 个；消费者链接
            # bgfx::getCaps() 直接 undefined——windows x86 imgui job 同症）。
            # 加此旗标后导出 5842 个符号，消费者链接复刻通过。
            if libtype == "shared":
                cache["CMAKE_SHARED_LINKER_FLAGS"] = "-Wl,--export-all-symbols"
        # msvc: 直接使用本机 Visual Studio 生成器，无需额外 cache 变量
        return cache, env_over

    # ---- LINUX / BSD：本机原生；arm64 时注入 aarch64-linux-gnu 交叉工具链 ----
    # CI-PATCH: bgfx.cmake 的 BGFX_WITH_WAYLAND 在 Linux 上默认 ON
    # （cmake_dependent_option），链接 -lwayland-egl——交叉时 arm64 版
    # wayland 库未安装必然失败；产物走 X11/OpenGL 后端，直接关闭。
    cache["BGFX_WITH_WAYLAND"] = "OFF"
    if platform == "LINUX" and arch == "arm64-v8a":
        cc = "/usr/bin/aarch64-linux-gnu-gcc"
        cxx = "/usr/bin/aarch64-linux-gnu-g++"
        if os.path.isfile(cc) and os.path.isfile(cxx):
            cache["CMAKE_SYSTEM_NAME"] = "Linux"
            cache["CMAKE_SYSTEM_PROCESSOR"] = "aarch64"
            cache["CMAKE_C_COMPILER"] = cc
            cache["CMAKE_CXX_COMPILER"] = cxx
            # 预置 X11/OpenGL 探测结果：CI 用 :arm64 多架构包（装在
            # /usr/lib/aarch64-linux-gnu），不预置的话 find_package 会
            # 撞上宿主 x86_64 的库，导致链接架构错误。变量已设时
            # FindX11/FindOpenGL 跳过搜索直接采用。
            alib = "/usr/lib/aarch64-linux-gnu"
            if os.path.isfile(os.path.join(alib, "libX11.so")):
                cache["X11_X11_INCLUDE_PATH"] = "/usr/include"
                cache["X11_X11_LIB"] = os.path.join(alib, "libX11.so")
            if os.path.isfile(os.path.join(alib, "libGL.so")):
                cache["OPENGL_INCLUDE_DIR"] = "/usr/include"
                cache["OPENGL_gl_LIBRARY"] = os.path.join(alib, "libGL.so")
    return cache, env_over


# ---------------------------------------------------------------------------
# 命令执行
# ---------------------------------------------------------------------------
def run(cmd, cwd, env=None, log=None):
    """执行命令并实时回显；返回退出码。log: 日志文件路径（追加写入全部输出）"""
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


def build_env(env_over):
    env = os.environ.copy()
    for k, v in env_over.items():
        if k == "PATH":
            env["PATH"] = v.replace("{PATH}", env["PATH"])
        else:
            env[k] = v
    return env


def cmake_generator(toolchain):
    """选择生成器：msvc 显式探测 CMake 支持的最高 VS 生成器，其余用 Ninja
    （缺则回退 Unix Makefiles）"""
    if toolchain != "msvc":
        if find_tool("ninja"):
            return "Ninja"
        return "Unix Makefiles"
    # CI-PATCH: 不再让 CMake 自选——本机实测 CMake 3.28 不认识
    # "Visual Studio 18 2026"，自选落到 NMake Makefiles，与 -A 平台
    # 参数不兼容报 "does not support platform specification"。
    # 从 cmake --help 里按新到旧探测可用 VS 生成器，选命中的最高版。
    try:
        help_out = subprocess.run([cmake_path(), "--help"],
                                  capture_output=True, text=True).stdout
    except OSError:
        help_out = ""
    for g in ("Visual Studio 18 2026", "Visual Studio 17 2022",
              "Visual Studio 16 2019"):
        if g in help_out:
            return g
    return None  # 无 VS 生成器可用（调用方跳过 -A，报错信息由 cmake 给出）


# ---------------------------------------------------------------------------
# 构建单个 (平台, 模式, 架构, 工具链, 库类型) 组合
# ---------------------------------------------------------------------------
def build_one(platform, mode, arch, libtype, toolchain, host, args, ctx, log_path):
    build_dir = os.path.join(BUILD_ROOT, "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain))
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
    os.makedirs(build_dir, exist_ok=True)

    cache, env_over = cmake_config(platform, mode, arch, libtype, toolchain, host, ctx)
    env = build_env(env_over)

    cmake = cmake_path()
    gen = cmake_generator(toolchain)

    cmd = [cmake, "-S", SRC_DIR, "-B", build_dir]
    if gen:
        cmd += ["-G", gen]
    # msvc：仅 VS 生成器支持 -A 主机/目标平台（NMake 等命令行生成器
    # 传 -A 报 "does not support platform specification"）
    if toolchain == "msvc" and platform == "WINDOWS" and gen and gen.startswith("Visual Studio"):
        cmd += ["-A", "x64" if arch == "x86_64" else "ARM64"]
    for k, v in cache.items():
        cmd += ["-D%s=%s" % (k, v)]
    if gen == "Ninja" or gen == "Unix Makefiles":
        cmd += ["-DCMAKE_BUILD_TYPE=" + cache.get("CMAKE_BUILD_TYPE", "Release")]

    print("  [%s/%s] 配置 CMake (toolchain=%s, libtype=%s) ..." % (mode, arch, toolchain, libtype))
    if run(cmd, ROOT, env, log_path) != 0:
        return False

    print("  [%s/%s] 编译 ..." % (mode, arch))
    if run([cmake, "--build", build_dir, "--config",
            "Debug" if mode == "debug" else "Release",
            "--parallel", str(args.jobs)], ROOT, env, log_path) != 0:
        return False

    # 收集产物到 build/bgfx/normalize/<arch>/，供打包使用
    collect_libs(build_dir, arch)
    return True


def collect_libs(build_dir, arch):
    """从构建目录收集库文件到 build/bgfx/normalize/<arch>/，MinGW .lib 生成 lib*.a 副本"""
    out_dir = os.path.join(BUILD_ROOT, "normalize", arch)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for root, _dirs, files in os.walk(build_dir):
        for f in files:
            if f.endswith(LIB_EXTENSIONS):
                # CI-PATCH4: glslang/spirv-opt/spirv-cross 已由 capi 的
                # CI-PATCH3 POST_BUILD 合并进 libshaderc_capi.a（对齐老
                # 库 xmake 产物形态：消费侧只需单库），不再独立分发——
                # 从产物清单剔除，避免旧包混出多余 .a
                if f in ("libglslang.a", "libspirv-opt.a", "libspirv-cross.a"):
                    continue
                src = os.path.join(root, f)
                dst = os.path.join(out_dir, f)
                shutil.copy2(src, dst)
                count += 1
                # MinGW 产物为 .lib，另生成规范命名 lib*.a 副本（匹配 cjpm -l:lib*.a）
                if f.endswith(".lib") and not f.endswith(".dll.lib") and "dll" not in f:
                    a_name = "lib" + f.replace(".lib", ".a")
                    shutil.copy2(src, os.path.join(out_dir, a_name))
                    count += 1
    print("  已收集 %d 个库文件到 %s" % (count, out_dir))


# ---------------------------------------------------------------------------
# 打包：头文件 + C API 头 + 静态库/动态库打成规范命名 zip
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, toolchain, dist_dir):
    name = "bgfx4cj-%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")

    lib_dir = os.path.join(BUILD_ROOT, "normalize", arch)
    if not os.path.isdir(lib_dir):
        print("  [WARN] 未找到库产物目录 %s，跳过打包" % lib_dir)
        return None

    lib_files = []
    for root, _dirs, files in os.walk(lib_dir):
        for f in files:
            if f.endswith(LIB_EXTENSIONS):
                lib_files.append(os.path.join(root, f))
    if not lib_files:
        print("  [WARN] %s 下没有库文件，跳过打包" % lib_dir)
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件集合
        for hd in HEADER_DIRS:
            if not os.path.isdir(hd):
                continue
            base = os.path.dirname(hd)  # include/<bx|bgfx|bimg|compat|tinystl>
            for root, _dirs, files in os.walk(hd):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, base)
                    z.write(full, os.path.join(name, "include", rel))
        # C API 头文件
        for rel in CAPI_HEADERS:
            src = os.path.join(SRC_DIR, rel)
            if os.path.exists(src):
                z.write(src, os.path.join(name, "include", os.path.basename(rel)))
        # 库文件
        for lf in lib_files:
            z.write(lf, os.path.join(name, "lib", os.path.basename(lf)))
    return zip_path


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
        print("  %s %-48s %s" % (mark, name, note))
    print("=" * 60)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    parse_libs_arg(args.libs, _ALLOWED_LIBS, "bgfx")  # 提前校验 --libs
    _BATCH_FLAG = args.batch

    if args.clean:
        for d in (BUILD_ROOT, DIST_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    cmake_path()
    host = detect_host()
    print("=" * 60)
    print("  bgfx4cj (bgfx.cmake) 全平台交叉编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  源码:     %s" % SRC_DIR)
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  cmake:    %s" % cmake_path())
    print("=" * 60)

    platforms = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    modes = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    arches = [a.strip().lower() for a in args.arches.split(",") if a.strip()]
    libtypes = [t.strip().lower() for t in args.libtype.split(",") if t.strip()]

    invalid = [p for p in platforms if p not in ALL_PLATFORMS]
    for p in invalid:
        print("  [WARN] 未知平台 %s，忽略（可选: %s）" % (p, ",".join(ALL_PLATFORMS)))
    platforms = [p for p in platforms if p in ALL_PLATFORMS]
    for t in libtypes:
        if t not in ALL_LIBTYPES:
            print("  [WARN] 未知库类型 %s，忽略（可选: %s）" % (t, ",".join(ALL_LIBTYPES)))
    libtypes = [t for t in libtypes if t in ALL_LIBTYPES]

    # 预解析各平台所需 SDK（命令行 > 环境变量 > 交互询问）
    ctx = {"ndk": None, "ohos": None, "emsdk": None, "mingw": args.mingw}
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")
    if "OHOS" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OHOS 平台因缺少 OHOS SDK 路径被跳过")
    if "EMSCRIPTEN" in platforms:
        ctx["emsdk"] = resolve_emsdk(args)
        if not ctx["emsdk"]:
            print("  [WARN] EMSCRIPTEN 平台因缺少 emsdk 路径被跳过")

    dist_dir = os.path.abspath(args.dist)
    results = []
    any_failed = False

    for platform in platforms:
        ok, reason = can_build(platform, host, ctx)
        if not ok:
            print("\n[SKIP] %s：%s" % (platform, reason))
            results.append((platform, "skip", reason))
            continue
        print("\n===== 平台 %s（%s 主机）=====" % (platform, host))

        for mode in modes:
            for arch in arches:
                for libtype in libtypes:
                    combo_name = "bgfx4cj-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)
                    toolchains = toolchains_for(platform, host, libtype)
                    done = False
                    for tc in toolchains:
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo_name, tc))
                        log_path = os.path.join(LOG_DIR, combo_name + "-" + tc + ".log")
                        if build_one(platform, mode, arch, libtype, tc, host, args, ctx, log_path):
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
                        else:
                            print("  [FAIL] %s / %s 编译失败，日志: %s" % (combo_name, tc, log_path))
                            if tc != toolchains[-1]:
                                print("  -> 回退工具链 %s ..." % toolchains[toolchains.index(tc) + 1])
                    if not done:
                        any_failed = True
                        results.append((combo_name, "fail", "编译失败（所有候选工具链）"))
                        if args.stop_on_error:
                            print("\n[STOP] --stop-on-error 触发，停止后续编译")
                            _summary(results)
                            sys.exit(1)

    _summary(results)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
