#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
luajit4cj 全平台自动交叉编译 + 打包脚本
======================================
驱动 LuaJIT 自带的 src/Makefile（GNU make）编译 LuaJIT C 侧库，
CLI 约定与 bgfx4cj/cxx/build.py 对齐：
  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a（对应 LuaJIT TARGET_ARCH x64 / arm64）
  - 平台:   LINUX WINDOWS ANDROID OPHM BSD IOS OSX
  - 工具链: mingw / clang（NDK、OHOS SDK、xcrun）
  - 库类型: static / shared（对应 LuaJIT BUILDMODE static / dynamic）

说明：
  - LuaJIT 没有 Emscripten/wasm 后端，故平台清单不含 EMSCRIPTEN；
  - OPHM = OpenHarmony / HarmonyOS，使用 OHOS NDK 的 llvm clang +
    --target=*-linux-ohos 交叉编译（TARGET_SYS 走 Linux）；
  - LuaJIT 的 Makefile 不支持 out-of-tree 构建，产物/生成文件就地落在
    LuaJIT/src 下，且随 TARGET_LJARCH 变化。因此每个组合开始前会清理
    src 下的目标文件与生成头，避免架构串扰（跨平台必须 clean）；
  - Windows 上使用 mingw32-make（GNU make），不依赖 MSVC；
  - 每个组合编译成功后立即打包为规范命名 zip：
      include/（公开头） + lib/（库） + share/luajit-2.1/jit/（运行时模块）；
    WINDOWS x86_64 静态库额外安装到父工程 libs/（lua51_x64.lib /
    lua51_x64_debug.lib + include/，对齐 cjpm.toml 的链接名）。

用法示例：
  python build.py                                  # 全部平台排列组合（缺 SDK/宿主不符自动跳过）
  python build.py --platforms WINDOWS              # 只编 Windows（mingw）
  python build.py --platforms ANDROID --ndk D:/ndk
  python build.py --platforms OPHM --ohos-sdk D:/ohos
  python build.py --modes release --arches x86_64
  python build.py --libtype static                 # 只编静态库
  python build.py --batch                          # 非交互（不询问，缺 SDK 即跳过）
"""

import argparse
import glob
import os
import platform as _platform
import shutil
import subprocess
import sys
import zipfile

# CI-PATCH: --libs 选择性构建（默认全量；未知库名直接报错；输出保持声明顺序）
_ALLOWED_LIBS = ['luajit']


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
LUAJIT_DIR = os.path.join(SCRIPT_DIR, "LuaJIT")
SRC_DIR    = os.path.join(LUAJIT_DIR, "src")
DIST_DIR   = os.path.join(SCRIPT_DIR, "dist")
LOG_DIR    = os.path.join(DIST_DIR, "logs")
LIBS_DIR   = os.path.join(os.path.dirname(SCRIPT_DIR), "libs")   # 父工程 libs/

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OPHM", "BSD", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# LuaJIT 公开头文件（打包与安装到 libs/include/ 用）
PUBLIC_HEADERS = ["lua.h", "luaconf.h", "lauxlib.h", "lualib.h", "luajit.h", "lua.hpp"]

# LuaJIT 库产物扩展名（打包收集用）
LIB_EXTENSIONS = (".a", ".so", ".dll", ".dylib")

# 平台 -> LuaJIT Makefile 的 TARGET_SYS
TARGET_SYS = {
    "LINUX":   "Linux",
    "WINDOWS": "Windows",
    "ANDROID": "Linux",
    "OPHM":    "Linux",
    "BSD":     "BSD",
    "IOS":     "iOS",
    "OSX":     "Darwin",
}

# build.bat / bgfx4cj 里交互询问时的默认 SDK 路径
NDK_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

# 构建时清理的产物/生成文件（白名单，避免误删源码）
CLEAN_PATTERNS = [
    "*.o", "*.obj",
    "luajit.exe", "lua51.dll",
    "libluajit.a", "libluajit.so", "libluajit*.dylib", "libluajit*.dll.a",
    "lj_bcdef.h", "lj_ffdef.h", "lj_libdef.h", "lj_recdef.h", "lj_folddef.h",
]
CLEAN_SUBDIRS = {
    "host": ["*.o", "*.obj", "buildvm.exe", "minilua.exe", "buildvm_arch.h",
             "minilua", "buildvm"],
    "jit":  ["vmdef.lua"],
}


# ---------------------------------------------------------------------------
# 主机平台检测
# ---------------------------------------------------------------------------
def detect_host():
    sysname = _platform.system().lower()
    if sysname == "windows":
        return "WINDOWS"
    if sysname == "darwin":
        return "OSX"
    if sysname in ("freebsd", "openbsd", "netbsd"):
        return "BSD"
    if sysname == "linux":
        return "LINUX"
    return "UNKNOWN"


def machine_arch():
    m = _platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "arm64-v8a"
    return m


def is_windows():
    return _platform.system().lower() == "windows"


def exe_suffix():
    return ".exe" if is_windows() else ""


def find_tool(name):
    return shutil.which(name)


_BATCH_FLAG = False


def set_batch_flag(flag):
    global _BATCH_FLAG
    _BATCH_FLAG = flag


def ask(prompt, default=None):
    if _BATCH_FLAG:
        return default
    if default:
        prompt = "%s [%s]: " % (prompt, default)
    else:
        prompt = prompt + ": "
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v or default


# ---------------------------------------------------------------------------
# 命令行参数（与 bgfx4cj/cxx/build.py 对齐）
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="luajit4cj 全平台自动交叉编译 LuaJIT + 打包脚本（参考 bgfx4cj/cxx/build.py）",
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
                    help="库类型清单，逗号分隔: static,shared（默认全部，对应 LuaJIT BUILDMODE）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / OHOS_SDK）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OPHM 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 前缀工具链目录（WINDOWS 平台用，默认从 PATH 探测）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认 = CPU 核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--libs-dir", default=LIBS_DIR,
                    help="仓颉侧链接用库的拷贝目标目录（默认父工程 libs/）")
    ap.add_argument("--no-libs-copy", action="store_true",
                    help="编译后不拷贝库/头文件到 libs 目录（只打包 zip）")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 dist/")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式：不询问 SDK 路径，缺 SDK 的平台直接跳过并告警")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止（默认继续其余组合）")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序）：luajit（默认=全量编译）")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# SDK 路径解析
# ---------------------------------------------------------------------------
def resolve_ndk(args):
    """解析 NDK 路径（ANDROID 平台需要）"""
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
    """解析 HarmonyOS / OpenHarmony NDK 路径（OPHM 平台需要）"""
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


# ---------------------------------------------------------------------------
# 工具链探测
# ---------------------------------------------------------------------------
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


def make_path():
    """定位 GNU make：Windows 上用 mingw32-make，POSIX 上用 make"""
    name = "mingw32-make" if is_windows() else "make"
    p = find_tool(name)
    if not p:
        print("[ERROR] 未找到 GNU make（%s），请安装并加入 PATH（https://www.gnu.org/software/make/）"
              % name)
        sys.exit(1)
    return p


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


# ---------------------------------------------------------------------------
# 可编译性判定（host 系统约束 + SDK 是否就绪）
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    """
    返回 (ok, reason)。
    ctx: dict 携带 ndk / ohos / mingw 等已解析的 SDK。
    """
    if platform == "WINDOWS":
        if host == "WINDOWS":
            tc = probe_mingw("x86_64", ctx.get("mingw"))
            if tc:
                return True, ""
            return False, "Windows 主机未检测到 mingw-w64 工具链（x86_64-w64-mingw32-gcc）"
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


def toolchains_for(platform, host):
    """每个平台候选工具链（按优先级）"""
    if platform == "WINDOWS" and host == "WINDOWS":
        return ["mingw"]   # Windows 主机原生 mingw（无需 MSVC）
    return ["clang"]


# ---------------------------------------------------------------------------
# 构建配置：把 (平台, 模式, 架构, 库类型) 翻译成 LuaJIT Makefile 变量
# ---------------------------------------------------------------------------
def build_config(platform, mode, arch, libtype, toolchain, host, ctx):
    """
    返回传给 make 的变量参数列表。
    LuaJIT 交叉编译关键变量：
      HOST_CC     宿主编译器（构建 minilua/buildvm 用，必须能运行于本机）
      TARGET_CC  目标编译器（可含 --target/--sysroot 等前缀）
      TARGET_SYS Windows / Linux / Darwin / iOS / BSD
      BUILDMODE  static / dynamic
      Q=          关闭 @ 静默，便于日志定位
    """
    define = ""  # 预留
    exe = exe_suffix()

    # ---- HOST_CC：宿主编译器 ----
    if host == "WINDOWS":
        tc = probe_mingw("x86_64", ctx.get("mingw"))
        if tc is None:
            raise RuntimeError("缺少 mingw-w64 工具链（HOST_CC 需要）")
        host_cc, _host_cxx, _host_ld = tc
    elif host == "OSX":
        host_cc = _xcode_tool("clang") or find_tool("clang") or "clang"
    elif host == "BSD":
        host_cc = "cc"
    else:  # LINUX / 其他 POSIX
        host_cc = "cc"

    # ---- TARGET_CC：目标编译器 ----
    if platform == "WINDOWS":
        # Windows 目标：mingw（Windows 主机原生 或 非 Windows 主机交叉）
        tc = probe_mingw(arch, ctx.get("mingw"))
        if tc is None:
            raise RuntimeError("缺少 %s 的 mingw-w64 工具链" % arch)
        cc, cxx, ld = tc
        target_cc = cc
    elif platform in ("ANDROID", "OPHM"):
        if platform == "ANDROID":
            ndk = ctx.get("ndk")
            if not ndk:
                raise RuntimeError("ANDROID 需要 NDK 路径")
            cc, cxx, ld, sysroot, target = probe_ndk(ndk, arch, host)
        else:
            sdk = ctx.get("ohos")
            if not sdk:
                raise RuntimeError("OPHM 需要 OHOS SDK 路径")
            cc, cxx, ld, sysroot, target = probe_ohos(sdk, arch)
        cross = "--target=" + target + " --sysroot=" + sysroot
        target_cc = cc + " " + cross
    elif platform == "LINUX":
        # CI-PATCH: x86_64 runner 上构建 arm64-v8a 是交叉编译（linux.yml 已装
        # gcc-aarch64-linux-gnu），必须用三元组前缀编译器 —— 裸 cc 会让 LuaJIT
        # 按宿主 x64 配置（vm_x64.dasc），链接 .so 时报
        # "R_X86_64_TPOFF32 ... recompile with -fPIC"
        if arch == "arm64-v8a":
            cross = find_tool("aarch64-linux-gnu-gcc") or "aarch64-linux-gnu-gcc"
            target_cc = cross
        else:
            target_cc = "cc"
    elif platform == "BSD":
        target_cc = "cc"
    elif platform == "OSX":
        base = _xcode_tool("clang") or find_tool("clang")
        if not base:
            raise RuntimeError("OSX 需要 clang")
        target = "arm64-apple-macosx" if arch == "arm64-v8a" else "x86_64-apple-macosx"
        # CI-PATCH: 必须带 -isysroot（同 IOS 分支）——CI runner 的裸 clang
        # 不一定继承 SDKROOT，缺 sysroot 时 TargetConditionals.h/math.h/
        # sys/types.h 全部找不到（macOS job 实测）。HOST_CC 同样补上：
        # HOSTCC 阶段（minilua/buildvm）报的正是这组缺失。
        sdk_path = _xcode_sdk("macosx")
        if not sdk_path:
            raise RuntimeError("无法获取 macosx SDK 路径（xcrun --sdk macosx --show-sdk-path）")
        isysroot = " -isysroot " + sdk_path
        host_cc = host_cc + isysroot
        target_cc = base + isysroot + " --target=" + target
    elif platform == "IOS":
        if not find_tool("xcrun"):
            raise RuntimeError("IOS 需要 xcrun")
        sdk = "iphoneos" if arch == "arm64-v8a" else "iphonesimulator"
        sdk_path = _xcode_sdk(sdk)
        if not sdk_path:
            raise RuntimeError("无法获取 %s SDK 路径（xcrun --sdk %s --show-sdk-path）" % (sdk, sdk))
        base = _xcode_tool("clang") or "clang"
        target = "arm64-apple-ios" if arch == "arm64-v8a" else "x86_64-apple-ios-simulator"
        # CI-PATCH: HOST_CC 同样补 macosx -isysroot（与 OSX 分支同因）——
        # IOS 的 host 工具（minilua/buildvm）运行在 macOS 上，CI 裸 clang
        # 不继承 SDKROOT 时 HOSTCC 阶段找不到 TargetConditionals.h 等。
        host_isysroot = _xcode_sdk("macosx")
        if host_isysroot:
            host_cc = host_cc + " -isysroot " + host_isysroot
        # 注意：sysroot 必须在 Python 侧解析后拼进 TARGET_CC，
        # 不能写成 $(xcrun ...) —— 那会被 make 当作变量引用展开为空。
        # CI-PATCH: iOS SDK 显式标记 system() 为 unavailable，lib_os.c:52
        # 的 os_execute 编译报错（CI 实测 'system' is unavailable: not
        # available on iOS）。上游在 LJ_TARGET_IOS 探测命中时自动置
        # LJ_NO_SYSTEM=1 走 ENOSYS 桩（lj_arch.h），但探测链依赖
        # TargetConditionals/版本宏，这里直接显式定义，路径与上游桩一致
        # （命令行与头文件重复定义同值 1 合法）。
        target_cc = base + " -isysroot " + sdk_path + " --target=" + target \
            + " -DLJ_NO_SYSTEM=1"
    else:
        raise RuntimeError("不支持的平台: %s" % platform)

    # ---- LuaJIT Makefile 变量 ----
    # shared 构建的 _dyn.o 需要 -fPIC（Makefile 的 DYNAMIC_CC 默认带，
    # 但命令行覆盖 TARGET_DYNCC 后必须自己补上）。
    dyncc = target_cc
    if platform in ("ANDROID", "OPHM"):
        dyncc = target_cc + " -fPIC"
    elif platform == "LINUX" and arch == "arm64-v8a":
        # CI-PATCH: 同上 —— 覆盖 TARGET_DYNCC 后 Makefile 默认的
        # DYNAMIC_CC=...-fPIC 不再生效，交叉构建 shared 需显式补 -fPIC
        dyncc = target_cc + " -fPIC"
    elif platform == "IOS":
        # CI-PATCH: 同上 —— IOS 覆盖 TARGET_DYNCC 后需补 -fPIC（macOS
        # Makefile 分支的 TARGET_DYNCC= $(STATIC_CC) 亦无 -fPIC）
        dyncc = target_cc + " -fPIC"
    vars = [
        "HOST_CC=" + host_cc,
        "TARGET_CC=" + target_cc,
        "TARGET_STCC=" + target_cc,
        "TARGET_DYNCC=" + dyncc,
        "TARGET_SYS=" + TARGET_SYS[platform],
        "BUILDMODE=" + ("dynamic" if libtype == "shared" else "static"),
        "Q=",
    ]
    if platform in ("ANDROID", "OPHM"):
        # Windows 宿主上 mingw32-make 的 shell 是 cmd.exe，LuaJIT Makefile
        # 里的 POSIX 检测/重定向全部失效，必须显式覆盖：
        #  1) TARGET_TESTUNWIND 检测不到 eh_frame → x64 的 lj_err.c 触发
        #     #error "Broken build system"，需注入 -DLUAJIT_UNWIND_EXTERNAL
        #     （仅 x86_64 必需；arm64 无该 #error）
        #  2) TARGET_AR+= 2>/dev/null 在 cmd 下报 "cannot find the path"
        #     → 覆盖为不带重定向的 ar rcus
        #  3) TARGET_LD 默认 $(CROSS)$(CC)=宿主 gcc，链接 arm64 ELF 报
        #     "Relocations in generic ELF" → 必须用交叉 clang
        #  4) TARGET_STRIP 默认宿主 strip → 用工具链的 llvm-strip
        bin_dir = os.path.dirname(cc)
        strip = os.path.join(bin_dir, "llvm-strip" + exe)
        vars.append("TARGET_AR=ar rcus")
        vars.append("TARGET_LD=" + target_cc)
        vars.append("TARGET_STRIP=" + strip)
        if arch == "x86_64":
            vars.append("XCFLAGS=-DLUAJIT_UNWIND_EXTERNAL")
    elif platform == "WINDOWS":
        # WINDOWS 目标：若用 --mingw 指定了交叉工具链（如 llvm-mingw 的
        # aarch64-w64-mingw32-gcc），Makefile 默认的 TARGET_LD=$(CC)=宿主
        # gcc 无法链接目标架构对象（luajit.exe 链接报 "file not recognized"），
        # 需显式用目标编译器链接；strip 同样用工具链的 llvm-strip。
        # 此外 TARGET_AR 也必须用工具链自带的 ar（PATH 里的 x86_64 ar
        # 打包 arm64 COFF 时符号索引不完整，链接报 undefined symbol）。
        bin_dir = os.path.dirname(cc)
        # CI-PATCH: strip 回退链——llvm-mingw 有 llvm-strip，标准 mingw-w64 只有 strip.exe
        strip = os.path.join(bin_dir, "llvm-strip" + exe)
        if not os.path.isfile(strip):
            strip = os.path.join(bin_dir, "strip" + exe)
            if not os.path.isfile(strip):
                strip = os.path.join(bin_dir, "llvm-strip" + exe)  # 保持原值让报错可见
        ar = os.path.join(bin_dir, "llvm-ar" + exe)
        if not os.path.isfile(ar):
            # 无通用 llvm-ar 时回退：标准 mingw-w64 只带无前缀 ar.exe，
            # llvm-mingw 才有 aarch64-w64-mingw32-ar（CI-PATCH 修复 NameError + 回退链）
            cand = os.path.join(bin_dir, "ar" + exe)
            if os.path.isfile(cand):
                ar = cand
            else:
                pre = {"x86_64": "x86_64-w64-mingw32-", "arm64-v8a": "aarch64-w64-mingw32-"} \
                    .get(arch, "x86_64-w64-mingw32-")
                ar = os.path.join(bin_dir, pre + "ar" + exe)
        vars.append("TARGET_AR=" + ar + " rcus")
        vars.append("TARGET_LD=" + target_cc)
        vars.append("TARGET_STRIP=" + strip)
    elif platform == "LINUX" and arch == "arm64-v8a":
        # CI-PATCH: x86_64 宿主上交叉构建 arm64-v8a —— Makefile 默认
        # TARGET_LD=$(CROSS)$(CC)=宿主 gcc，链接 arm64 ELF 报
        # "Relocations in generic ELF" → 必须用交叉编译器链接
        vars.append("TARGET_LD=" + target_cc)
        # 同理 strip 也默认宿主 strip，改用三元组工具（不存在时保持原值让报错可见）
        strip = find_tool("aarch64-linux-gnu-strip") or "aarch64-linux-gnu-strip"
        vars.append("TARGET_STRIP=" + strip)
    if mode == "debug":
        vars.append("CCDEBUG=-g")
    return vars


# ---------------------------------------------------------------------------
# 清理 LuaJIT/src 下的构建产物（LuaJIT 就地构建，跨架构必须清理）
# ---------------------------------------------------------------------------
def clean_src():
    for pat in CLEAN_PATTERNS:
        for f in glob.glob(os.path.join(SRC_DIR, pat)):
            try:
                os.remove(f)
            except OSError:
                pass
    for sub, pats in CLEAN_SUBDIRS.items():
        d = os.path.join(SRC_DIR, sub)
        if not os.path.isdir(d):
            continue
        for pat in pats:
            for f in glob.glob(os.path.join(d, pat)):
                try:
                    os.remove(f)
                except OSError:
                    pass


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


# ---------------------------------------------------------------------------
# 构建单个 (平台, 模式, 架构, 库类型) 组合
# ---------------------------------------------------------------------------
def build_one(platform, mode, arch, libtype, toolchain, host, args, ctx, log_path):
    cfg = build_config(platform, mode, arch, libtype, toolchain, host, ctx)
    # macOS 目标：LuaJIT 的 Makefile 在 Darwin 分支强制要求 MACOSX_DEPLOYMENT_TARGET，
    # 否则报 "missing: export MACOSX_DEPLOYMENT_TARGET=XX.YY"。
    env = os.environ.copy()
    if platform == "OSX" and not env.get("MACOSX_DEPLOYMENT_TARGET"):
        env["MACOSX_DEPLOYMENT_TARGET"] = "10.13"
    make = make_path()

    print("  [%s/%s] 清理 LuaJIT/src 构建产物 ..." % (mode, arch))
    clean_src()

    print("  [%s/%s] make %s ..." % (mode, arch, " ".join(cfg)))
    if run([make, "-j", str(args.jobs)] + cfg, SRC_DIR, env, log_path) != 0:
        return False
    return True


# ---------------------------------------------------------------------------
# 打包：把公开头 + 库 + jit 运行时模块打成规范命名 zip
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, toolchain, dist_dir):
    name = "luajit4cj-%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")

    lib_files = []
    for f in os.listdir(SRC_DIR):
        full = os.path.join(SRC_DIR, f)
        if os.path.isfile(full) and f.endswith(LIB_EXTENSIONS):
            lib_files.append(full)
    if not lib_files:
        print("  [WARN] %s 下没有库文件，跳过打包" % SRC_DIR)
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 公开头文件
        for h in PUBLIC_HEADERS:
            src = os.path.join(SRC_DIR, h)
            if os.path.isfile(src):
                z.write(src, os.path.join(name, "include", h))
        # 库文件
        for lf in lib_files:
            z.write(lf, os.path.join(name, "lib", os.path.basename(lf)))
        # jit 运行时模块（jit/*.lua，LuaJIT 运行期需要）
        jit_dir = os.path.join(SRC_DIR, "jit")
        if os.path.isdir(jit_dir):
            for f in sorted(os.listdir(jit_dir)):
                if f.endswith(".lua"):
                    z.write(os.path.join(jit_dir, f), os.path.join(name, "jit", f))
    return zip_path


# ---------------------------------------------------------------------------
# 安装 WINDOWS x86_64 静态库到父工程 libs/（对齐 cjpm.toml 链接名 lua51_x64.lib）
# ---------------------------------------------------------------------------
def install_windows_libs(platform, mode, arch, libtype, libs_dir):
    if not (platform == "WINDOWS" and arch == "x86_64" and libtype == "static"):
        return
    libname = "lua51_x64_debug.lib" if mode == "debug" else "lua51_x64.lib"
    liba = os.path.join(SRC_DIR, "libluajit.a")
    if not os.path.isfile(liba):
        print("  [WARN] 未找到 libluajit.a，跳过安装到 libs/")
        return
    os.makedirs(libs_dir, exist_ok=True)
    shutil.copyfile(liba, os.path.join(libs_dir, libname))
    inc_dir = os.path.join(libs_dir, "include")
    os.makedirs(inc_dir, exist_ok=True)
    for h in PUBLIC_HEADERS:
        src = os.path.join(SRC_DIR, h)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(inc_dir, h))
    print("  [OK] 已安装 %s 与头文件到 %s" % (libname, libs_dir))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    libs_wanted = parse_libs_arg(args.libs, _ALLOWED_LIBS, "luajit")
    if "luajit" not in libs_wanted:
        print("[luajit] --libs 未包含 luajit，整组跳过")
        return
    set_batch_flag(args.batch)

    if args.clean and os.path.isdir(DIST_DIR):
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        print("已清理: %s" % DIST_DIR)

    make_path()
    host = detect_host()
    print("=" * 60)
    print("  luajit4cj 全平台自动交叉编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  make:     %s" % make_path())
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
    ctx = {"ndk": None, "ohos": None, "mingw": args.mingw}
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")
    if "OPHM" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OPHM 平台因缺少 OHOS SDK 路径被跳过")

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
                    combo_name = "luajit4cj-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)
                    toolchains = toolchains_for(platform, host)
                    done = False
                    for tc in toolchains:
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo_name, tc))
                        log_path = os.path.join(LOG_DIR, combo_name + "-" + tc + ".log")
                        try:
                            ok_build = build_one(platform, mode, arch, libtype, tc,
                                                 host, args, ctx, log_path)
                        except RuntimeError as e:
                            print("  [ERROR] %s" % e)
                            ok_build = False
                        if ok_build:
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
                            if not args.no_libs_copy:
                                install_windows_libs(platform, mode, arch,
                                                     libtype, args.libs_dir)
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
    for name, status, note in results:
        if status == "ok":
            print("  [OK]   %-52s %s" % (name, note))
        elif status == "skip":
            print("  [SKIP] %-52s %s" % (name, note))
        else:
            print("  [FAIL] %-52s %s" % (name, note))
    failed = [r for r in results if r[1] == "fail"]
    print("=" * 60)
    if failed:
        print("  共 %d 个组合失败，详见 dist/logs/ 下对应日志" % len(failed))
    else:
        print("  全部组合编译打包完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
