#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JoltPhysics4cj 全平台自动交叉编译 + 打包脚本（JoltPhysics 版）
================================================================
参考 openalsoft4cj/cxx/build.py 的交互约定与代码结构。

  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a
  - 平台:   LINUX WINDOWS ANDROID OHOS BSD EMSCRIPTEN IOS OSX
  - 工具链: msvc / mingw / ndk / ohos / emsdk / xcode / native
  - 库类型: static / shared（对应 CMake -DJPH_BUILD_SHARED_LIBS）

说明：
  OHOS = OpenHarmony / HarmonyOS：优先使用 DevEco NDK 自带的
  ohos.toolchain.cmake；若无则退回 clang --target=*-linux-ohos
  --sysroot=<sdk>/sysroot 的交叉编译方式。

行为约定（与 bgfx4cj / openalsoft4cj 保持一致）：
  1. 启动时传入编译平台清单（默认全部 8 个平台），脚本对
     debug/release x x86_64/arm64-v8a x static/shared 自动排列组合，
     为每个可编译的平台依次编译，并在每个组合编译成功后立即打包
     为规范命名的 zip；
  2. WINDOWS 平台（Windows 主机上）自动尝试 msvc(Visual Studio)/
     mingw，优先 msvc，失败后自动回退 mingw；
  3. LINUX / BSD 平台使用本机原生编译器（clang 优先）；
  4. 需要 NDK / emsdk / OHOS SDK 的交叉编译平台（ANDROID、
     EMSCRIPTEN、OHOS、以及非 Windows 主机上的 WINDOWS 交叉编译），
     会要求开发者提供 SDK 路径（命令行参数 > 环境变量 > 交互询问）
     后再推进编译，无法提供则告警跳过；
  5. IOS / OSX 必须在其自身系统（macOS）上编译：脚本检测到自身
     运行在 macOS 上才放行，否则告警跳过。

用法示例：
  python build.py                                  # 全部平台排列组合
  python build.py --platforms ANDROID,WINDOWS      # 只编指定平台
  python build.py --platforms ANDROID --ndk D:/ndk
  python build.py --modes release --arches x86_64
  python build.py --libtype static                 # 只编静态库
  python build.py --batch                          # 非交互（不询问，缺 SDK 即跳过）
"""

import argparse
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import zipfile

# CI-PATCH: --libs 选择性构建（默认全量；未知库名直接报错；输出保持声明顺序）
_ALLOWED_LIBS = ['jolt']


def parse_libs_arg(libs_str, allowed, group):
    if not libs_str:
        return list(allowed)
    wanted = [s.strip().lower() for s in libs_str.split(",") if s.strip()]
    unknown = [w for w in wanted if w not in allowed]
    if unknown:
        sys.exit("[%s] --libs 未知库名: %s（可选：%s）"
                 % (group, ",".join(unknown), ",".join(allowed)))
    return [w for w in allowed if w in set(wanted)]



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
JOLT_DIR      = os.path.join(SCRIPT_DIR, "JoltPhysics")      # JoltPhysics 源码根目录
SRC_DIR       = os.path.join(JOLT_DIR, "Build")              # JoltPhysics CMake 源码目录（含 CMakeLists.txt）
JOLTC_DIR     = os.path.join(SCRIPT_DIR, "joltc")            # joltc（JoltPhysics C API 包装层）工程目录
OUTPUT_DIR    = os.path.join(SCRIPT_DIR, "output")           # cmake 构建/安装产物根目录
DIST_DIR      = os.path.join(SCRIPT_DIR, "dist")             # zip / 日志输出目录
LOG_DIR       = os.path.join(DIST_DIR, "logs")
PROJECT_ROOT  = os.path.dirname(SCRIPT_DIR)                  # 项目根目录（含 src/ test/ libs/）
LIBS_DIR      = os.path.join(PROJECT_ROOT, "libs")           # 仓颉侧链接用的静态/动态库输出目录

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OHOS", "BSD", "EMSCRIPTEN", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# build.bat 里 arm64-v8a 使用的 Android / OpenHarmony NDK 默认路径（交互询问时作为回车默认值）
NDK_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"
OHOS_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

LIB_EXTENSIONS = (".a", ".lib", ".so", ".dll", ".dylib", ".bc", ".wasm")
HEADER_EXTENSIONS = (".h", ".hpp")


# ---------------------------------------------------------------------------
# 主机平台检测（沿用 bgfx 平台命名：WINDOWS / LINUX / OSX / BSD ...）
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
        description="JoltPhysics4cj 全平台自动交叉编译 + 打包脚本（JoltPhysics, CMake 构建）",
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
                    help="库类型清单，逗号分隔: static,shared（默认全部，对应 CMake -DJPH_BUILD_SHARED_LIBS）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / ANDROID_NDK_ROOT）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OHOS 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--emsdk", default=None,
                    help="Emscripten SDK 路径（或环境变量 EMSDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 工具链目录（Windows 主机上 mingw 回退 / 非 Windows 主机交叉编译 WINDOWS 时用）")
    ap.add_argument("--android-api", type=int, default=24,
                    help="Android 最低 API 级别（默认 24）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认 = CPU 核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--libs-dir", default=LIBS_DIR,
                    help="编译成功后把库文件复制到的目录（默认项目根 libs/，仓颉侧链接用）")
    ap.add_argument("--no-libs-copy", action="store_true",
                    help="编译成功后不复制库文件到 libs 目录")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 output/ 与 dist/")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式：不询问 SDK 路径，缺 SDK 的平台直接跳过并告警")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止（默认继续其余组合）")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
    ap.add_argument("--generator", default=None,
                    help="强制指定 CMake 生成器（默认按平台自动选择，如 Ninja / Visual Studio 17 2022 / Xcode）")
    # ---- JoltPhysics 特有选项 ----
    ap.add_argument("--double-precision", action="store_true",
                    help="启用 DOUBLE_PRECISION（位置用 double，支持更大世界）")
    ap.add_argument("--cross-platform-deterministic", action="store_true",
                    help="启用 CROSS_PLATFORM_DETERMINISTIC（跨平台确定性）")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序）：jolt（默认=全量编译）")
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


def args_batch():
    """供 ask() 查询是否处于批处理模式（避免全局传参）"""
    return _BATCH_FLAG


_BATCH_FLAG = False


def set_batch_flag(flag):
    global _BATCH_FLAG
    _BATCH_FLAG = flag


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
    """解析 HarmonyOS / OpenHarmony NDK 路径（OHOS 平台需要）"""
    v = (args.ohos_sdk
         or os.environ.get("OHOS_SDK")
         or os.environ.get("OHOS_NDK_HOME"))
    if not v:
        v = ask("请输入 HarmonyOS / OpenHarmony NDK 路径", default=OHOS_DEFAULT)
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


# ---------------------------------------------------------------------------
# 工具链探测
# ---------------------------------------------------------------------------
def probe_ndk_toolchain(ndk, host):
    """
    探测 Android NDK 的 CMake 工具链文件，返回其绝对路径。
    使用 NDK 自带的 <ndk>/build/cmake/android.toolchain.cmake。
    """
    tc = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
    if os.path.isfile(tc):
        return tc
    # 兜底：扫描 toolchains/llvm/prebuilt/<host>/ 布局中可能存在的 toolchain 文件
    for root, _dirs, files in os.walk(os.path.join(ndk, "build")):
        if "android.toolchain.cmake" in files:
            return os.path.join(root, "android.toolchain.cmake")
    raise RuntimeError("无法在 NDK 中找到 android.toolchain.cmake: %s" % ndk)


def probe_ohos(sdk, arch):
    """
    探测 OpenHarmony NDK 工具链。返回 (toolchain_file 或 None, target)。
    优先使用 DevEco 提供的 ohos.toolchain.cmake；否则返回 None，
    由调用方生成临时 toolchain 文件（clang --target=*-linux-ohos）。
    """
    tc = os.path.join(sdk, "build", "cmake", "ohos.toolchain.cmake")
    if os.path.isfile(tc):
        return tc, None
    # 部分 NDK 布局：<sdk>/native/build/cmake/ohos.toolchain.cmake
    tc2 = os.path.join(sdk, "native", "build", "cmake", "ohos.toolchain.cmake")
    if os.path.isfile(tc2):
        return tc2, None
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
    tc_path = os.path.join(toolchain_dir, "ohos-%s.cmake" % target)
    content = (
        'set(CMAKE_SYSTEM_NAME Linux)\n'
        'set(CMAKE_SYSTEM_PROCESSOR arm64)\n'
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
    ) % (cc.replace("\\", "/"), cxx.replace("\\", "/"), sysroot,
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


def _probe_linux_cross(prefix):
    """探测 Linux 交叉工具链（aarch64-linux-gnu-gcc/g++ 等）。
    返回 (cc, cxx) 或 None。仅在非本机架构的 LINUX 组合下调用。"""
    exe = exe_suffix()
    cc = find_tool(prefix + "-gcc" + exe) or find_tool(prefix + "-clang" + exe)
    if not cc:
        return None
    if cc.endswith("-clang" + exe):
        cxx = cc[:-len("clang" + exe)] + "clang++" + exe
    else:
        cxx = cc[:-len("gcc" + exe)] + "g++" + exe
    if not os.path.isfile(cxx):
        cxx = cc
    return cc, cxx


def probe_mingw(arch, mingw_dir):
    """
    探测 mingw-w64 工具链。返回 (cc, cxx, rc, ar) 或 None。
    arch: x86_64 -> 本机 gcc / x86_64-w64-mingw32-；arm64-v8a -> aarch64-w64-mingw32-
    """
    exe = exe_suffix()
    if arch == "arm64-v8a":
        triples = ["aarch64-w64-mingw32-"]
        # 本机 Windows 上默认没有 aarch64 交叉编译器，仅走 --mingw / PATH 探测
    else:
        triples = ["x86_64-w64-mingw32-"]
    for pre in triples:
        # 1) --mingw 指定目录优先（CI-PATCH：--mingw 指向 llvm-mingw
        #    msvcrt 工具链时必须整体一致——若 x86_64 落回 PATH 本机
        #    mingw（UCRT/libstdc++），产物会混出两套 C++ 标准库
        #    （std::__1 vs __cxx11），消费侧 -lc++/-lstdc++ 单挂哪套
        #    都重复定义或 undefined（win x86_64 job 实测 imgui/jolt/
        #    openal/requireCJLib 混链））
        if mingw_dir and os.path.isdir(mingw_dir):
            bin_dir = os.path.join(mingw_dir, "bin")
            cand = os.path.join(bin_dir, pre + "gcc" + exe)
            if os.path.exists(cand):
                return (cand,
                        os.path.join(bin_dir, pre + "g++" + exe),
                        os.path.join(bin_dir, pre + "windres" + exe),
                        os.path.join(bin_dir, pre + "ar" + exe))
        # 2) PATH 中查找（含本机裸 gcc——仅当无 --mingw 或其目录无该前缀）
        gcc = find_tool(pre + "gcc" + exe)
        gxx = find_tool(pre + "g++" + exe)
        if gcc and gxx:
            rc = find_tool(pre + "windres" + exe)
            ar = find_tool(pre + "ar" + exe)
            return gcc, gxx, rc, ar
    # 3) Windows 主机兜底：本机裸 gcc/g++（无三元组前缀）
    if is_windows():
        local = find_tool("gcc" + exe)
        if local and find_tool("g++" + exe):
            return (local,
                    find_tool("g++" + exe),
                    find_tool("windres" + exe),
                    find_tool("ar" + exe) or os.path.join(os.path.dirname(local), "ar" + exe))
    return None


def probe_vs_generators(cmake_exe):
    """
    从 `cmake --help` 解析可用的 Visual Studio 生成器，按版本号降序返回。
    例如 ["Visual Studio 18 2026", "Visual Studio 17 2022", ...]。
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
    # 按版本号降序（18 2026 -> 17 2022 -> 16 2019 -> ...）
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
            # Windows 主机：msvc(Visual Studio) 或本机 mingw 任一可用即可
            if ctx.get("vs_generators"):
                return True, ""
            tc = probe_mingw("x86_64", ctx.get("mingw"))
            if tc:
                return True, ""
            return False, "Windows 主机上未检测到 Visual Studio 或 mingw-w64 工具链"
        tc = probe_mingw("x86_64", ctx.get("mingw")) or probe_mingw("arm64-v8a", ctx.get("mingw"))
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
# CMake 生成器与配置生成
# ---------------------------------------------------------------------------
def toolchains_for(platform, host, libtype="static"):
    """每个平台候选工具链（按优先级）：WINDOWS 主机上 static 优先 mingw，其余 msvc 优先"""
    if platform == "WINDOWS" and host == "WINDOWS":
        # CI-PATCH: 统一 MinGW 优先（不分 libtype）——ci_deps 依赖库的
        # 工具链必须一致，MSVC .lib 与 MinGW 的 C++ name mangling 不兼容
        # （?xxx@bgfx@@ vs _ZN4bgfx…），混用链接必出 undefined reference。
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
    return "Unix Makefiles" if not is_windows() else "MinGW Makefiles"


def toolchain_cfg(platform, arch, toolchain, host, ctx, args):
    """生成平台/工具链专用 CMake 参数"""
    cfg = []
    if platform == "WINDOWS":
        if toolchain == "msvc":
            # Visual Studio 多配置生成器：-A 指定架构
            arch_map = {"x86_64": "x64", "arm64-v8a": "ARM64"}
            cfg.append("-A" + arch_map.get(arch, "x64"))
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
        tc_file = probe_ndk_toolchain(ctx["ndk"], host)
        abi = arch  # arm64-v8a / x86_64 直接作为 ANDROID_ABI
        cfg += [
            "-DCMAKE_TOOLCHAIN_FILE=" + tc_file,
            "-DANDROID_ABI=" + abi,
            "-DANDROID_PLATFORM=android-%d" % args.android_api,
            "-DANDROID_STL=c++_static",
            "-DANDROID_LD=lld",
        ]

    elif platform == "OHOS":
        sdk = ctx["ohos"]
        tc_file, target = probe_ohos(sdk, arch)
        if tc_file:
            cfg += [
                "-DCMAKE_TOOLCHAIN_FILE=" + tc_file,
                "-DOHOS_ARCH=" + ("arm64-v8a" if arch == "arm64-v8a" else "x86_64"),
                "-DOHOS_PLATFORM=API12",
            ]
        else:
            gen_tc = _gen_ohos_toolchain(sdk, target,
                                         os.path.join(OUTPUT_DIR, "toolchains"))
            cfg += ["-DCMAKE_TOOLCHAIN_FILE=" + gen_tc]

    elif platform == "EMSCRIPTEN":
        tc_file = probe_emsdk(ctx["emsdk"])
        cfg += ["-DCMAKE_TOOLCHAIN_FILE=" + tc_file]

    elif platform == "LINUX":
        # CI-PATCH: arm64 组合在 x86_64 Linux runner 上必须交叉编译——
        # 原先无 LINUX 分支，CMake 落到宿主原生 gcc 产出 x86_64 库
        # （归包审计实测 libjoltc.so 为 x86_64）。用 aarch64-linux-gnu
        # 三元组工具链；找不到时报错而非悄悄产出异架构库。
        if arch == "arm64-v8a":
            tc = _probe_linux_cross("aarch64-linux-gnu")
            if tc is None:
                raise RuntimeError("缺少 aarch64-linux-gnu 交叉工具链"
                                   "（apt install gcc-aarch64-linux-gnu）")
            cc, cxx = tc
            cfg += [
                "-DCMAKE_C_COMPILER=" + cc,
                "-DCMAKE_CXX_COMPILER=" + cxx,
                "-DCMAKE_SYSTEM_NAME=Linux",
                "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
                "-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER",
                "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY",
                "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY",
            ]
        # x86_64 本机编译无需任何参数

    elif platform == "IOS":
        cfg += [
            "-DCMAKE_SYSTEM_NAME=iOS",
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
        ]
        # CI-PATCH: 模拟器架构必须显式指定 iphonesimulator（对齐 imgui），
        # 否则 CMake 按默认 iphoneos 设备 SDK 配置 x86_64
        if arch != "arm64-v8a":
            cfg += ["-DCMAKE_OSX_SYSROOT=iphonesimulator"]
        # CI-PATCH2: 本脚本 iOS 用 Xcode 生成器（cmake_generator），
        # 默认要求代码签名，CI 无 development team 必然失败
        # （"Signing for X requires a development team"，imgui/openal
        # 同因已修）——关闭签名。OSX 分支不受影响。
        cfg += [
            "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED=NO",
            "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED=NO",
        ]

    elif platform == "OSX":
        cfg += [
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
        ]
    return cfg


def cmake_config(platform, mode, arch, libtype, toolchain, host, ctx, args):
    """
    生成 cmake 配置参数列表（不含 -S/-B，由调用方追加）。
    返回 (configure_args, is_multi_config)。
    is_multi_config: Visual Studio / Xcode 生成器为 True，构建时需 --config
    """
    gen = cmake_generator(platform, toolchain, host, ctx, args)
    is_multi = gen.startswith("Visual Studio") or gen == "Xcode"
    build_type = mode.capitalize()  # Debug / Release

    cfg = ["-G", gen]
    if not is_multi:
        cfg.append("-DCMAKE_BUILD_TYPE=" + build_type)

    # ---- joltc 工程选项：只编库，不编示例/测试 ----
    cfg += [
        # JoltPhysics 源码根目录（joltc/CMakeLists.txt 用它定位本地 Jolt，
        # 找不到时才会回退到 GitHub 下载 v5.6.0）
        # 注意：必须用正斜杠，否则 FetchContent 的 subbuild 会把反斜杠当转义字符
        "-DJOLT_PHYSICS_ROOT=" + JOLT_DIR.replace("\\", "/"),
        # 库类型：static -> JPH_BUILD_SHARED=OFF；shared -> ON
        # 注意 joltc 默认在独立构建时构建 SHARED，必须显式指定
        "-DJPH_BUILD_SHARED=" + ("ON" if libtype == "shared" else "OFF"),
        # 只编库：关闭示例与测试（默认在独立构建时开启）
        "-DJPH_SAMPLES=OFF",
        "-DJPH_TESTS=OFF",
        # 开启安装目标（产出 libjoltc + joltc.h 到 stage）
        "-DJPH_INSTALL=ON",
        # 关闭着色器/Compute 相关源码（DX12/VK/MTL/CPU 计算），纯物理核心。
        # joltc 通过 FetchContent 引入 Jolt，这些选项在 Jolt 的 Build/CMakeLists.txt
        # 中定义，Windows 上默认开启 DX12（需要 dxcapi.h，纯净环境没有）
        "-DJPH_USE_DX12=OFF",
        "-DJPH_USE_VK=OFF",
        "-DJPH_USE_MTL=OFF",
        "-DJPH_USE_CPU_COMPUTE=OFF",
        # 关闭 LTO（默认 ON）：libJolt.a 的 LTO 字节码只有 C++ 链接器
        # （lto-wrapper）能正确消费，仓颉的 lld 链接后会运行时异常
        "-DINTERPROCEDURAL_OPTIMIZATION=OFF",
        # 关闭所有警告即错误，避免跨平台编译器警告导致失败
        "-DENABLE_ALL_WARNINGS=OFF",
    ]

    # ---- 可选特性（命令行开关）----
    if args.double_precision:
        cfg.append("-DDOUBLE_PRECISION=ON")
    if args.cross_platform_deterministic:
        cfg.append("-DCROSS_PLATFORM_DETERMINISTIC=ON")

    # ---- 平台 / 工具链专用参数 ----
    cfg += toolchain_cfg(platform, arch, toolchain, host, ctx, args)
    return cfg, is_multi


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
    stage_dir = os.path.join(OUTPUT_DIR, "stage-" + tag)

    # 清空本次组合的构建/安装目录，避免残留
    for d in (build_dir, stage_dir):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    os.makedirs(build_dir, exist_ok=True)

    cfg, is_multi = cmake_config(platform, mode, arch, libtype, toolchain, host, ctx, args)
    env = build_env(platform, ctx.get("emsdk"))
    cmake = cmake_path()

    # 构建入口为 joltc 工程（内部通过 FetchContent 引用本地 JoltPhysics 源码）
    config_cmd = [cmake, "-S", JOLTC_DIR, "-B", build_dir] + cfg
    print("  [%s/%s/%s] 配置 %s (toolchain=%s) ..." % (mode, arch, libtype, platform, toolchain))
    if run(config_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    print("  [%s/%s/%s] 编译 %s ..." % (mode, arch, libtype, platform))
    build_cmd = [cmake, "--build", build_dir, "--parallel", str(args.jobs)]
    if is_multi:
        build_cmd += ["--config", mode.capitalize()]
    if run(build_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    print("  [%s/%s/%s] 安装到 %s ..." % (mode, arch, libtype, stage_dir))
    install_cmd = [cmake, "--install", build_dir, "--prefix", stage_dir]
    if is_multi:
        install_cmd += ["--config", mode.capitalize()]
    if run(install_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    return True


# ---------------------------------------------------------------------------
# 产物目录清理
# ---------------------------------------------------------------------------
def clean_output():
    """清空 cmake 构建产物目录 output/"""
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        print("  已清空编译产物目录: %s" % OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 复制库文件到 libs/ 目录（仓颉侧 cjpm 链接用）
# ---------------------------------------------------------------------------
def stage_dir_of(platform, mode, arch, libtype, toolchain):
    """返回指定组合的 stage 安装目录路径。"""
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    return os.path.join(OUTPUT_DIR, "stage-" + tag)


def copy_libs(stage_dir, libs_dir):
    """把 stage 安装目录下的库文件复制到 libs_dir（保持原文件名）。"""
    if not os.path.isdir(stage_dir):
        print("  [WARN] 未找到安装产物目录 %s，跳过复制 libs" % stage_dir)
        return
    os.makedirs(libs_dir, exist_ok=True)
    copied = []
    for root, _dirs, files in os.walk(stage_dir):
        for f in files:
            low = f.lower()
            if low.endswith(LIB_EXTENSIONS):
                src = os.path.join(root, f)
                dst = os.path.join(libs_dir, f)
                shutil.copy2(src, dst)
                copied.append(dst)
    if copied:
        print("  [OK] 已复制 %d 个库文件到 %s:" % (len(copied), libs_dir))
        for c in copied:
            print("       - %s" % c)
    else:
        print("  [WARN] %s 下没有库文件，未复制" % stage_dir)


# ---------------------------------------------------------------------------
# 打包：收集 include 头文件 + 库文件打成规范命名 zip
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, toolchain, dist_dir, args):
    name = "joltphysics4cj-%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    stage_dir = os.path.join(OUTPUT_DIR, "stage-" + tag)
    if not os.path.isdir(stage_dir):
        print("  [WARN] 未找到安装产物目录 %s，跳过打包" % stage_dir)
        return None

    headers, libs = [], []
    for root, _dirs, files in os.walk(stage_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, stage_dir)
            low = f.lower()
            if low.endswith(HEADER_EXTENSIONS):
                headers.append((full, rel))
            elif low.endswith(LIB_EXTENSIONS):
                # CI-PATCH: shared 组合排除静态中间产物——它们是链入
                # joltc 动态库的内嵌内核（消费者只需动态库），打出来会让
                # 归包 shared/ 混入"没有对应动态库的静态库"：
                #   windows/linux: libJolt.a / libJoltd.a（Jolt 内核，
                #   由 joltc C 包装层链入）
                #   ios/osx (CI 实测): libjoltc.a / libjoltcd.a——Xcode
                #   生成器下 joltc 目标同时产出静态+动态两形态（BUILD_
                #   SHARED_LIBS 不抑制归档），静态版是被链入 dylib 的
                #   中间产物，混进 shared 包误导消费者
                # 注意只排静态形态（.a/.lib）——前缀 libjoltc. 同样命中
                # libjoltc.dylib，按后缀限定才不会把动态库本体清掉
                #（自检实测：纯前缀过滤会让 shared 包空掉）
                # CI-PATCH2 初版曾为 joltc 上游 IOS FORCE 禁共享设 IOS
                # 例外保留静态库；上游已放开（joltc/CMakeLists.txt 仅
                # 保留 EMSCRIPTEN 禁共享），IOS 恢复统一排除——libJolt.a
                # 再次成为被链入 dylib 的中间产物，不应对外分发。
                if (libtype == "shared" and low.endswith((".a", ".lib"))
                        and low.startswith(("libjolt.", "libjoltd.",
                                            "libjoltc.", "libjoltcd."))):
                    continue
                libs.append((full, rel))
    if not libs:
        print("  [WARN] %s 下没有库文件，跳过打包" % stage_dir)
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件：<name>/include/<相对路径>
        for full, rel in headers:
            z.write(full, os.path.join(name, "include", rel))
        # 库文件：<name>/lib/<相对路径>
        for full, rel in libs:
            z.write(full, os.path.join(name, "lib", rel))
    return zip_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    libs_wanted = parse_libs_arg(args.libs, _ALLOWED_LIBS, "jolt")
    if "jolt" not in libs_wanted:
        print("[jolt] --libs 未包含 jolt，整组跳过")
        return
    set_batch_flag(args.batch)

    if args.clean:
        for d in (OUTPUT_DIR, DIST_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    cmake = cmake_path()
    host = detect_host()
    print("=" * 60)
    print("  JoltPhysics4cj 全平台交叉编译 + 打包（JoltPhysics）")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  源码目录: %s" % SRC_DIR)
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

    # 预解析各平台所需 SDK（命令行 > 环境变量 > 交互询问）
    vs_gen = detect_vs_generator()
    ctx = {"ndk": None, "ohos": None, "emsdk": None, "mingw": args.mingw,
           "vs_generator": vs_gen,
           "vs_generators": probe_vs_generators(cmake)}
    if vs_gen:
        print("  检测到 Visual Studio: %s" % vs_gen)
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
    results = []   # (name, ok, note)
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
                    combo_name = "joltphysics4cj-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)
                    # 每个组合编译前清空产物目录，避免与上一组合/上次运行的产物混在一起
                    clean_output()
                    toolchains = toolchains_for(platform, host, libtype)
                    done = False
                    for tc in toolchains:
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo_name, tc))
                        log_path = os.path.join(LOG_DIR, combo_name + "-" + tc + ".log")
                        # 工具链缺失（如 mingw 无 arm64 交叉编译器、msvc 无 ARM64 组件）时
                        # 会抛 RuntimeError，捕获后视为该工具链失败，继续回退/下一组合
                        try:
                            build_ok = build_one(platform, mode, arch, libtype, tc, host, args, ctx, log_path)
                        except RuntimeError as e:
                            print("  [WARN] %s / %s 工具链不可用: %s" % (combo_name, tc, e))
                            build_ok = False
                        if build_ok:
                            # 编译成功后把库文件复制到 libs/（仓颉侧链接用），默认开启
                            if not args.no_libs_copy:
                                copy_libs(stage_dir_of(platform, mode, arch, libtype, tc), args.libs_dir)
                            if args.skip_package:
                                print("  [OK] %s 编译成功（--skip-package 不打包）" % combo_name)
                                results.append((combo_name + "-" + tc, "ok", "编译成功"))
                            else:
                                zpath = package(platform, mode, arch, libtype, tc, dist_dir, args)
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
                                print("  -> 尝试回退工具链 %s ..." % toolchains[toolchains.index(tc) + 1])
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
