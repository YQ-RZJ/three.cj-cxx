#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sdl3 全平台自动交叉编译 + 打包脚本
==========================================
编译 SDL3 (v3.5.0, 源码位于 cxx/SDL) 并支持输出为
不同系统 / 不同芯片架构 / release|debug 的静态 / 动态库。

矩阵:
  平台   LINUX / WINDOWS / OHOS / ANDROID / MACOS / IOS
  架构   x86_64 / arm64 / arm / x86   (按平台可选)
  模式   debug / release
  库类型 static / shared

用法示例:
  python build.py                                     # 全平台排列组合
  python build.py --platforms LINUX,WINDOWS          # 只编指定平台
  python build.py --platforms OHOS --ohos-sdk <path> # 指定 OHOS NDK
  python build.py --modes release --arches x86_64
  python build.py --libtype static                   # 只编静态库
  python build.py --batch                            # 非交互(缺 SDK 即跳过)

参考: bgfx4cj-tcp/cxx/build.py 的跨平台编译打包约定。
本脚本改用 CMake 驱动(而非 xmake)，以复用 SDL3 原生构建系统。
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

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # CI 扁平化布局：脚本在 .github/scripts/ 下，cxx 根即项目根
# CI-PATCH: 原 GROUP_DIR 已扁平化删除，以下路径均相对 cxx 根解析
GROUP_DIR = os.path.dirname(os.path.abspath(__file__))  # 仅供 --dist 默认值等 CI 侧用途
SDL_DIR    = os.path.join(SCRIPT_DIR, "SDL")   # SDL3 源码根目录 (cxx/SDL)
DIST_DIR   = os.path.join(SCRIPT_DIR, "dist")
LOG_DIR    = os.path.join(DIST_DIR, "logs")
BUILD_ROOT = os.path.join(SCRIPT_DIR, "build") # 各平台组合构建目录根
PKG_PREFIX = "sdl3"                            # 打包 zip 前缀

ALL_PLATFORMS = ["LINUX", "WINDOWS", "OHOS", "ANDROID", "MACOS", "IOS"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64"]
ALL_LIBTYPES  = ["static", "shared"]

# 平台 -> 支持的架构
PLATFORM_ARCHES = {
    "LINUX":   ["x86_64", "arm64"],
    "WINDOWS": ["x86_64", "arm64"],
    "OHOS":    ["arm64", "x86_64"],
    "ANDROID": ["arm64", "x86_64"],
    "MACOS":   ["arm64", "x86_64"],
    "IOS":     ["arm64", "x86_64"],
}

# OHOS NDK 默认路径 (本机 OpenHarmony SDK)
OHOS_SDK_DEFAULT = r"D:\Venv\OpenHarmonySDK\23\native"

LIB_EXTENSIONS = (".a", ".lib", ".so", ".dll", ".dylib", ".bc", ".wasm")


# ---------------------------------------------------------------------------
# 主机平台检测
# ---------------------------------------------------------------------------
def detect_host():
    s = _platform.system().lower()
    if "windows" in s:
        return "WINDOWS"
    if "darwin" in s:
        return "MACOS"
    if "linux" in s:
        return "LINUX"
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
        description="sdl3 全平台自动交叉编译 + 打包脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔 (默认全部)")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单: debug,release (默认全部)")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单: x86_64,arm64 (默认全部)")
    ap.add_argument("--libtype", default=",".join(ALL_LIBTYPES),
                    help="库类型清单: static,shared (默认全部)")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径 (或环境变量 OHOS_SDK)")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径 (或环境变量 ANDROID_NDK_HOME)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数 (默认 = CPU 核数)")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录")
    ap.add_argument("--source", default=SDL_DIR,
                    help="SDL3 源码根目录 (默认 cxx/SDL)")
    ap.add_argument("--sdl-opt", action="append", default=[],
                    metavar="NAME=VALUE",
                    help="额外传给 cmake 的 -D 选项 (可多次指定, 覆盖默认裁剪)")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 build/ 与 dist/")
    ap.add_argument("--batch", "--no-interactive", dest="batch",
                    action="store_true",
                    help="非交互模式: 不询问 SDK 路径, 缺 SDK 的平台直接跳过")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="任一组合编译失败即停止 (默认继续其余组合)")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译, 不打包 zip")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def is_windows():
    return os.name == "nt"


def find_tool(name):
    p = shutil.which(name)
    return os.path.abspath(p) if p else None


_BATCH_FLAG = False


def args_batch():
    return _BATCH_FLAG


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


# ---------------------------------------------------------------------------
# SDK 路径解析
# ---------------------------------------------------------------------------
def resolve_ohos_sdk(args):
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


def resolve_ndk(args):
    v = (args.ndk
         or os.environ.get("ANDROID_NDK_HOME")
         or os.environ.get("ANDROID_NDK_ROOT"))
    if not v:
        v = ask("请输入 Android NDK 路径")
    if not v:
        return None
    if not os.path.isdir(v):
        print("  [ERROR] NDK 路径不存在: %s" % v)
        return None
    return os.path.normpath(v)


# ---------------------------------------------------------------------------
# OHOS 工具链探测
# ---------------------------------------------------------------------------
def probe_ohos(sdk, arch):
    """返回 (cc, cxx, sysroot, target)"""
    exe = ".exe" if is_windows() else ""
    bin_dir = os.path.join(sdk, "llvm", "bin")
    cc  = os.path.join(bin_dir, "clang" + exe)
    cxx = os.path.join(bin_dir, "clang++" + exe)
    sysroot = os.path.join(sdk, "sysroot")
    if not (os.path.isfile(cc) and os.path.isfile(cxx) and os.path.isdir(sysroot)):
        raise RuntimeError("OHOS SDK 结构不完整: %s" % sdk)
    target = "aarch64-linux-ohos" if arch == "arm64" else "x86_64-linux-ohos"
    return cc, cxx, sysroot, target


# ---------------------------------------------------------------------------
# CMake 工具查找
# ---------------------------------------------------------------------------
def find_cmake():
    p = find_tool("cmake")
    if not p:
        print("[ERROR] 未找到 cmake，请先安装并加入 PATH")
        sys.exit(1)
    return p


def find_ninja():
    return find_tool("ninja")


def generator_args():
    """返回 CMake 生成器参数: 优先 Ninja, 回退 MinGW Makefiles (Windows)"""
    ninja = find_ninja()
    if ninja:
        return ["-G", "Ninja"]
    if is_windows():
        mk = find_tool("mingw32-make")
        if mk:
            return ["-G", "MinGW Makefiles", "-DCMAKE_MAKE_PROGRAM=" + mk]
    return []


def _vs_generator():
    """通过 vswhere 探测已安装的 Visual Studio, 返回 CMake 生成器名或 None"""
    vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if not os.path.isfile(vswhere):
        return None
    try:
        out = subprocess.check_output(
            [vswhere, "-latest", "-products", "*", "-property", "catalog_productLineVersion"],
            stderr=subprocess.DEVNULL).decode("utf-8", "replace").strip()
    except Exception:
        return None
    ver = out.split(".")[0] if out else ""
    if ver == "2022":
        return "Visual Studio 17 2022"
    if ver == "2019":
        return "Visual Studio 16 2019"
    if ver == "2017":
        return "Visual Studio 15 2017"
    return None


def toolchains_for(platform, host, libtype):
    """每个平台候选工具链（按优先级）。WINDOWS 主机上 static 优先 mingw, 回退 msvc。"""
    if platform == "WINDOWS" and host == "WINDOWS":
        if libtype == "static":
            return ["mingw", "msvc"]
        return ["mingw"]
    return ["default"]


# ---------------------------------------------------------------------------
# 构建: 为单个 (platform, mode, arch, libtype, toolchain) 组合生成 CMake 命令
# ---------------------------------------------------------------------------
def cmake_configure_args(platform, mode, arch, libtype, toolchain, host, ctx):
    """返回 CMake configure 阶段的参数列表 (不含 cmake 本身)"""
    args = [
        "-DCMAKE_BUILD_TYPE=" + ("Release" if mode == "release" else "Debug"),
    ]

    # SDL3 库类型: libtype -> SDL_SHARED / SDL_STATIC
    if libtype == "shared":
        args += ["-DSDL_SHARED=ON", "-DSDL_STATIC=OFF"]
    else:
        args += ["-DSDL_SHARED=OFF", "-DSDL_STATIC=ON"]

    # 功能裁剪默认值 (与 OHOS 迁移验证过的配置一致; 用 --sdl-opt 覆盖)
    args += [
        "-DSDL_TEST_LIBRARY=OFF",
        "-DSDL_AUDIO=OFF",
        "-DSDL_CAMERA=OFF",
        "-DSDL_RENDER=OFF",
        "-DSDL_GPU=OFF",
        "-DSDL_DIALOG=OFF",
        "-DSDL_TRAY=OFF",
        "-DSDL_NOTIFICATION=OFF",
        "-DSDL_OPENGLES=ON",
        "-DSDL_VULKAN=OFF",
    ]
    # 用户自定义 -D 覆盖 (最后出现者生效)
    args += ["-D" + o for o in ctx.get("sdl_opts", [])]

    # ---- OHOS: 官方 ohos.toolchain.cmake ----
    if platform == "OHOS":
        sdk = ctx.get("ohos")
        if not sdk:
            raise RuntimeError("OHOS 需要 OHOS SDK 路径")
        probe_ohos(sdk, arch)  # 校验 <sdk>/llvm/bin + <sdk>/sysroot
        tc = os.path.join(sdk, "build", "cmake", "ohos.toolchain.cmake")
        if not os.path.isfile(tc):
            raise RuntimeError("OHOS SDK 缺少 ohos.toolchain.cmake: %s" % tc)
        args += [
            "-DCMAKE_TOOLCHAIN_FILE=" + tc,
            "-DOHOS_ARCH=" + ("arm64-v8a" if arch == "arm64" else arch),
            # 静态链接 C++ 运行时（-static-libstdc++ → libc++_static.a）：
            # 实测（HUAWEI Mate 80 Pro, error.txt）设备上不存在 libc++_shared.so——
            # 所有 namespace（ndk/cj_*_sdk/cj_runtime/moduleNs_default）均 errno=2
            # ENOENT，导致 libSDL3.so 加载失败 → CJ-RUNTIME load cj library failed
            # → registerModule 未执行 → ArkTS 报 export name 缺失。
            # 参考项目 ohos_sdl2 虽用 -DOHOS_STL=c++_shared，但其 HAP 需携带
            # libc++_shared.so；我们按设备实测选择静态化，产物自包含，仅依赖
            # 系统平台库（EGL/GLESv3/hilog 等系统自带，无需打包），
            # 与 sdl4cj cjpm.toml 的 OHOS link-option（libc++_static.a）保持一致。
            "-DOHOS_STL=c++_static",
        ]

    # ---- ANDROID: NDK android.toolchain.cmake ----
    elif platform == "ANDROID":
        ndk = ctx.get("ndk")
        if not ndk:
            raise RuntimeError("ANDROID 需要 NDK 路径")
        tc = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
        if not os.path.isfile(tc):
            raise RuntimeError("NDK 缺少 android.toolchain.cmake: %s" % tc)
        args += [
            "-DCMAKE_TOOLCHAIN_FILE=" + tc,
            "-DANDROID_ABI=" + ("arm64-v8a" if arch == "arm64" else "x86_64"),
            "-DANDROID_PLATFORM=android-24",
        ]

    # ---- LINUX: 本机 clang/gcc ----
    elif platform == "LINUX":
        if host != "LINUX":
            raise RuntimeError("LINUX 目标需要在 Linux 主机上编译")
        cc = find_tool("clang") or find_tool("gcc") or "gcc"
        cxx = find_tool("clang++") or find_tool("g++") or "g++"
        args += ["-DCMAKE_C_COMPILER=" + cc, "-DCMAKE_CXX_COMPILER=" + cxx]

    # ---- WINDOWS: 本机 mingw (clang/gcc) 或 msvc ----
    elif platform == "WINDOWS":
        if host != "WINDOWS":
            raise RuntimeError("非 Windows 主机编译 WINDOWS 需要 mingw-w64 交叉工具链 (未配置)")
        if toolchain == "msvc":
            # MSVC: 使用 Visual Studio 多配置生成器, 不指定编译器
            gen = _vs_generator()
            if not gen:
                raise RuntimeError("未检测到 Visual Studio, 无法使用 msvc 工具链")
            args += ["-G", gen, "-A", ("x64" if arch == "x86_64" else "ARM64")]
            return args
        # mingw: 优先真正的 MinGW gcc (产出 .a)。
        # 注意: 不能优先 LLVM clang —— Windows 上 clang 默认目标为 MSVC ABI, 只会产出 .lib
        cc = (find_tool("x86_64-w64-mingw32-gcc")
              or find_tool("gcc")
              or find_tool("clang") or "gcc")
        cxx = (find_tool("x86_64-w64-mingw32-g++")
               or find_tool("g++")
               or find_tool("clang++") or "g++")
        args += ["-DCMAKE_C_COMPILER=" + cc, "-DCMAKE_CXX_COMPILER=" + cxx]

    # ---- MACOS / IOS: 需要 macOS 主机 (Xcode clang) ----
    elif platform in ("MACOS", "IOS"):
        if host != "MACOS":
            raise RuntimeError("%s 必须在 macOS 上编译" % platform)
        cc = find_tool("clang") or "clang"
        cxx = find_tool("clang++") or "clang++"
        args += ["-DCMAKE_C_COMPILER=" + cc, "-DCMAKE_CXX_COMPILER=" + cxx]
        if platform == "IOS":
            args += ["-DCMAKE_SYSTEM_NAME=iOS"]
            args += ["-DCMAKE_OSX_ARCHITECTURES=" + ("arm64" if arch == "arm64" else "x86_64")]
            if arch != "arm64":
                args += ["-DCMAKE_OSX_SYSROOT=iphonesimulator"]

    # Generator: 优先 Ninja, 回退 MinGW Makefiles (Windows)
    args += generator_args()
    return args


# ---------------------------------------------------------------------------
# 可编译性判定
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    """返回 (ok, reason)"""
    if platform == "LINUX":
        if host == "LINUX":
            return True, ""
        return False, "LINUX 目标需要在 Linux 主机上编译"
    if platform == "WINDOWS":
        if host == "WINDOWS":
            return True, ""
        return False, "WINDOWS 目标需要在 Windows 主机上编译 (未配置 mingw 交叉)"
    if platform == "OHOS":
        if ctx.get("ohos"):
            return True, ""
        return False, "缺少 OpenHarmony (OHOS) NDK 路径 (--ohos-sdk / OHOS_SDK)"
    if platform == "ANDROID":
        if ctx.get("ndk"):
            return True, ""
        return False, "缺少 Android NDK 路径 (--ndk / ANDROID_NDK_HOME)"
    if platform == "MACOS":
        if host != "MACOS":
            return False, "MACOS 必须在 macOS 上编译"
        return True, ""
    if platform == "IOS":
        if host != "MACOS":
            return False, "IOS 必须在 macOS 上编译"
        return True, ""
    return False, "未知平台: %s" % platform


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


# ---------------------------------------------------------------------------
# 打包: 头文件 + 库 -> 规范命名 zip
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, build_dir, dist_dir):
    name = "%s-%s-%s-%s-%s" % (PKG_PREFIX, platform.lower(), arch, mode, libtype)
    zip_path = os.path.join(dist_dir, name + ".zip")

    # 收集本组合构建目录下的库产物
    lib_files = []
    for root, _dirs, files in os.walk(build_dir):
        for f in files:
            if f.endswith(LIB_EXTENSIONS):
                lib_files.append(os.path.join(root, f))
    if not lib_files:
        print("  [WARN] 未找到库产物, 跳过打包")
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 头文件 (SDL/include/SDL3/*.h + SDL/include/build_config/*.h)
        include_root = os.path.join(SDL_DIR, "include")
        for sub in ("SDL3", "build_config"):
            d = os.path.join(include_root, sub)
            if os.path.isdir(d):
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        if f.endswith((".h", ".cmake")):
                            full = os.path.join(root, f)
                            rel = os.path.relpath(full, include_root)
                            z.write(full, os.path.join(name, "include", rel))
        # 库文件
        for lf in lib_files:
            rel = os.path.relpath(lf, build_dir)
            z.write(lf, os.path.join(name, "lib", rel))
            # SONAME 别名：若 .so 的 DT_SONAME 与文件名不同（如其他 UNIX 平台的
            # libSDL3.so → SONAME libSDL3.so.0），运行时按 SONAME 加载依赖，
            # 打包必须同时提供 SONAME 文件，否则 dlopen 报 "module not found"
            # （.a 静态链接无此问题，.so 动态链接必须带）。
            # 注意：OHOS 平台已在 CMakeLists.txt（SDL3-shared UNIX 分支）跳过
            # VERSION/SOVERSION，产物 SONAME 即文件名 libSDL3.so（无 .so.0），
            # 因此下面的条件判断自然不触发，无需重复打包同一文件。
            soname = _elf_soname(lf)
            if soname and soname != os.path.basename(lf):
                z.write(lf, os.path.join(name, "lib", soname))
    return zip_path


# ---------------------------------------------------------------------------
# ELF SONAME 解析（用于 .so 打包时补充 SONAME 别名文件）
# ---------------------------------------------------------------------------
def _elf_soname(path):
    """返回 ELF 动态库的 DT_SONAME；非 ELF 或解析失败返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        if head != b"\x7fELF":
            return None
        import subprocess
        import re as _re
        # 优先 readelf（Linux/OHOS NDK），回退 objdump（MinGW）：
        #   readelf -d <so> 输出: "Library soname: [libSDL3.so.0]"
        #   objdump -p <so> 输出: "SONAME               libSDL3.so.0"
        for tool, args in (("readelf", ["-d"]), ("objdump", ["-p"])):
            exe = find_tool(tool)
            if not exe:
                continue
            proc = subprocess.run([exe] + args + [path],
                                  capture_output=True, text=True, timeout=30)
            for line in proc.stdout.splitlines():
                if "SONAME" not in line and "soname" not in line:
                    continue
                m = _re.search(r"\[([^\]]+)\]", line)
                if m:
                    return m.group(1)
                parts = line.split("SONAME", 1)
                if len(parts) > 1:
                    name = parts[1].strip().lstrip(": ").strip()
                    if name:
                        return name
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    global _BATCH_FLAG
    args = parse_args()
    set_batch = args.batch
    _BATCH_FLAG = set_batch

    if args.clean:
        for d in (BUILD_ROOT, DIST_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("已清理: %s" % d)

    cmake = find_cmake()
    host = detect_host()
    print("=" * 60)
    print("  sdl3 全平台交叉编译 + 打包")
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

    # 校验
    invalid_p = [p for p in platforms if p not in ALL_PLATFORMS]
    for p in invalid_p:
        print("  [WARN] 未知平台 %s, 忽略 (可选: %s)" % (p, ",".join(ALL_PLATFORMS)))
    platforms = [p for p in platforms if p in ALL_PLATFORMS]

    for t in libtypes:
        if t not in ALL_LIBTYPES:
            print("  [WARN] 未知库类型 %s, 忽略" % t)
    libtypes = [t for t in libtypes if t in ALL_LIBTYPES]

    # 预解析 SDK
    ctx = {"ohos": None, "ndk": None, "sdl_opts": args.sdl_opt}
    if "OHOS" in platforms:
        ctx["ohos"] = resolve_ohos_sdk(args)
        if not ctx["ohos"]:
            print("  [WARN] OHOS 平台因缺少 SDK 路径被跳过")
    if "ANDROID" in platforms:
        ctx["ndk"] = resolve_ndk(args)
        if not ctx["ndk"]:
            print("  [WARN] ANDROID 平台因缺少 NDK 路径被跳过")

    dist_dir = os.path.abspath(args.dist)
    results = []
    any_failed = False

    for platform in platforms:
        ok, reason = can_build(platform, host, ctx)
        if not ok:
            print("\n[SKIP] %s: %s" % (platform, reason))
            results.append((platform, "skip", reason))
            continue
        print("\n===== 平台 %s (%s 主机) =====" % (platform, host))

        # 该平台支持的架构
        plat_arches = [a for a in arches if a in PLATFORM_ARCHES.get(platform, [])]
        if not plat_arches:
            print("  [WARN] 平台 %s 不支持任何选定架构 %s, 跳过" % (platform, arches))
            results.append((platform, "skip", "架构不匹配"))
            continue

        for mode in modes:
            for arch in plat_arches:
                for libtype in libtypes:
                    combo = "%s-%s-%s-%s-%s" % (PKG_PREFIX, platform.lower(), arch, mode, libtype)
                    build_dir = os.path.join(BUILD_ROOT,
                                             "%s-%s" % (platform.lower(), arch),
                                             mode, libtype)
                    toolchains = toolchains_for(platform, host, libtype)
                    done = False
                    for tc in toolchains:
                        combo_tc = combo + "-" + tc
                        log_path = os.path.join(LOG_DIR, combo_tc + ".log")
                        print("\n----- 组合 %s / toolchain=%s -----" % (combo, tc))

                        # 清空 build 目录 (避免上次残留)
                        if os.path.isdir(build_dir):
                            shutil.rmtree(build_dir, ignore_errors=True)
                        os.makedirs(build_dir, exist_ok=True)

                        ok = True
                        try:
                            cfg_args = cmake_configure_args(platform, mode, arch, libtype, tc, host, ctx)
                        except RuntimeError as e:
                            print("  [FAIL] %s/%s: %s" % (combo, tc, e))
                            ok = False

                        if ok:
                            print("  [1/3] 配置 %s/%s ..." % (combo, tc))
                            if run([cmake, "-B", build_dir, "-S", args.source] + cfg_args,
                                   SCRIPT_DIR, log=log_path) != 0:
                                print("  [FAIL] %s/%s 配置失败, 日志: %s" % (combo, tc, log_path))
                                ok = False

                        if ok:
                            print("  [2/3] 编译 %s/%s ..." % (combo, tc))
                            build_cmd = [cmake, "--build", build_dir, "-j", str(args.jobs)]
                            if tc == "msvc":
                                # Visual Studio 为多配置生成器, 需 --config 指定
                                build_cmd += ["--config", "Release" if mode == "release" else "Debug"]
                            if run(build_cmd, SCRIPT_DIR, log=log_path) != 0:
                                print("  [FAIL] %s/%s 编译失败, 日志: %s" % (combo, tc, log_path))
                                ok = False

                        if not ok:
                            if tc != toolchains[-1]:
                                print("  -> 回退工具链 %s ..." % toolchains[toolchains.index(tc) + 1])
                            continue

                        # Package
                        if args.skip_package:
                            print("  [OK] %s/%s 编译成功 (--skip-package 不打包)" % (combo, tc))
                            results.append((combo_tc, "ok", "编译成功"))
                        else:
                            print("  [3/3] 打包 %s/%s ..." % (combo, tc))
                            zpath = package(platform, mode, arch, libtype, build_dir, dist_dir)
                            if zpath:
                                print("  [OK] %s/%s 编译并打包: %s" % (combo, tc, zpath))
                                results.append((combo_tc, "ok", "zip: " + zpath))
                            else:
                                print("  [OK] %s/%s 编译成功, 但无产物可打包" % (combo, tc))
                                results.append((combo_tc, "ok", "编译成功, 未打包"))
                        done = True
                        break

                    if not done:
                        any_failed = True
                        results.append((combo, "fail", "编译失败（所有候选工具链）"))
                        if args.stop_on_error:
                            print("\n[STOP] --stop-on-error 触发, 停止后续编译")
                            _summary(results)
                            sys.exit(1)

    _summary(results)
    sys.exit(1 if any_failed else 0)


def _summary(results):
    print("\n" + "=" * 60)
    print("  汇总报告")
    print("=" * 60)
    if not results:
        print("  (没有执行任何编译)")
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
