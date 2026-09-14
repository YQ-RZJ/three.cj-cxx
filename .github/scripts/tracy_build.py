#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tracy4cj 全平台自动交叉编译 + 打包脚本
======================================
编译 Tracy 客户端（tracy/public/TracyClient.cpp）为静态库并打包 zip
（格式对齐 cxx/bgfx/build.py）：

  - 库产物:   output/build-<platform>-<arch>-<mode>/lib/ 下
              libtracyc.a（release）/ libtracycd.a（debug）
              （MSVC 工具链额外产出 tracyc.lib / tracycd.lib，并附 lib*.a 副本）
  - zip 产物: <dist>/tracy4cj-<platform>-<arch>-<mode>-<toolchain>.zip
      include/ = tracy/public 全部头文件（TracyC.h + client/ + common/ + tracy/）
      lib/     = 静态库

  - 平台:   WINDOWS LINUX ANDROID OPHM IOS OSX
  - 架构:   x86_64 / arm64
  - 模式:   release / debug
  - 工具链: WINDOWS 主机优先 mingw（mingw-w64 gcc 与 llvm-mingw clang 均支持），
            回退 msvc；其余平台 ndk / ohos / clang native / xcode

说明：
  OPHM = OpenHarmony / HarmonyOS：使用 DevEco NDK 的 clang
  --target=*-linux-ohos --sysroot=<sdk>/sysroot 交叉编译。

行为约定：
  1. 无参运行时尝试编译所有"当前能编译"的平台并打包 zip；
  2. WINDOWS 主机优先 mingw-w64（与 three.cj 工具链一致），回退 msvc(cl.exe)；
     llvm-mingw（clang 后端）与 mingw-w64（gcc 后端）自动识别并使用各自兼容参数；
  3. LINUX / OSX 使用本机 clang（回退 gcc）；
  4. ANDROID 需要 NDK 路径（命令行 > 环境变量 > 交互询问）；
  5. OPHM 需要 OHOS SDK 路径（命令行 > 环境变量 > 交互询问）；
  6. IOS / OSX 必须在 macOS 上编译。

用法示例：
  python build.py                                  # 编译全部可编译平台并打包
  python build.py --platforms WINDOWS              # 只编 Windows
  python build.py --platforms WINDOWS --arches arm64 --modes release,debug
  python build.py --dist D:/out --skip-package     # 只编译不打包
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
_ALLOWED_LIBS = ['tracy']


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
TRACY_SRC  = os.path.join(SCRIPT_DIR, "tracy", "public", "TracyClient.cpp")
TRACY_PUB  = os.path.join(SCRIPT_DIR, "tracy", "public")          # include 根（打包用）
TRACY_INC  = TRACY_PUB                                            # -I 路径
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
DIST_DIR   = os.path.join(SCRIPT_DIR, "dist")

ALL_PLATFORMS = ["WINDOWS", "LINUX", "ANDROID", "OPHM", "IOS", "OSX"]
ALL_MODES     = ["release", "debug"]
ALL_ARCHES    = ["x86_64", "arm64"]

NDK_DEFAULT  = os.environ.get("ANDROID_NDK_HOME", r"C:\Android\Sdk\ndk")
OHOS_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

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
    return "OTHER"


def machine_arch():
    """返回 python 视角的本机架构（arm64 / x86_64 / ...）"""
    m = _platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    return m


def is_windows():
    return os.name == "nt"


def exe_suffix():
    return ".exe" if is_windows() else ""


def find_tool(name):
    """在 PATH 中查找可执行文件，返回绝对路径或 None"""
    p = shutil.which(name)
    return os.path.abspath(p) if p else None


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="tracy4cj 全平台自动交叉编译 + 打包脚本（TracyClient.cpp → 静态库 → zip）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔: " + ",".join(ALL_PLATFORMS)
                         + "（默认全部，OPHM=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单，逗号分隔: release,debug（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单，逗号分隔: x86_64,arm64（默认全部）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / ANDROID_NDK_ROOT）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OPHM 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 / llvm-mingw 工具链目录（也可用环境变量 MINGW / LLVM_MINGW）")
    ap.add_argument("--toolchain", default=None, choices=["mingw", "msvc"],
                    help="Windows 工具链选择（默认 mingw 优先，与 cjc 的 lld mingw ABI 匹配；msvc 产物仅供独立 C++ 场景）")
    ap.add_argument("--android-api", type=int, default=24,
                    help="Android 最低 API 级别（默认 24）")
    ap.add_argument("--ios-deploy-target", default="13.0",
                    help="iOS 最低部署版本（默认 13.0）")
    ap.add_argument("--macos-deploy-target", default="10.15",
                    help="macOS 最低部署版本（默认 10.15）")
    ap.add_argument("--jobs", type=int, default=1,
                    help="并行编译任务数（单文件编译，默认 1）")
    ap.add_argument("--dist", default=DIST_DIR,
                    help="zip 与日志输出目录（默认 cxx/tracy/dist/）")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 output/ 与 dist/")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式：不询问 SDK 路径，缺 SDK 的平台直接跳过并告警")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止（默认继续其余组合）")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序）：tracy（默认=全量编译）")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# SDK 路径解析：命令行参数 > 环境变量 > 交互询问
# ---------------------------------------------------------------------------
def resolve_ndk(args):
    v = (args.ndk
         or os.environ.get("ANDROID_NDK_HOME")
         or os.environ.get("ANDROID_NDK_ROOT"))
    if not v:
        v = ask("请输入 Android NDK 路径", default=NDK_DEFAULT)
    if not v or not os.path.isdir(v):
        print("  [ERROR] NDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def resolve_ohos_sdk(args):
    v = (args.ohos_sdk
         or os.environ.get("OHOS_SDK")
         or os.environ.get("OHOS_NDK_HOME"))
    if not v:
        v = ask("请输入 HarmonyOS / OpenHarmony NDK 路径", default=OHOS_DEFAULT)
    if not v or not os.path.isdir(v):
        print("  [ERROR] OHOS SDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


def normalize_mingw_dir(v):
    if not v:
        return None
    v = os.path.normpath(v)
    if os.path.basename(v).lower() == "bin":
        v = os.path.dirname(v)
    return v


def resolve_mingw(args):
    v = args.mingw or os.environ.get("MINGW") or os.environ.get("LLVM_MINGW")
    return normalize_mingw_dir(v)


# ---------------------------------------------------------------------------
# 工具链探测
# ---------------------------------------------------------------------------
_GXX_KIND_CACHE = {}


def gxx_kind(gxx_path):
    """探测 g++ 后端类型：'gcc'（mingw-w64 GNU g++）或 'clang'（llvm-mingw）。
    llvm-mingw 的 *-g++ 实为 clang，不认 gcc 专属参数（-mthreads/-static-libstdc++ 等），
    必须按后端区分编译参数。结果按路径缓存（子进程探测较慢）。"""
    if gxx_path in _GXX_KIND_CACHE:
        return _GXX_KIND_CACHE[gxx_path]
    kind = "gcc"
    try:
        out = subprocess.run([gxx_path, "--version"],
                             capture_output=True, universal_newlines=True,
                             errors="replace", timeout=30)
        text = (out.stdout or "") + (out.stderr or "")
        if "clang" in text.lower():
            kind = "clang"
    except Exception:
        pass
    _GXX_KIND_CACHE[gxx_path] = kind
    return kind


def probe_mingw(arch, mingw_dir):
    """返回 (g++, ar, kind) 或 None。arch: x86_64 / arm64
    kind: 'gcc'（mingw-w64）或 'clang'（llvm-mingw）。
    arm64 必须使用带 triple 前缀的编译器（aarch64-w64-mingw32-g++），
    PATH 上的裸 g++ 只能编本机架构，不能交叉出 arm64。"""
    exe = exe_suffix()
    prefix = "aarch64-w64-mingw32-" if arch == "arm64" else "x86_64-w64-mingw32-"
    candidates = []
    if mingw_dir and os.path.isdir(mingw_dir):
        candidates.append(os.path.join(mingw_dir, "bin"))
    candidates.append(None)  # PATH

    for bin_dir in candidates:
        if bin_dir:
            gxx = os.path.join(bin_dir, prefix + "g++" + exe)
            if os.path.exists(gxx):
                ar = os.path.join(bin_dir, "ar" + exe)
                if not os.path.exists(ar):
                    ar = os.path.join(bin_dir, prefix + "ar" + exe)
                return gxx, ar, gxx_kind(gxx)
            # llvm-mingw 也提供 clang++ 别名（部分发行版无 g++ 软链）
            clangxx = os.path.join(bin_dir, prefix + "clang++" + exe)
            if os.path.exists(clangxx):
                ar = os.path.join(bin_dir, "llvm-ar" + exe)
                if not os.path.exists(ar):
                    ar = os.path.join(bin_dir, prefix + "ar" + exe)
                return clangxx, ar, "clang"
        else:
            # PATH 查找：arm64 只认 triple 前缀；x86_64 可回退裸 g++
            gxx = find_tool(prefix + "g++" + exe) or find_tool(prefix + "clang++" + exe)
            if not gxx and arch == "x86_64":
                gxx = find_tool("g++" + exe)
            if gxx:
                bin2 = os.path.dirname(gxx)
                ar = (find_tool("llvm-ar" + exe) or find_tool("ar" + exe)
                      or os.path.join(bin2, "ar" + exe))
                return gxx, ar, gxx_kind(gxx)
    return None


def probe_msvc(arch="x86_64"):
    """探测 MSVC（宽查询，不依赖 -requires 过滤）。
    返回 (cl, lib, link, vs_root, vcvars_args) 或 None。
    vcvars_args: 与目标架构匹配的 vcvarsall.bat 参数（x64 / amd64_arm64）。"""
    vswhere_candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
        r"C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe",
    ]
    host_dir = "Hostx64"
    arch_dir = {"x86_64": "x64", "arm64": "arm64"}.get(arch, "x64")
    # 目标三元组环境：x64 用原生 x64，arm64 用 amd64 宿主交叉 arm64
    vcvars_args = {"x86_64": ["x64"], "arm64": ["amd64_arm64"]}.get(arch, ["x64"])
    for vswhere in vswhere_candidates:
        if not os.path.isfile(vswhere):
            continue
        # 宽查询 -all：本机 VS 安装可能带 isComplete=0 标记，-latest/-requires 会漏掉；
        # 老版 vswhere 的 -property 提取不稳定，直接从全量文本解析 installationPath
        try:
            out = subprocess.check_output(
                [vswhere, "-all", "-prerelease", "-products", "*"],
                stderr=subprocess.DEVNULL, universal_newlines=True, errors="replace")
        except Exception:
            continue
        roots = re.findall(r"^installationPath:\s*(.+)$", out, re.MULTILINE)
        for root in roots:
            root = root.strip()
            if not root or not os.path.isdir(root):
                continue
            tools = os.path.join(root, "VC", "Tools", "MSVC")
            if not os.path.isdir(tools):
                continue
            for ver in sorted(os.listdir(tools), reverse=True):
                bin_dir = os.path.join(tools, ver, "bin", host_dir, arch_dir)
                cl = os.path.join(bin_dir, "cl.exe")
                if os.path.isfile(cl):
                    return (cl, os.path.join(bin_dir, "lib.exe"),
                            os.path.join(bin_dir, "link.exe"), root, vcvars_args)
    return None


def msvc_env(vs_root, vcvars_args):
    """通过 vcvarsall.bat 获取 MSVC 完整环境（INCLUDE/LIB 等），子进程继承用。
    写临时批处理调用（cmd /C 直接带引号路径在部分 shell 下解析失败）。
    vcvars_args 按目标架构选择（x64 / amd64_arm64），保证 arm64 目标的
    INCLUDE/LIB 指向正确的库目录。"""
    bat = os.path.join(vs_root, "VC", "Auxiliary", "Build", "vcvarsall.bat")
    if not os.path.isfile(bat):
        return None
    tmp_bat = os.path.join(OUTPUT_DIR, "_vcenv.bat")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(tmp_bat, "w", encoding="ascii") as f:
        f.write('@echo off\r\ncall "%s" %s >nul 2>&1\r\nset\r\n'
                % (bat, " ".join(vcvars_args)))
    try:
        r = subprocess.run(["cmd", "/C", tmp_bat],
                           capture_output=True, universal_newlines=True, errors="replace")
    except Exception:
        return None
    if r.returncode != 0:
        return None
    env = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.upper() != "PROMPT":
                env[k.upper()] = v
    return env if ("INCLUDE" in env and "LIB" in env) else None


def ndk_triplet_tool(arch, ndk):
    """返回 NDK 中目标三元组 clang++ 路径。"""
    triple = "aarch64-linux-android" if arch == "arm64" else "x86_64-linux-android"
    prebuilt = ("windows-x86_64" if is_windows() else "linux-x86_64")
    for api in range(34, 20, -1):
        cand = os.path.join(ndk, "toolchains", "llvm", "prebuilt", prebuilt,
                            "bin", "%s%d-clang++" % (triple, api) + exe_suffix())
        if os.path.isfile(cand):
            return cand
    # 通用 clang++ + --target
    gen = os.path.join(ndk, "toolchains", "llvm", "prebuilt", prebuilt,
                       "bin", "clang++" + exe_suffix())
    return gen if os.path.isfile(gen) else None


def ohos_clang(arch, sdk):
    """返回 OHOS SDK clang++ 路径。"""
    cand = os.path.join(sdk, "llvm", "bin", "clang++" + exe_suffix())
    return cand if os.path.isfile(cand) else None


# ---------------------------------------------------------------------------
# 可编译性判定
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    if platform == "WINDOWS":
        if host == "WINDOWS":
            if probe_msvc("x86_64") or probe_msvc("arm64") or \
               probe_mingw("x86_64", ctx.get("mingw")) or probe_mingw("arm64", ctx.get("mingw")):
                return True, ""
            return False, "Windows 主机上未检测到 MSVC 或 mingw-w64 工具链"
        if probe_msvc("x86_64") or probe_msvc("arm64") or \
           probe_mingw("x86_64", ctx.get("mingw")) or probe_mingw("arm64", ctx.get("mingw")):
            return True, ""
        return False, "非 Windows 主机且未检测到 MSVC 交叉或 mingw-w64 工具链"
    if platform == "LINUX":
        if host == "LINUX":
            return True, ""
        return False, "LINUX 目标需要在 Linux 主机上编译"
    if platform == "ANDROID":
        if ctx.get("ndk"):
            return True, ""
        return False, "缺少 NDK 路径（--ndk / ANDROID_NDK_HOME / 交互提供）"
    if platform == "OPHM":
        if ctx.get("ohos"):
            return True, ""
        return False, "缺少 OpenHarmony (OHOS) SDK 路径（--ohos-sdk / OHOS_SDK / 交互提供）"
    if platform == "IOS":
        if host != "OSX":
            return False, "IOS 必须在 macOS 上编译（当前主机: %s）" % host
        if not find_tool("clang++") and not find_tool("xcrun"):
            return False, "macOS 上未找到 clang++ / xcrun（需要 Xcode Command Line Tools）"
        return True, ""
    if platform == "OSX":
        if host != "OSX":
            return False, "OSX 必须在 macOS 上编译（当前主机: %s）" % host
        if not find_tool("clang++"):
            return False, "macOS 上未找到 clang++（需要 Xcode Command Line Tools）"
        return True, ""
    return False, "未知平台: %s" % platform


# ---------------------------------------------------------------------------
# 编译命令构造（直接调用编译器，不依赖 CMake）
# ---------------------------------------------------------------------------
def compile_cmd(platform, mode, arch, ctx, args):
    """返回 (list 编译命令模板, str ar 命令, is_msvc)。
    优化/调试参数由调用方（build_one）按 mode 追加，统一在各平台分支末尾处理。"""
    common_defs = ["-DTRACY_ENABLE=1", "-DTRACY_FIBERS=1", "-DTRACY_DELAYED_INIT=1"]
    opt = ["-O2", "-DNDEBUG"] if mode == "release" else ["-O0", "-g"]

    if platform == "WINDOWS":
        # 工具链选择：默认 mingw（与 cjc 的 lld mingw ABI 匹配，CRT 符号天然互补）；
        # --toolchain msvc 时用 MSVC（注意：MSVC 静态库含 MSVC CRT 专属符号，
        # cjc 的 mingw 链接器无法解析 operator delete/__dyn_tls_init 等，仅用于独立 C++ 场景）
        forced = getattr(args, "toolchain", None)
        tc_mingw = probe_mingw(arch, ctx.get("mingw"))
        msvc = probe_msvc(arch)
        if forced == "msvc" or (not tc_mingw and msvc):
            if not msvc:
                raise RuntimeError("未找到 MSVC 工具链（vswhere/cl.exe）")
            cl, lib, _link, _root, _vcargs = msvc
            defs = ["-DTRACY_ENABLE", "-DTRACY_FIBERS"]
            flags = ["/std:c++17", "/Zc:__cplusplus",
                     "/Zi" if mode != "release" else "/DNDEBUG",
                     "/MD" if mode == "release" else "/MDd",
                     "/O2" if mode == "release" else "/Od"]
            return [cl] + flags + defs, lib, True
        if tc_mingw:
            gxx, ar, kind = tc_mingw
            base = ["-std=c++17", "-fno-omit-frame-pointer"]
            if kind == "gcc":
                # mingw-w64 GNU g++：POSIX 线程模型 TLS 支持（Tracy 压缩线程依赖）+
                # C++ 运行时静态自包含；-mstackrealign 保证 SSE 对齐
                base += ["-mthreads", "-mstackrealign",
                         "-static-libstdc++", "-static-libgcc"]
            else:
                # llvm-mingw（clang 后端）：不认 gcc 专属参数（-mthreads /
                # -static-libstdc++ / gcc 风格 -arch）；MSVC 兼容模式已含
                # __declspec(thread) TLS 与 unwind，无需额外线程参数
                base += ["-mstackrealign"]
            # 注意：不要用 gcc 风格 -arch aarch64（Apple clang 专属语法），
            # llvm-mingw / mingw-w64 均通过编译器 triple 前缀决定目标架构
            if arch == "arm64":
                base += ["-D_WIN32_WINNT=0x0601"]
                if kind == "clang":
                    # Tracy 的 Windows-ARM64 计时路径依赖 MSVC 专属内建
                    # _ReadStatusReg（TracyProfiler.hpp TRACY_HAS_CNTVCT 分支），
                    # clang（llvm-mingw）无此内建 → 编译失败。取消 _M_ARM64 宏
                    # 让 Tracy 走 TRACY_TIMER_FALLBACK（chrono）时钟；
                    # _M_ARM64 的其余使用（rpmalloc/lz4）均有 _MSC_VER 守卫，不受影响。
                    base += ["-U_M_ARM64"]
            return [gxx] + base + opt + common_defs, ar, False
        raise RuntimeError("未找到可用的 Windows 工具链")

    if platform == "LINUX":
        clang = find_tool("clang++") or find_tool("g++")
        flags = ["-std=c++17", "-fno-omit-frame-pointer", "-fPIC", "-pthread"]
        # CI-PATCH: find_tool 返回字符串，必须包成 [clang] 再拼列表——
        # 直接 clang + flags 抛 'can only concatenate str (not "list")
        # to str'（linux arm64 job 实测）。与 ANDROID/OPHM 分支的
        # [cxx] + flags 写法对齐。
        return [clang] + flags + opt + common_defs, "ar", False

    if platform == "ANDROID":
        ndk = ctx["ndk"]
        cxx = ndk_triplet_tool(arch, ndk)
        if not cxx:
            raise RuntimeError("NDK 中未找到 clang++: %s" % ndk)
        api = args.android_api
        triple = "aarch64-linux-android" if arch == "arm64" else "x86_64-linux-android"
        flags = ["-std=c++17", "-fno-omit-frame-pointer", "-fPIC",
                 "--target=%s%d" % (triple, api),
                 "-DANDROID", "-D__ANDROID_API__=%d" % api]
        ar = os.path.join(os.path.dirname(cxx), "llvm-ar" + exe_suffix())
        return [cxx] + flags + common_defs + ["-O2" if mode == "release" else "-O0"], ar, False

    if platform == "OPHM":
        sdk = ctx["ohos"]
        cxx = ohos_clang(arch, sdk)
        if not cxx:
            raise RuntimeError("OHOS SDK 中未找到 clang++: %s" % sdk)
        triple = "aarch64-linux-ohos" if arch == "arm64" else "x86_64-linux-ohos"
        flags = ["-std=c++17", "-fno-omit-frame-pointer", "-fPIC",
                 "--target=%s" % triple,
                 "--sysroot=%s" % os.path.join(sdk, "sysroot"),
                 "-D_OHOS_", "-D__MUSL__",
                 # OHOS 原生平台宏：Tracy 上游已加入 __OHOS__ 分支
                 # （deviceinfo NDK 取设备信息、program_invocation_* 取进程名、
                 #   跳过 musl 未实现的 pthread_setcancelstate）
                 "-D__OHOS__"]
        ar = os.path.join(os.path.dirname(cxx), "llvm-ar" + exe_suffix())
        return [cxx] + flags + common_defs + ["-O2" if mode == "release" else "-O0"], ar, False

    if platform == "IOS":
        # CI-PATCH: 对齐 OSX 分支——按架构选择 SDK（模拟器必须用
        # iphonesimulator，硬编码 iphoneos 会让 x86_64 模拟器构建
        # 产出设备架构对象）；isysroot 在 Python 侧解析（macOS runner
        # 的裸 clang 不继承 SDKROOT）。
        sdk = "iphoneos" if arch == "arm64" else "iphonesimulator"
        flags = ["-std=c++17", "-fno-omit-frame-pointer", "-fPIC",
                 "-arch", "arm64" if arch == "arm64" else "x86_64",
                 "-miphoneos-version-min=%s" % args.ios_deploy_target,
                 "-isysroot"]
        xcrun = find_tool("xcrun")
        if xcrun:
            sdk_path = subprocess.check_output(
                [xcrun, "--sdk", sdk, "--show-sdk-path"],
                universal_newlines=True).strip()
            return (["xcrun", "-sdk", sdk, "clang++"] + flags + [sdk_path]
                    + opt + common_defs, "ar", False)
        sdk_path = subprocess.check_output(
            ["xcodebuild", "-sdk", sdk, "-version", "Path"],
            universal_newlines=True).strip().splitlines()[-1]
        return (["clang++"] + flags + [sdk_path] + opt + common_defs, "ar", False)

    if platform == "OSX":
        flags = ["-std=c++17", "-fno-omit-frame-pointer", "-fPIC",
                 "-arch", "arm64" if arch == "arm64" else "x86_64",
                 "-mmacosx-version-min=%s" % args.macos_deploy_target]
        if find_tool("xcrun"):
            return (["xcrun", "clang++"] + flags + ["-O2" if mode == "release" else "-O0"],
                    "ar", False)
        return (["clang++"] + flags + ["-O2" if mode == "release" else "-O0"], "ar", False)

    raise RuntimeError("未知平台: %s" % platform)


# ---------------------------------------------------------------------------
# 编译单个组合
# ---------------------------------------------------------------------------

def strip_msvc_defaultlibs(obj_path):
    """剥除 .obj 中 MSVC CRT/C++ 运行时的 /DEFAULTLIB 指令（libcpmt/libcmt/oldnames 等）。
    仓颉 cjc 用 lld(mingw) 链接，这些库不存在；C++ 运行时由仓颉侧 libstdc++ 提供。
    等长替换不破坏 COFF 结构。"""
    data = open(obj_path, "rb").read()
    total = 0
    for name in (b"libcpmt", b"libcmt", b"msvcprt", b"msvcrt", b"oldnames"):
        for pat in (b'/DEFAULTLIB:"' + name + b'" ',
                    b'/DEFAULTLIB:"' + name + b'.lib" '):
            n = len(pat)
            cnt = data.count(pat)
            if cnt:
                data = data.replace(pat, b" " * n)
                total += cnt
    if total:
        open(obj_path, "wb").write(data)
    return total


def run_logged(cmd, env=None, log_path=None):
    """执行命令，实时回显并追加写入日志（格式对齐 bgfx/build.py run()）。
    返回退出码。"""
    try:
        proc = subprocess.Popen(
            cmd, env=env,
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

    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write("$ %s\n" % " ".join(cmd))
            f.writelines(lines)
            f.write("\n")
    return rc


def build_one(platform, mode, arch, ctx, args, log_path):
    tag = "%s_%s_%s" % (platform.lower(), mode, arch)
    obj = os.path.join(OUTPUT_DIR, "obj", tag, "TracyClient.obj")
    # 库产物放组合目录（语义对齐 bgfx：output/build-<platform>-<arch>-<mode>/lib/）
    build_dir = os.path.join(OUTPUT_DIR, "build-%s-%s-%s" % (platform.lower(), arch, mode))
    lib_out = os.path.join(build_dir, "lib")
    os.makedirs(os.path.dirname(obj), exist_ok=True)
    os.makedirs(lib_out, exist_ok=True)

    cxx_cmd, ar_cmd, is_msvc = compile_cmd(platform, mode, arch, ctx, args)

    # MSVC：vcvars 环境注入（INCLUDE/LIB，按目标架构选择 vcvarsall 参数）
    env = None
    if is_msvc:
        _cl, _lib, _link, vs_root, vcargs = probe_msvc(arch)
        env = msvc_env(vs_root, vcargs) or os.environ.copy()

    # 对象编译
    cmd = list(cxx_cmd)
    if is_msvc:
        cmd += ["/c", TRACY_SRC, "/I" + TRACY_INC, "/Fo" + obj]
    else:
        cmd += ["-c", TRACY_SRC, "-I" + TRACY_INC, "-o", obj]
    print("  [CC] %s" % " ".join(cmd))
    if run_logged(cmd, env, log_path) != 0:
        print("  [FAIL] 对象编译失败，日志: %s" % log_path)
        return False
    # MSVC 产物：剥除 /DEFAULTLIB 指令（cjc lld-mingw 链接兼容）
    if is_msvc:
        strip_msvc_defaultlibs(obj)

    # 归档：MSVC 先出 .lib 再复制为 .a（打包压缩语义：仓颉侧统一 .a 命名）
    lib_c = ("tracycd.lib" if mode == "debug" else "tracyc.lib") if is_msvc \
        else ("libtracycd.a" if mode == "debug" else "libtracyc.a")
    lib_file = os.path.join(lib_out, lib_c)
    if is_msvc:
        ar_list = [ar_cmd, "/nologo", "/OUT:" + lib_file, obj]
    else:
        if os.path.exists(lib_file):
            os.remove(lib_file)
        ar_list = [ar_cmd, "rcs", lib_file, obj]
    print("  [AR] %s" % " ".join(ar_list))
    if run_logged(ar_list, env, log_path) != 0:
        print("  [FAIL] 归档失败，日志: %s" % log_path)
        return False

    # MSVC 产物 .lib → .a（复制为仓颉侧链接命名，保留 .lib 副本）
    if is_msvc:
        lib_a = os.path.join(lib_out,
                             "libtracycd.a" if mode == "debug" else "libtracyc.a")
        shutil.copyfile(lib_file, lib_a)
        print("  [OK] %s (from %s)" % (lib_a, lib_c))
    else:
        print("  [OK] %s" % lib_file)
    return True


# ---------------------------------------------------------------------------
# 打包：把 tracy/public 头文件 + 静态库打成规范命名 zip（格式对齐 bgfx/build.py）
# ---------------------------------------------------------------------------
def package(platform, mode, arch, toolchain, dist_dir, lib_file):
    """lib_file: build_one 产出的静态库路径（可能为 None 表示未部署）。
    zip 命名: tracy4cj-<platform>-<arch>-<mode>-<toolchain>.zip
      include/ = tracy/public 全部头文件
      lib/     = 静态库（.a 优先，MSVC 场景附 .lib）"""
    name = "tracy4cj-%s-%s-%s-%s" % (platform.lower(), arch, mode, toolchain)
    zip_path = os.path.join(dist_dir, name + ".zip")

    if not lib_file or not os.path.isfile(lib_file):
        print("  [WARN] 未找到库产物，跳过打包: %s" % lib_file)
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件集合（tracy/public/**：TracyC.h + client/ + common/ + tracy/）
        if os.path.isdir(TRACY_PUB):
            for root, _dirs, files in os.walk(TRACY_PUB):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, TRACY_PUB)
                    z.write(full, os.path.join(name, "include", rel))
        # 静态库（.a 优先；MSVC 场景同一目录下 .lib 与 .a 均打包）
        lib_dir = os.path.dirname(lib_file)
        for f in sorted(os.listdir(lib_dir)):
            if f.startswith("libtracyc") and (f.endswith(".a") or f.endswith(".lib")):
                z.write(os.path.join(lib_dir, f), os.path.join(name, "lib", f))
    return zip_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    libs_wanted = parse_libs_arg(args.libs, _ALLOWED_LIBS, "tracy")
    if "tracy" not in libs_wanted:
        print("[tracy] --libs 未包含 tracy，整组跳过")
        return
    set_batch_flag(args.batch)

    host = detect_host()
    if not os.path.isfile(TRACY_SRC):
        print("[ERROR] 未找到 TracyClient.cpp: %s" % TRACY_SRC)
        return 1
    if not os.path.isdir(TRACY_INC):
        print("[ERROR] 未找到头文件目录: %s" % TRACY_INC)
        return 1

    if args.clean:
        for d in (OUTPUT_DIR, args.dist):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    print("=" * 60)
    print("  tracy4cj 全平台交叉编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  源文件:   %s" % TRACY_SRC)
    print("  产物目录: %s" % os.path.abspath(args.dist))
    print("=" * 60)

    ctx = {
        "ndk": None,
        "ohos": None,
        "mingw": resolve_mingw(args),
    }

    platforms = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    modes = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    arches = [a.strip().lower() for a in args.arches.split(",") if a.strip()]

    invalid = [p for p in platforms if p not in ALL_PLATFORMS]
    for p in invalid:
        print("  [WARN] 未知平台 %s，忽略（可选: %s）" % (p, ",".join(ALL_PLATFORMS)))
    platforms = [p for p in platforms if p in ALL_PLATFORMS]

    # 预解析 SDK（仅在需要时；命令行 > 环境变量 > 交互询问）
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")
    if "OPHM" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OPHM 平台因缺少 OHOS SDK 路径被跳过")

    dist_dir = os.path.abspath(args.dist)
    results = []   # (name, status, note)
    any_failed = False

    for platform in platforms:
        can, why = can_build(platform, host, ctx)
        if not can:
            print("\n[SKIP] %s：%s" % (platform, why))
            results.append((platform, "skip", why))
            continue
        print("\n===== 平台 %s（%s 主机）=====" % (platform, host))

        for mode in modes:
            for arch in arches:
                combo_name = "tracy4cj-%s-%s-%s" % (platform.lower(), arch, mode)
                print("\n----- 组合 %s -----" % combo_name)
                log_path = os.path.join(dist_dir, "logs", combo_name + ".log")
                try:
                    success = build_one(platform, mode, arch, ctx, args, log_path)
                except Exception as e:
                    print("  [FAIL] %s" % e)
                    success = False

                if not success:
                    any_failed = True
                    results.append((combo_name, "fail", "编译失败，日志: %s" % log_path))
                    if args.stop_on_error:
                        print("\n[STOP] --stop-on-error 触发，停止后续编译")
                        _summary(results)
                        return 1
                    continue

                # 工具链标识（zip 命名与汇总用）
                if platform == "WINDOWS":
                    tc = "msvc" if getattr(args, "toolchain", None) == "msvc" else "mingw"
                else:
                    tc = platform.lower()

                # 库产物在组合目录 output/build-<platform>-<arch>-<mode>/lib/；
                # 打包 zip（--skip-package 跳过）
                lib_file = os.path.join(
                    OUTPUT_DIR, "build-%s-%s-%s" % (platform.lower(), arch, mode), "lib",
                    ("libtracycd.a" if mode == "debug" else "libtracyc.a"))
                if args.skip_package:
                    print("  [OK] %s 编译成功（--skip-package 不打包）" % combo_name)
                    results.append((combo_name, "ok", "编译成功"))
                else:
                    zpath = package(platform, mode, arch, tc, dist_dir, lib_file)
                    if zpath:
                        print("  [OK] %s 编译并打包: %s" % (combo_name, zpath))
                        results.append((combo_name, "ok", "zip: " + zpath))
                    else:
                        print("  [OK] %s 编译成功，但无产物可打包" % combo_name)
                        results.append((combo_name, "ok", "编译成功，未打包"))

    _summary(results)
    return 1 if any_failed else 0


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
        print("  %s %-44s %s" % (mark, name, note))
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
