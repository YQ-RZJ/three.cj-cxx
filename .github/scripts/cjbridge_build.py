#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
requireCJLib 全平台自动交叉编译 + 打包脚本
==========================================
同时编译三个子项目：
  - requireCJLib     （C FFI 变体，产物 librequirecj_ffi）
  - requireCJLib-ark （NAPI 变体，产物 librequirecj_napi）
  - dlbridge         （动态库加载桥，产物 libdlbridge）

  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a
  - 平台:   WINDOWS LINUX ANDROID OPHM IOS OSX
  - 工具链: msvc / mingw / ndk / ohos / xcode / native
  - 库类型: static / shared

说明：
  OPHM = OpenHarmony / HarmonyOS：优先使用 DevEco NDK 自带的
  ohos.toolchain.cmake；若无则退回 clang --target=*-linux-ohos
  --sysroot=<sdk>/sysroot 的交叉编译方式。

  requireCJLib-ark (NAPI 变体) 需要 OHOS NDK 的 node_api.h 头文件，
  仅在 OPHM 平台编译时有意义；其他平台仅编译 requireCJLib (C FFI 变体)。

行为约定：
  1. 无参运行时尝试编译所有"当前能编译"的平台；
  2. WINDOWS 主机优先 msvc，失败回退 mingw；
  3. LINUX 使用本机原生编译器（clang 优先）；
  4. ANDROID / OPHM 需要 NDK 路径（命令行 > 环境变量 > 交互询问）；
  5. IOS / OSX 必须在 macOS 上编译。

用法示例：
  python build.py                                  # 尝试编译所有可编译平台
  python build.py --platforms OPHM                 # 只编 OpenHarmony
  python build.py --platforms ANDROID,WINDOWS      # 只编指定平台
  python build.py --platforms ANDROID --ndk D:/ndk
  python build.py --platforms OPHM --ohos-sdk D:/OpenHarmony/native
  python build.py --modes release --arches x86_64
  python build.py --libtype shared                 # 只编动态库
  python build.py --batch                          # 非交互（不询问，缺 SDK 即跳过）
  python build.py --cj-runtime-lib C:/venv/Cangjie/runtime/lib/windows_x86_64_cjnative
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
_ALLOWED_LIBS = ['ffi', 'napi', 'dlbridge']


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
OUTPUT_DIR   = os.path.join(SCRIPT_DIR, "output")          # cmake 构建/安装产物根目录
DIST_DIR     = os.path.join(SCRIPT_DIR, "dist")            # zip / 日志输出目录
LOG_DIR      = os.path.join(DIST_DIR, "logs")
LIBS_DIR     = os.path.join(SCRIPT_DIR, "libs")            # 仓颉侧链接用的库输出目录

# 三个子项目的 CMakeLists.txt 所在目录
# CI-PATCH: 目录扁平化后，requireCJLib/dlbridge 直接位于 cxx 根（原嵌套布局已移平）
FFI_SRC_DIR      = os.path.join(SCRIPT_DIR, "requireCJLib")
NAPI_SRC_DIR     = os.path.join(SCRIPT_DIR, "requireCJLib-ark")
DLBRIDGE_SRC_DIR = os.path.join(SCRIPT_DIR, "dlbridge")

ALL_PLATFORMS = ["WINDOWS", "LINUX", "ANDROID", "OPHM", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# 交互询问时作为回车默认值的 NDK 路径
NDK_DEFAULT   = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"
OHOS_DEFAULT  = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"

LIB_EXTENSIONS    = (".a", ".lib", ".so", ".dll", ".dylib", ".bc", ".wasm")
HEADER_EXTENSIONS = (".h", ".hpp")


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


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="requireCJLib 全平台自动交叉编译 + 打包脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔，可选: " + ",".join(ALL_PLATFORMS)
                         + "（默认全部，OPHM=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单，逗号分隔: debug,release（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单，逗号分隔: x86_64,arm64-v8a（默认全部）")
    ap.add_argument("--libtype", default="static,shared",
                    help="库类型清单，逗号分隔: static,shared（默认两者都编）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / ANDROID_NDK_ROOT）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OPHM 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 工具链目录（也可用环境变量 MINGW / LLVM_MINGW）")
    ap.add_argument("--android-api", type=int, default=24,
                    help="Android 最低 API 级别（默认 24）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认 = CPU 核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--libs-dir", default=LIBS_DIR,
                    help="编译成功后把库文件复制到的目录（默认 libs/，仓颉侧链接用）")
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
                    help="强制指定 CMake 生成器（默认按平台自动选择）")
    ap.add_argument("--skip-napi", action="store_true",
                    help="跳过 requireCJLib-ark (NAPI 变体) 的编译")
    ap.add_argument("--skip-dlbridge", action="store_true",
                    help="跳过 dlbridge (动态库加载桥) 的编译")
    ap.add_argument("--cj-runtime-lib", default=None,
                    help="仓颉运行时库目录（用于动态库链接，如 C:/venv/Cangjie/runtime/lib/windows_x86_64_cjnative）")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序）：ffi,napi,dlbridge（默认=全量编译）")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def is_windows():
    return os.name == "nt"


def exe_suffix():
    return ".exe" if is_windows() else ""


def find_tool(name):
    p = shutil.which(name)
    return os.path.abspath(p) if p else None


def ask(prompt, default=None):
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


_BATCH_FLAG = False


def args_batch():
    return _BATCH_FLAG


def set_batch_flag(flag):
    global _BATCH_FLAG
    _BATCH_FLAG = flag


# ---------------------------------------------------------------------------
# SDK 路径解析
# ---------------------------------------------------------------------------
def resolve_ndk(args):
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
def probe_ndk_toolchain(ndk, host):
    tc = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
    if os.path.isfile(tc):
        return tc
    for root, _dirs, files in os.walk(os.path.join(ndk, "build")):
        if "android.toolchain.cmake" in files:
            return os.path.join(root, "android.toolchain.cmake")
    raise RuntimeError("无法在 NDK 中找到 android.toolchain.cmake: %s" % ndk)


def probe_ohos(sdk, arch):
    """
    探测 OpenHarmony NDK 工具链。返回 (toolchain_file 或 None, target)。
    优先使用 ohos.toolchain.cmake；否则返回 None 由调用方生成临时工具链文件。
    """
    # 常见路径：DevEco NDK 布局
    for rel in ("build/cmake/ohos.toolchain.cmake",
                "native/build/cmake/ohos.toolchain.cmake"):
        tc = os.path.join(sdk, rel)
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


def probe_mingw(arch, mingw_dir):
    exe = exe_suffix()
    if arch == "arm64-v8a":
        triples = ["aarch64-w64-mingw32-"]
    else:
        triples = ["x86_64-w64-mingw32-"]
        local = find_tool("gcc" + exe)
        if local and find_tool("g++" + exe) and find_tool("windres" + exe):
            return (local,
                    find_tool("g++" + exe),
                    find_tool("windres" + exe),
                    find_tool("ar" + exe) or os.path.join(os.path.dirname(local), "ar" + exe))
    for pre in triples:
        if mingw_dir and os.path.isdir(mingw_dir):
            bin_dir = os.path.join(mingw_dir, "bin")
            cand = os.path.join(bin_dir, pre + "gcc" + exe)
            if os.path.exists(cand):
                return (cand,
                        os.path.join(bin_dir, pre + "g++" + exe),
                        os.path.join(bin_dir, pre + "windres" + exe),
                        os.path.join(bin_dir, pre + "ar" + exe))
        gcc = find_tool(pre + "gcc" + exe)
        gxx = find_tool(pre + "g++" + exe)
        if gcc and gxx:
            rc = find_tool(pre + "windres" + exe)
            ar = find_tool(pre + "ar" + exe)
            return gcc, gxx, rc, ar
    return None


def probe_vs_generators(cmake_exe):
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


def vs_has_arm64():
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
                 "-property", "installationPath"],
                stderr=subprocess.DEVNULL, universal_newlines=True, errors="replace")
        except Exception:
            continue
        tools = os.path.join(out.strip(), "VC", "Tools", "MSVC")
        if not os.path.isdir(tools):
            return False
        for ver in os.listdir(tools):
            cl = os.path.join(tools, ver, "bin", "Hostx64", "arm64", "cl.exe")
            if os.path.isfile(cl):
                return True
        return False
    return False


def pick_ninja():
    return find_tool("ninja")


# ---------------------------------------------------------------------------
# 可编译性判定
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    if platform == "WINDOWS":
        if host == "WINDOWS":
            if ctx.get("vs_generators"):
                return True, ""
            tc = probe_mingw("x86_64", ctx.get("mingw"))
            if tc:
                return True, ""
            return False, "Windows 主机上未检测到 Visual Studio 或 mingw-w64 工具链"
        tc = probe_mingw("x86_64", ctx.get("mingw")) or probe_mingw("arm64-v8a", ctx.get("mingw"))
        if tc:
            return True, ""
        return False, "非 Windows 主机且未检测到 mingw-w64 交叉工具链"
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
        return False, "缺少 OpenHarmony (OHOS) NDK 路径（--ohos-sdk / OHOS_SDK / 交互提供）"
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
# CMake 生成器与配置
# ---------------------------------------------------------------------------
def toolchains_for(platform, host, libtype="shared", arch="x86_64", ctx=None):
    if platform == "WINDOWS" and host == "WINDOWS":
        if libtype == "static":
            return ["mingw", "msvc"]
        if arch == "arm64-v8a" and not vs_has_arm64():
            return ["mingw"]
        return ["msvc", "mingw"]
    return ["native"]


def cmake_generator(platform, toolchain, host, ctx, args):
    if args.generator:
        return args.generator
    if platform == "WINDOWS" and toolchain == "msvc":
        return (ctx.get("vs_generator")
                or ctx.get("vs_generators", ["Visual Studio 17 2022"])[0])
    if platform in ("IOS", "OSX"):
        return "Xcode"
    if pick_ninja():
        return "Ninja"
    return "Unix Makefiles" if not is_windows() else "MinGW Makefiles"


def toolchain_cfg(platform, arch, toolchain, host, ctx, args):
    cfg = []
    if platform == "WINDOWS":
        if toolchain == "msvc":
            arch_map = {"x86_64": "x64", "arm64-v8a": "ARM64"}
            cfg.append("-A" + arch_map.get(arch, "x64"))
        else:
            tc = probe_mingw(arch, ctx.get("mingw"))
            if tc is None:
                raise RuntimeError("缺少 %s 的 mingw-w64 工具链" % arch)
            cc, cxx, rc, ar = tc
            cc, cxx = cc.replace("\\", "/"), cxx.replace("\\", "/")
            cfg += ["-DCMAKE_C_COMPILER=" + cc, "-DCMAKE_CXX_COMPILER=" + cxx]
            if host != "WINDOWS":
                cfg.append("-DCMAKE_SYSTEM_NAME=Windows")
            if rc:
                cfg.append("-DCMAKE_RC_COMPILER=" + rc.replace("\\", "/"))
            if ar:
                cfg.append("-DCMAKE_AR=" + ar.replace("\\", "/"))
            if host != "WINDOWS":
                cfg += [
                    "-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER",
                    "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY",
                    "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY",
                ]

    elif platform == "ANDROID":
        tc_file = probe_ndk_toolchain(ctx["ndk"], host)
        abi = arch
        cfg += [
            "-DCMAKE_TOOLCHAIN_FILE=" + tc_file,
            "-DANDROID_ABI=" + abi,
            "-DANDROID_PLATFORM=android-%d" % args.android_api,
            "-DANDROID_STL=c++_static",
            "-DANDROID_LD=lld",
        ]

    elif platform == "OPHM":
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

    elif platform == "IOS":
        cfg += [
            "-DCMAKE_SYSTEM_NAME=iOS",
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
        ]

    elif platform == "OSX":
        cfg += [
            "-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64-v8a" else "x86_64"),
        ]
    return cfg


def cmake_config(platform, mode, arch, libtype, toolchain, host, ctx, args):
    gen = cmake_generator(platform, toolchain, host, ctx, args)
    is_multi = gen.startswith("Visual Studio") or gen == "Xcode"
    build_type = mode.capitalize()

    cfg = ["-G", gen]
    if not is_multi:
        cfg.append("-DCMAKE_BUILD_TYPE=" + build_type)

    # 库类型选项
    cfg += [
        "-DREQUIRECJ_FFI_SHARED=" + ("ON" if libtype == "shared" else "OFF"),
        "-DREQUIRECJ_NAPI_SHARED=" + ("ON" if libtype == "shared" else "OFF"),
        "-DDLBRIDGE_SHARED=" + ("ON" if libtype == "shared" else "OFF"),
    ]

    # OHOS NDK 路径（NAPI 变体需要 node_api.h）
    if platform == "OPHM" and ctx.get("ohos"):
        cfg.append("-DOHOS_NDK=" + ctx["ohos"].replace("\\", "/"))

    # 仓颉运行时库目录（动态库链接时需要）
    if args.cj_runtime_lib:
        cfg.append("-DCJ_RUNTIME_LIB_DIR=" + args.cj_runtime_lib.replace("\\", "/"))

    cfg += toolchain_cfg(platform, arch, toolchain, host, ctx, args)
    return cfg, is_multi


# ---------------------------------------------------------------------------
# 命令执行
# ---------------------------------------------------------------------------
def run(cmd, cwd, env=None, log=None):
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
# 构建单个子项目
# ---------------------------------------------------------------------------
def build_subproject(src_dir, build_dir, stage_dir, cfg, is_multi, mode, env, log_path, jobs):
    cmake = cmake_path()

    config_cmd = [cmake, "-S", src_dir, "-B", build_dir] + cfg
    if run(config_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    build_cmd = [cmake, "--build", build_dir, "--parallel", str(jobs)]
    if is_multi:
        build_cmd += ["--config", mode.capitalize()]
    if run(build_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    install_cmd = [cmake, "--install", build_dir, "--prefix", stage_dir]
    if is_multi:
        install_cmd += ["--config", mode.capitalize()]
    if run(install_cmd, SCRIPT_DIR, env, log_path) != 0:
        return False

    return True


# ---------------------------------------------------------------------------
# 构建单个 (平台, 模式, 架构, 库类型, 工具链) 组合
# ---------------------------------------------------------------------------
def build_one(platform, mode, arch, libtype, toolchain, host, args, ctx, log_path):
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    base_build = os.path.join(OUTPUT_DIR, "build-" + tag)
    base_stage = os.path.join(OUTPUT_DIR, "stage-" + tag)

    for d in (base_build, base_stage):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    os.makedirs(base_build, exist_ok=True)

    cfg, is_multi = cmake_config(platform, mode, arch, libtype, toolchain, host, ctx, args)

    # CI-PATCH: 三个子项目的 CMakeLists 各自只消费自己的库类型选项，
    # 无差别全传会让 CMake 报 unused-cli 警告——按子项目剔除不相关选项。
    # 注意只剔除库类型选项本身，其它 -D（如 CMAKE_BUILD_TYPE）必须保留。
    _LIBTYPE_OPTS = ("REQUIRECJ_FFI_SHARED", "REQUIRECJ_NAPI_SHARED", "DLBRIDGE_SHARED")

    def cfg_for(*keep):
        drop = tuple("-D" + p + "=" for p in _LIBTYPE_OPTS if p not in keep)
        return [o for o in cfg if not o.startswith(drop)]

    cfg_ffi  = cfg_for("REQUIRECJ_FFI_SHARED")
    cfg_napi = cfg_for("REQUIRECJ_NAPI_SHARED")
    cfg_dlb  = cfg_for("DLBRIDGE_SHARED")
    env = os.environ.copy()
    if toolchain == "mingw" and ctx.get("mingw"):
        mbin = os.path.join(ctx["mingw"], "bin")
        if os.path.isdir(mbin):
            env["PATH"] = mbin + os.pathsep + env["PATH"]

    # CI-PATCH: --libs 选择性构建（默认全量）：ffi/napi/dlbridge 三段独立过滤
    # （napi 仅 OPHM 编译，不受 --libs 控制）
    if "ffi" not in libs_wanted:
        print("  [skip] requireCJLib (C FFI)（--libs 未包含）")
        return True
    # 1) 编译 requireCJLib (C FFI 变体)
    print("  [%s/%s/%s] 编译 requireCJLib (C FFI) ..." % (mode, arch, platform))
    ffi_build = os.path.join(base_build, "ffi")
    ffi_stage = os.path.join(base_stage, "ffi")
    if not build_subproject(FFI_SRC_DIR, ffi_build, ffi_stage,
                            cfg_ffi, is_multi, mode, env, log_path, args.jobs):
        return False

    # 2) 编译 requireCJLib-ark (NAPI 变体)
    #    NAPI 变体需要 OHOS NDK 的 node_api.h，仅 OPHM 平台编译
    if not args.skip_napi and platform == "OPHM":
        if "napi" not in libs_wanted:
            print("  [skip] requireCJLib-ark (NAPI)（--libs 未包含）")
        else:
            print("  [%s/%s/%s] 编译 requireCJLib-ark (NAPI) ..." % (mode, arch, platform))
            napi_build = os.path.join(base_build, "napi")
            napi_stage = os.path.join(base_stage, "napi")
            if not build_subproject(NAPI_SRC_DIR, napi_build, napi_stage,
                                    cfg_napi, is_multi, mode, env, log_path, args.jobs):
                return False

    # 3) 编译 dlbridge (动态库加载桥)
    if not args.skip_dlbridge:
        if "dlbridge" not in libs_wanted:
            print("  [skip] dlbridge（--libs 未包含）")
        else:
            print("  [%s/%s/%s] 编译 dlbridge ..." % (mode, arch, platform))
            dlb_build = os.path.join(base_build, "dlbridge")
            dlb_stage = os.path.join(base_stage, "dlbridge")
            if not build_subproject(DLBRIDGE_SRC_DIR, dlb_build, dlb_stage,
                                    cfg_dlb, is_multi, mode, env, log_path, args.jobs):
                return False

    return True


# ---------------------------------------------------------------------------
# 产物目录清理
# ---------------------------------------------------------------------------
def clean_output():
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        print("  已清空编译产物目录: %s" % OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 复制库文件到 libs/ 目录
# ---------------------------------------------------------------------------
def stage_dir_of(platform, mode, arch, libtype, toolchain):
    tag = "%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
    return os.path.join(OUTPUT_DIR, "stage-" + tag)


def copy_libs(stage_dir, libs_dir, subdir):
    if not os.path.isdir(stage_dir):
        print("  [WARN] 未找到安装产物目录 %s，跳过复制 libs" % stage_dir)
        return
    target = os.path.join(libs_dir, subdir)
    os.makedirs(target, exist_ok=True)
    copied = []
    for root, _dirs, files in os.walk(stage_dir):
        for f in files:
            low = f.lower()
            if low.endswith(LIB_EXTENSIONS):
                src = os.path.join(root, f)
                dst = os.path.join(target, f)
                shutil.copy2(src, dst)
                copied.append(dst)
    if copied:
        print("  [OK] 已复制 %d 个库文件到 %s:" % (len(copied), target))
        for c in copied:
            print("       - %s" % c)
    else:
        print("  [WARN] %s 下没有库文件，未复制" % stage_dir)


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, toolchain, dist_dir, args):
    name = "requireCJLib-%s-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype, toolchain)
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
                libs.append((full, rel))
    if not libs:
        print("  [WARN] %s 下没有库文件，跳过打包" % stage_dir)
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in headers:
            z.write(full, os.path.join(name, "include", rel))
        for full, rel in libs:
            z.write(full, os.path.join(name, "lib", rel))
    return zip_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    libs_wanted = parse_libs_arg(args.libs, _ALLOWED_LIBS, "cjbridge")
    set_batch_flag(args.batch)

    if args.clean:
        for d in (OUTPUT_DIR, DIST_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    cmake = cmake_path()
    host = detect_host()
    print("=" * 60)
    print("  requireCJLib 全平台交叉编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  C FFI 源码:   %s" % FFI_SRC_DIR)
    print("  NAPI 源码:    %s" % NAPI_SRC_DIR)
    print("  dlbridge 源码: %s" % DLBRIDGE_SRC_DIR)
    print("  OHOS SDK:    %s" % (args.ohos_sdk or "(auto-detect)"))
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  CJ RT Lib: %s" % (args.cj_runtime_lib or "(not set)"))
    print("  cmake:    %s" % cmake)
    if args.skip_napi:
        print("  [INFO] --skip-napi: 跳过 NAPI 变体编译")
    if args.skip_dlbridge:
        print("  [INFO] --skip-dlbridge: 跳过 dlbridge 编译")
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

    # 预解析各平台所需 SDK
    vs_gen = detect_vs_generator()
    ctx = {"ndk": None, "ohos": None, "mingw": resolve_mingw(args),
           "vs_generator": vs_gen,
           "vs_generators": probe_vs_generators(cmake)}
    if vs_gen:
        print("  检测到 Visual Studio: %s" % vs_gen)
    if ctx["mingw"]:
        print("  检测到 mingw-w64 工具链: %s" % ctx["mingw"])
    if not vs_has_arm64():
        print("  [INFO] 未检测到 Visual Studio ARM64 工具集（windows arm64 将优先使用 mingw）")
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")
    if "OPHM" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OPHM 平台因缺少 OHOS SDK 路径被跳过")

    dist_dir = os.path.abspath(args.dist)
    results = []
    any_failed = False

    for plat in platforms:
        ok, reason = can_build(plat, host, ctx)
        if not ok:
            print("\n[SKIP] %s: %s" % (plat, reason))
            results.append((plat, "skip", reason))
            continue
        print("\n===== 平台 %s（%s 主机）=====" % (plat, host))

        for mode in modes:
            for arch in arches:
                for libtype in libtypes:
                    combo_name = "requireCJLib-%s-%s-%s-%s" % (plat.lower(), arch, mode, libtype)
                    clean_output()
                    toolchains = toolchains_for(plat, host, libtype, arch, ctx)
                    done = False
                    for tc in toolchains:
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo_name, tc))
                        log_path = os.path.join(LOG_DIR, combo_name + "-" + tc + ".log")
                        try:
                            build_ok = build_one(plat, mode, arch, libtype, tc, host, args, ctx, log_path)
                        except RuntimeError as e:
                            print("  [WARN] %s / %s 工具链不可用: %s" % (combo_name, tc, e))
                            build_ok = False
                        if build_ok:
                            if not args.no_libs_copy:
                                copy_libs(stage_dir_of(plat, mode, arch, libtype, tc),
                                          args.libs_dir,
                                          "%s-%s" % (plat.lower(), arch))
                            if args.skip_package:
                                print("  [OK] %s 编译成功（--skip-package 不打包）" % combo_name)
                                results.append((combo_name + "-" + tc, "ok", "编译成功"))
                            else:
                                zpath = package(plat, mode, arch, libtype, tc, dist_dir, args)
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
