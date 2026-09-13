#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bgfx4cj 全平台自动交叉编译 + 打包脚本
======================================
与 build.bat 同目录使用，参数约定参考 build.bat：
  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a
  - 平台:   LINUX WINDOWS ANDROID OPHM BSD EMSCRIPTEN IOS OSX
  - 工具链: clang / mingw / msvs(msvc)
  - 库类型: static / shared（对应 xmake 的 set_kind）

说明：
  OPHM = OpenHarmony / HarmonyOS，复刻 build.bat 的原始 HarmonyOS 行为：
  使用 OHOS NDK 的 llvm/bin/clang + --target=*-linux-ohos --sysroot=<sdk>/sysroot
  交叉编译（bx_platform 走 OPHM，同时定义 BX_PLATFORM_LINUX=1，
  OpenHarmony 兼容 Linux API，renderer 走 compat/linux + GLES30 路径）。

行为约定：
  1. 启动时传入编译平台清单（默认全部 8 个平台），脚本对
     debug/release x x86_64/arm64-v8a x static/shared 自动排列组合，
     为每个可编译的平台依次编译，并在每个组合编译成功后立即打包为规范命名的 zip；
  2. WINDOWS 平台（Windows 主机上）自动尝试 msvs(msvc)/mingw，优先 msvs，
     失败后自动回退 mingw；
  3. 其余平台优先使用 clang 工具链；
  4. 需要 NDK / emsdk 等 SDK 的交叉编译平台（ANDROID、EMSCRIPTEN、以及
     非 Windows 主机上的 WINDOWS 交叉编译），会要求开发者提供 SDK 路径
     （命令行参数 > 环境变量 > 交互询问）后再推进编译，无法提供则告警跳过；
  5. IOS / OSX 必须在其自身系统（macOS）上编译：脚本检测到自身运行在
     macOS 上才放行，否则告警跳过。

用法示例：
  python build.py                                  # 全部平台排列组合
  python build.py --platforms ANDROID,WINDOWS      # 只编指定平台
  python build.py --platforms ANDROID --ndk D:/ndk
  python build.py --modes release --arches x86_64
  python build.py --libtype static                 # 只编静态库
  python build.py --libtype shared                 # 只编动态库
  python build.py --batch                          # 非交互（不询问，缺 SDK 即跳过）
"""

import argparse
import os
import platform as _platform
import shutil
import subprocess
import sys
import zipfile

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # CI 扁平化布局：脚本在 .github/scripts/ 下，cxx 根即项目根
# CI-PATCH: 原 GROUP_DIR 已扁平化删除，以下路径均相对 cxx 根解析
GROUP_DIR = os.path.dirname(os.path.abspath(__file__))  # 仅供 --dist 默认值等 CI 侧用途
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")        # xmake 产物根目录
LIB_OUT    = os.path.join(OUTPUT_DIR, "bgfx", "Lib")   # 静态库汇聚目录
HEADERS_DIR = os.path.join(SCRIPT_DIR, "Headers", "bgfx", "Header")  # 打包用头文件集合
DIST_DIR    = os.path.join(SCRIPT_DIR, "dist")         # zip / 日志输出目录
LOG_DIR     = os.path.join(DIST_DIR, "logs")

# 编译顺序：bx -> bimg -> bimg_capi -> bgfx -> geometryc_capi -> shaderc_capi
SUBPROJECTS = ["bx", "bimg", "bimg_capi", "bgfx", "geometryc_capi", "shaderc_capi"]

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OPHM", "BSD", "EMSCRIPTEN", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# 每个 C API 包装库对应的头文件（打包时并入 include/）
CAPI_HEADERS = {
    "bimg_capi":       os.path.join("bimg_capi",       "bimg_capi.h"),
    "geometryc_capi":  os.path.join("geometryc_capi",  "geometryc_capi.h"),
    "shaderc_capi":    os.path.join("shaderc_capi",    "shaderc_capi.h"),
}

# build.bat 里 arm64-v8a 使用的 OpenHarmony NDK 默认路径（交互询问时作为回车默认值）
NDK_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

LIB_EXTENSIONS = (".a", ".lib", ".so", ".dll", ".dylib", ".bc", ".wasm")


# ---------------------------------------------------------------------------
# 主机平台检测（bx 平台命名：WINDOWS / LINUX / OSX / BSD ...）
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
        description="bgfx4cj 全平台自动交叉编译 + 打包脚本（参考 build.bat）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔，可选: " + ",".join(ALL_PLATFORMS)
                         + "（默认全部，OPHM=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单，逗号分隔: debug,release（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单，逗号分隔: x86_64,arm64-v8a（默认全部）")
    ap.add_argument("--libtype", default=",".join(ALL_LIBTYPES),
                    help="库类型清单，逗号分隔: static,shared（默认全部，对应 xmake 的 set_kind）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / OHOS_SDK）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OPHM 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--emsdk", default=None,
                    help="Emscripten SDK 路径（或环境变量 EMSDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 前缀工具链目录（非 Windows 主机交叉编译 WINDOWS 时用）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认 = CPU 核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 output/ 与 dist/")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式：不询问 SDK 路径，缺 SDK 的平台直接跳过并告警")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止（默认继续其余组合）")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
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
    """解析 NDK 路径（ANDROID 平台、arm64-v8a 等需要）"""
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


def resolve_ohos_sdk(args):
    """解析 HarmonyOS / OpenHarmony NDK 路径（OPHM 平台需要，build.bat 原始行为）"""
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


def probe_ndk(ndk, arch, host):
    """
    探测 NDK 结构，返回 (cc, cxx, ld, sysroot, target)。
    兼容两种布局：
      - OpenHarmony NDK: <ndk>/llvm/bin/clang[.exe]  + <ndk>/sysroot
      - Android NDK:     <ndk>/toolchains/llvm/prebuilt/<host>/bin/clang[.exe]
    """
    exe = exe_suffix()
    ohos_bin = os.path.join(ndk, "llvm", "bin", "clang" + exe)
    if os.path.isfile(ohos_bin) and os.path.isdir(os.path.join(ndk, "sysroot")):
        bin_dir = os.path.join(ndk, "llvm", "bin")
        sysroot = os.path.join(ndk, "sysroot")
        target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    else:
        # Android NDK 的 prebuilt 主机目录
        hostdirs = []
        if host == "WINDOWS":
            hostdirs = ["windows-x86_64"]
        elif host == "OSX":
            hostdirs = ["darwin-arm64" if machine_arch() == "arm64" else "darwin-x86_64"]
        else:
            hostdirs = ["linux-x86_64"]
        base = None
        for hd in hostdirs:
            cand = os.path.join(ndk, "toolchains", "llvm", "prebuilt", hd)
            if os.path.isdir(cand):
                base = cand
                break
        if base is None:
            # 再兜底扫一遍 prebuilt 下实际存在的目录
            prebuilt = os.path.join(ndk, "toolchains", "llvm", "prebuilt")
            if os.path.isdir(prebuilt):
                cands = sorted(os.listdir(prebuilt))
                for c in cands:
                    if os.path.isfile(os.path.join(prebuilt, c, "bin", "clang" + exe)):
                        base = os.path.join(prebuilt, c)
                        break
        if base is None:
            raise RuntimeError("无法在 NDK 中找到 llvm 工具链: %s" % ndk)
        bin_dir = os.path.join(base, "bin")
        sysroot = os.path.join(base, "sysroot")
        target = "aarch64-linux-android24" if arch == "arm64-v8a" else "x86_64-linux-android24"
    cc  = os.path.join(bin_dir, "clang" + exe)
    cxx = os.path.join(bin_dir, "clang++" + exe)
    return cc, cxx, cc, sysroot, target


def probe_ohos(sdk, arch):
    """
    探测 OpenHarmony NDK（build.bat 原始 HarmonyOS 行为）：
      <sdk>/llvm/bin/clang[.exe] + <sdk>/sysroot，target 为 *-linux-ohos
    """
    exe = exe_suffix()
    bin_dir = os.path.join(sdk, "llvm", "bin")
    cc  = os.path.join(bin_dir, "clang" + exe)
    cxx = os.path.join(bin_dir, "clang++" + exe)
    sysroot = os.path.join(sdk, "sysroot")
    if not (os.path.isfile(cc) and os.path.isfile(cxx) and os.path.isdir(sysroot)):
        raise RuntimeError(
            "OHOS SDK 结构不完整，需要 <sdk>/llvm/bin/clang 与 <sdk>/sysroot: %s" % sdk)
    target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    return cc, cxx, cc, sysroot, target


def probe_emsdk(emsdk):
    """返回 (emcc, em++) 路径；优先 upstream 布局，退回 emsdk 根目录"""
    exe = ".bat" if is_windows() else ""
    for base in (os.path.join(emsdk, "upstream", "emscripten"), emsdk):
        emcc = os.path.join(base, "emcc" + exe)
        emxx = os.path.join(base, "em++" + exe)
        if os.path.exists(emcc) and os.path.exists(emxx):
            return emcc, emxx
    raise RuntimeError("无法在 emsdk 中找到 emcc/em++: %s" % emsdk)


def probe_mingw(arch, mingw_dir):
    """
    探测 mingw-w64 交叉工具链前缀。返回 (cc, cxx, ld) 或 None。
    arch: x86_64 -> x86_64-w64-mingw32-，arm64-v8a -> aarch64-w64-mingw32-
    """
    triples = {"x86_64": "x86_64-w64-mingw32-", "arm64-v8a": "aarch64-w64-mingw32-"}
    pre = triples.get(arch, triples["x86_64"])
    gcc_name = pre + "gcc" + exe_suffix()
    gxx_name = pre + "g++" + exe_suffix()
    # 1) --mingw 指定目录
    if mingw_dir and os.path.isdir(mingw_dir):
        bin_dir = os.path.join(mingw_dir, "bin")
        cand = os.path.join(bin_dir, gcc_name)
        if os.path.exists(cand):
            return (cand,
                    os.path.join(bin_dir, gxx_name),
                    cand)
    # 2) PATH 中查找
    gcc = find_tool(gcc_name)
    gxx = find_tool(gxx_name)
    if gcc and gxx:
        return gcc, gxx, gcc
    return None


# ---------------------------------------------------------------------------
# 可编译性判定（host 系统约束 + SDK 是否就绪）
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    """
    返回 (ok, reason)。
    ctx: dict 携带 ndk / emsdk / mingw 等已解析的 SDK。
    """
    if platform == "WINDOWS":
        if host == "WINDOWS":
            return True, ""
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


# ---------------------------------------------------------------------------
# xmake 配置生成（对应 build.bat 中 `xmake f -p ...` 的参数部分）
# ---------------------------------------------------------------------------
def build_config(platform, mode, arch, toolchain, host, ctx):
    define = "-DBX_PLATFORM_%s=1" % platform

    # ---- WINDOWS（Windows 主机原生：msvc / mingw）----
    if platform == "WINDOWS" and host == "WINDOWS":
        if toolchain == "mingw":
            # 显式使用 --mingw 指定的完整 mingw-w64，避免 xmake 自动探测到
            # PATH 中残缺的 Git mingw64（无 ar/gcc）导致 "cannot get program for ar"
            tc = probe_mingw(arch, ctx.get("mingw"))
            if tc is not None:
                cc, cxx, ld = tc
                ar = os.path.join(os.path.dirname(cc), "ar" + exe_suffix())
                return ["-p", "windows", "-a", arch, "-m", mode,
                        "--toolchain=mingw", "--bx_platform=WINDOWS",
                        "--cc=" + cc, "--cxx=" + cxx, "--ld=" + ld, "--sh=" + cxx,
                        "--ar=" + ar,
                        "--cxflags=" + define, "--cxxflags=" + define]
        return ["-p", "windows", "-a", arch, "-m", mode,
                "--toolchain=" + toolchain, "--bx_platform=WINDOWS",
                "--cxflags=" + define, "--cxxflags=" + define]

    # ---- WINDOWS（非 Windows 主机：mingw-w64 交叉）----
    if platform == "WINDOWS":
        tc = probe_mingw(arch, ctx.get("mingw"))
        if tc is None:
            raise RuntimeError("缺少 %s 的 mingw-w64 工具链" % arch)
        cc, cxx, ld = tc
        ar = os.path.join(os.path.dirname(cc), "ar" + exe_suffix())
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=mingw", "--bx_platform=WINDOWS",
                "--cc=" + cc, "--cxx=" + cxx, "--ld=" + ld, "--sh=" + cxx,
                "--ar=" + ar,
                "--cxflags=" + define, "--cxxflags=" + define]

    # ---- ANDROID：cross + NDK clang（任何主机，需 NDK）----
    if platform == "ANDROID":
        ndk = ctx.get("ndk")
        if not ndk:
            raise RuntimeError("ANDROID 需要 NDK 路径")
        cc, cxx, ld, sysroot, target = probe_ndk(ndk, arch, host)
        cross = ("--target=" + target + " --sysroot=" + sysroot)
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=clang", "--bx_platform=ANDROID",
                "--cc=" + cc, "--cxx=" + cxx, "--ld=" + ld, "--sh=" + cxx,
                "--cxflags=" + define + " " + cross,
                "--cxxflags=" + define + " " + cross,
                "--ldflags=" + cross, "--shflags=" + cross]

    # ---- OPHM（OpenHarmony / HarmonyOS）：cross + OHOS NDK clang ----
    if platform == "OPHM":
        sdk = ctx.get("ohos")
        if not sdk:
            raise RuntimeError("OPHM 需要 OHOS SDK 路径")
        cc, cxx, ld, sysroot, target = probe_ohos(sdk, arch)
        cross = ("--target=" + target + " --sysroot=" + sysroot)
        # OpenHarmony 兼容 Linux API：bx_platform 走 OPHM（debug.cpp 用 hilog），
        # 同时定义 BX_PLATFORM_LINUX=1，让 renderer 走 compat/linux + GLES30 路径
        ohm_def = "-DBX_PLATFORM_OPHM=1 -DBX_PLATFORM_LINUX=1"
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=clang", "--bx_platform=OPHM",
                "--cc=" + cc, "--cxx=" + cxx, "--ld=" + ld, "--sh=" + cxx,
                "--cxflags=" + ohm_def + " " + cross,
                "--cxxflags=" + ohm_def + " " + cross,
                "--ldflags=" + cross, "--shflags=" + cross]

    # ---- EMSCRIPTEN：cross + emcc（任何主机，需 emsdk）----
    if platform == "EMSCRIPTEN":
        emsdk = ctx.get("emsdk")
        if not emsdk:
            raise RuntimeError("EMSCRIPTEN 需要 emsdk 路径")
        emcc, emxx = probe_emsdk(emsdk)
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=clang", "--bx_platform=EMSCRIPTEN",
                "--cc=" + emcc, "--cxx=" + emxx, "--ld=" + emcc, "--sh=" + emxx,
                "--cxflags=" + define, "--cxxflags=" + define]

    # ---- IOS：macOS + Xcode 交叉（arm64 真机 / x86_64 模拟器）----
    if platform == "IOS":
        cc = _xcode_tool("clang")
        cxx = _xcode_tool("clang++")
        if arch == "arm64-v8a":
            sdk_name, target = "iphoneos", "arm64-apple-ios"
        else:
            sdk_name, target = "iphonesimulator", "x86_64-apple-ios-simulator"
        sdk = _xcode_sdk(sdk_name)
        cross = ("--target=" + target + " --sysroot=" + sdk)
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=clang", "--bx_platform=IOS",
                "--cc=" + cc, "--cxx=" + cxx, "--ld=" + cc, "--sh=" + cxx,
                "--cxflags=" + define + " " + cross,
                "--cxxflags=" + define + " " + cross,
                "--ldflags=" + cross, "--shflags=" + cross]

    # ---- OSX：macOS 原生 clang（--target 区分 arm64 / x86_64）----
    if platform == "OSX":
        cc = find_tool("clang") or _xcode_tool("clang")
        cxx = find_tool("clang++") or _xcode_tool("clang++")
        target = "arm64-apple-macosx" if arch == "arm64-v8a" else "x86_64-apple-macosx"
        return ["-p", "cross", "-a", arch, "-m", mode,
                "--toolchain=clang", "--bx_platform=OSX",
                "--cc=" + cc, "--cxx=" + cxx, "--ld=" + cc, "--sh=" + cxx,
                "--cxflags=" + define + " --target=" + target,
                "--cxxflags=" + define + " --target=" + target,
                "--ldflags=--target=" + target, "--shflags=--target=" + target]

    # ---- LINUX / BSD：cross + clang（本机原生）----
    return ["-p", "cross", "-a", arch, "-m", mode,
            "--toolchain=clang", "--bx_platform=" + platform,
            "--cxflags=" + define, "--cxxflags=" + define]


def _xcode_tool(name):
    """通过 xcrun 定位 Xcode 工具链中的编译器"""
    try:
        out = subprocess.check_output(["xcrun", "-f", name],
                                      stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return None


def _xcode_sdk(sdk_name):
    try:
        out = subprocess.check_output(["xcrun", "--sdk", sdk_name, "--show-sdk-path"],
                                      stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return None


def toolchains_for(platform, host, libtype=None):
    """每个平台候选工具链（按优先级）：WINDOWS 主机上 msvs 优先，失败回退 mingw"""
    _ = libtype  # 保留参数，供未来扩展（如 MSVC 区分 static/shared）
    if platform == "WINDOWS" and host == "WINDOWS":
        return ["msvc", "mingw"]   # 优先 msvs(msvc)，失败用 mingw
    return ["clang"]


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


def xmake_path():
    p = find_tool("xmake")
    if not p:
        print("[ERROR] 未找到 xmake，请先安装并加入 PATH（https://xmake.io）")
        sys.exit(1)
    return p


# ---------------------------------------------------------------------------
# EMSCRIPTEN 环境：设置 EMSDK 相关环境变量并扩充 PATH
# ---------------------------------------------------------------------------
def build_env(platform, emsdk):
    env = os.environ.copy()
    if platform == "EMSCRIPTEN" and emsdk:
        env["EMSDK"] = emsdk
        env["EMSDK_NODE"] = os.path.join(emsdk, "node", "bin")  # 不一定存在，无碍
        extra = [
            os.path.join(emsdk, "upstream", "emscripten"),
            os.path.join(emsdk, "upstream", "bin"),
            os.path.join(emsdk, "node"),
        ]
        for d in extra:
            bin_dir = d if os.path.isdir(d) else None
            if bin_dir:
                env["PATH"] = bin_dir + os.pathsep + env["PATH"]
    return env


# ---------------------------------------------------------------------------
# 构建单个 (平台, 模式, 架构, 工具链) 组合
# ---------------------------------------------------------------------------
def build_one(platform, mode, arch, libtype, toolchain, host, args, ctx, log_path):
    for proj in SUBPROJECTS:
        proj_dir = os.path.join(SCRIPT_DIR, proj)
        if not os.path.isdir(proj_dir):
            print("  [ERROR] 子项目目录不存在: %s" % proj_dir)
            return False
        cfg = build_config(platform, mode, arch, toolchain, host, ctx)
        # 库类型（static/shared）经各子项目 xmake.lua 的 libtype option 生效
        cfg += ["--libtype=" + libtype]
        env = build_env(platform, ctx.get("emsdk"))

        print("  [%s/%s] 清除并配置 %s (toolchain=%s) ..." % (mode, arch, proj, toolchain))
        if run([xmake_path(), "f", "-c"], proj_dir, env, log_path) != 0:
            return False
        if run([xmake_path(), "f"] + cfg, proj_dir, env, log_path) != 0:
            return False

        print("  [%s/%s] 编译 %s ..." % (mode, arch, proj))
        if run([xmake_path(), "-j", str(args.jobs)], proj_dir, env, log_path) != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# 产物目录清理：每个组合编译前清空 output/，避免上一组合的库混入本次打包
# ---------------------------------------------------------------------------
def clean_output():
    """清空 xmake 编译产物目录 output/（LIB_OUT 所在根目录）"""
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        print("  已清空编译产物目录: %s" % OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 打包：把 Headers 头文件 + C API 头 + 静态库/动态库打成规范命名 zip
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, toolchain, dist_dir):
    name = "bgfx4cj-%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")

    lib_dir = os.path.join(LIB_OUT, arch)
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

    # MinGW 编译产物为 .lib，另外创建一份规范命名 lib*.a 副本（匹配 cjpm.toml -l:lib*.a 格式）
    # 分两个子目录：lib/ 放 .lib，lib_a/ 放 lib*.a
    temp_a_dir = os.path.join(OUTPUT_DIR, "lib_a", arch)
    if os.path.isdir(temp_a_dir):
        shutil.rmtree(temp_a_dir, ignore_errors=True)
    for lf in lib_files:
        if lf.endswith(".lib"):
            base = os.path.basename(lf)
            # 转换规则：xxx.lib → libxxx.a（如 bgfx.lib → libbgfx.a）
            a_name = "lib" + base.replace(".lib", ".a")
            a_path = os.path.join(temp_a_dir, a_name)
            os.makedirs(temp_a_dir, exist_ok=True)
            shutil.copy2(lf, a_path)
    a_files = []
    for root, _dirs, files in os.walk(temp_a_dir):
        for f in files:
            if f.endswith(".a"):
                a_files.append(os.path.join(root, f))

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件集合（Headers/bgfx/Header/**）
        if os.path.isdir(HEADERS_DIR):
            for root, _dirs, files in os.walk(HEADERS_DIR):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, HEADERS_DIR)
                    z.write(full, os.path.join(name, "include", rel))
        # C API 头文件
        for _tag, rel in CAPI_HEADERS.items():
            src = os.path.join(SCRIPT_DIR, rel)
            if os.path.exists(src):
                z.write(src, os.path.join(name, "include", os.path.basename(rel)))
        # 静态库 / 动态库（.lib 格式，放 lib/ 目录）
        for lf in lib_files:
            rel = os.path.relpath(lf, LIB_OUT)
            z.write(lf, os.path.join(name, "lib", rel))
        # MinGW 产物另存 .a 副本，放 lib_a/ 目录
        for af in a_files:
            rel = os.path.relpath(af, temp_a_dir)
            z.write(af, os.path.join(name, "lib_a", rel))
    return zip_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    set_batch_flag(args.batch)

    if args.clean:
        for d in (OUTPUT_DIR, DIST_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    xmake_path()
    host = detect_host()
    print("=" * 60)
    print("  bgfx4cj 全平台交叉编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  xmake:    %s" % xmake_path())
    print("=" * 60)

    platforms = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    modes     = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    arches    = [a.strip().lower() for a in args.arches.split(",") if a.strip()]
    libtypes  = [t.strip().lower() for t in args.libtype.split(",") if t.strip()]

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
    if "OPHM" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OPHM 平台因缺少 OHOS SDK 路径被跳过")
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
                    combo_name = "bgfx4cj-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)
                    # 每个组合编译前清空产物目录，避免与上一组合/上次运行的产物混在一起
                    clean_output()
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


if __name__ == "__main__":
    main()
