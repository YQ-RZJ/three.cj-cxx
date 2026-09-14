#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openssl4cj 全平台自动交叉编译 + 打包脚本
========================================
驱动 OpenSSL 自带的 Configure + make 编译 OpenSSL C 侧库，
CLI 约定与 bgfx4cj/cxx/build.py 对齐：
  - 模式:   debug / release
  - 架构:   x86_64 / arm64-v8a
  - 平台:   LINUX WINDOWS ANDROID OHOS BSD IOS OSX
  - 工具链: mingw / clang（NDK、OHOS SDK、xcrun）
  - 库类型: static / shared

说明：
  - OpenSSL 使用 Configure + make 构建系统，产物就地落在源码目录下；
  - 每个组合编译成功后立即打包为规范命名 zip（include/ + lib/）；
  - 编译完成后自动将库文件和头文件复制到父工程 libs/ 目录；
  - 宏裁剪：通过 Configure 的 no-* 选项禁用不必要的功能，缩小库体积。

用法示例：
  python build.py                                  # 全部平台排列组合
  python build.py --platforms WINDOWS              # 只编 Windows（mingw）
  python build.py --platforms ANDROID --ndk D:/ndk
  python build.py --modes release --arches x86_64
  python build.py --libtype static                 # 只编静态库
  python build.py --batch                          # 非交互
"""

import argparse
import atexit
import ctypes
import glob
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import time
import zipfile

# CI-PATCH: --libs 选择性构建（默认全量；未知库名直接报错；输出保持声明顺序）
_ALLOWED_LIBS = ["openssl", "tlsbridge"]


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
OPENSSL_DIR = os.path.join(SCRIPT_DIR, "openssl")           # OpenSSL 源码
TLSBRIDGE_DIR = os.path.join(SCRIPT_DIR, "tlsbridge")       # tlsbridge 包装库
DIST_DIR    = os.path.join(SCRIPT_DIR, "dist")              # zip / 日志输出
LOG_DIR     = os.path.join(DIST_DIR, "logs")
BUILD_DIR   = os.path.join(SCRIPT_DIR, "build")             # 构建中间产物
LIBS_DIR    = os.path.join(os.path.dirname(SCRIPT_DIR), "libs")  # 父工程 libs/

ALL_PLATFORMS = ["LINUX", "WINDOWS", "ANDROID", "OHOS", "BSD", "IOS", "OSX"]
ALL_MODES     = ["debug", "release"]
ALL_ARCHES    = ["x86_64", "arm64-v8a"]
ALL_LIBTYPES  = ["static", "shared"]

# OpenSSL 公开头文件（打包用）
OPENSSL_PUBLIC_HEADERS = ["opensslconf.h", "opensslv.h", "ossl_typ.h",
                          "aes.h", "asn1.h", "asn1t.h", "async.h", "bio.h",
                          "bn.h", "buffer.h", "cmac.h", "cmp.h", "cms.h",
                          "conf.h", "conf_api.h", "crypto.h", "cryptoerr.h",
                          "ct.h", "des.h", "dh.h", "dsa.h", "dtls1.h",
                          "e_os2.h", "ebcdic.h", "ec.h", "ecdh.h", "ecdsa.h",
                          "engine.h", "err.h", "evp.h", "hmac.h", "hpke.h",
                          "httperr.h", "http.h", "idea.h", "kdf.h", "lhash.h",
                          "macros.h", "md4.h", "md5.h", "mdc2.h", "modes.h",
                          "obj_mac.h", "objects.h", "ocsp.h", "opensslv.h",
                          "ossl_typ.h", "pem.h", "pem2.h", "pkcs12.h",
                          "pkcs7.h", "policydocs.h", "poly1305.h", "provider.h",
                          "rand.h", "rc2.h", "rc4.h", "ripemd.h", "rsa.h",
                          "safestack.h", "seed.h", "self_test.h", "sha.h",
                          "srtp.h", "ssl.h", "ssl2.h", "ssl3.h", "stack.h",
                          "store.h", "symhacks.h", "tls1.h", "trace.h", "ts.h",
                          "txt_db.h", "types.h", "ui.h", "whrlpool.h", "x509.h",
                          "x509_vfy.h", "x509v3.h"]

# 编译产物文件扩展名
LIB_EXTENSIONS = (".a", ".lib", ".so", ".dll", ".dylib")

# 平台 -> OpenSSL Configure 目标
OPENSSL_TARGET = {
    "WINDOWS": {
        "x86_64":    "mingw64",
        "arm64-v8a": "mingw64",
    },
    "LINUX": {
        "x86_64":    "linux-x86_64",
        "arm64-v8a": "linux-aarch64",
    },
    "ANDROID": {
        "x86_64":    "android-x86_64",
        "arm64-v8a": "android-arm64",
    },
    "OHOS": {
        "x86_64":    "linux-x86_64",
        "arm64-v8a": "linux-aarch64",
    },
    "BSD": {
        "x86_64":    "BSD-x86_64",
        "arm64-v8a": "BSD-aarch64",
    },
    "IOS": {
        "x86_64":    "ios64-xcrun",
        "arm64-v8a": "ios64-xcrun",
    },
    "OSX": {
        "x86_64":    "darwin64-x86_64-cc",
        "arm64-v8a": "darwin64-arm64-cc",
    },
}

# 宏裁剪：不必要功能全部禁用，缩小 OpenSSL 库体积
TRIMMED_CONFIG = " ".join([
    "no-afalgeng",
    "no-aria",
    "no-asan",
    "no-autoalginit",
    "no-autoerrinit",
    "no-bf",
    "no-blake2",
    "no-camellia",
    "no-cast",
    "no-chacha",
    "no-cmac",
    "no-comp",
    "no-crmf",
    "no-crypto-mdebug",
    "no-ct",
    "no-deprecated",
    "no-des",
    "no-dgram",
    "no-dh",
    "no-dsa",
    "no-dso",
    "no-ec2m",
    "no-ecdh",
    "no-ecdsa",
    "no-engine",
    "no-err",
    "no-filenames",
    "no-fips",
    "no-fuzz-afl",
    "no-fuzz-libfuzzer",
    "no-gost",
    "no-hw",
    "no-idea",
    "no-ktls",
    "no-md2",
    "no-md4",
    "no-mdc2",
    "no-module",
    "no-multiblock",
    "no-nextprotoneg",
    "no-ocb",
    "no-ocsp",
    "no-padlockeng",
    "no-pic",
    "no-posix-io",
    "no-psk",
    "no-rc2",
    "no-rc4",
    "no-rc5",
    "no-rfc3779",
    "no-rmd160",
    "no-scrypt",
    "no-seed",
    "no-shared",
    "no-siphash",
    "no-siv",
    "no-sm2",
    "no-sm3",
    "no-sm4",
    "no-sock",
    "no-srp",
    "no-srtp",
    "no-sse2",
    "no-ssl",
    "no-ssl-trace",
    "no-static",
    "no-stdio",
    "no-tests",
    "no-ubsan",
    "no-ui-console",
    "no-whirlpool",
    "no-tls1",
    "no-tls1_1",
    "no-tls1_2",
    "no-ssl3",
])

# 必需保留的算法（SSL/TLS 需要）
REQUIRED_ALGORITHMS = [
    "aes", "aria", "asn1", "async", "autoalginit", "autoerrinit",
    "bio", "bn", "buffer", "cmac", "conf", "crmf", "crypto", "ct",
    "des", "dh", "dsa", "ec", "ecdh", "ecdsa", "engine", "err",
    "evp", "hmac", "hpke", "http", "kdf", "lhash", "modes",
    "objects", "ocsp", "pem", "pkcs12", "pkcs7", "poly1305",
    "provider", "rand", "rsa", "sha", "siphash", "sm2", "sm3",
    "sm4", "srp", "srtp", "ssl", "store", "ts", "ui", "x509", "x509v3",
]

# 只保留 no-* 中对非必需功能的禁用
# 构建时动态计算：保留 REQUIRED_ALGORITHMS 中的，禁用其余
CONFIG_SLIM = "no-weak-ssl-ciphers no-comp no-dso no-engine no-tests no-ssl3"

# 默认的 NDK 路径
NDK_DEFAULT = r"C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native"


def to_msys2_path(path):
    """转换 Windows 路径为 MSYS2 路径: D:\\foo\\bar -> /d/foo/bar"""
    drive, rest = os.path.splitdrive(path)
    if drive:
        return "/" + drive.rstrip(":").lower() + rest.replace("\\", "/")
    return path.replace("\\", "/")


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
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "arm64-v8a"
    return m


def is_windows():
    return os.name == "nt"


def exe_suffix():
    return ".exe" if is_windows() else ""


def find_tool(name):
    p = shutil.which(name)
    return os.path.abspath(p) if p else None


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


_BATCH_FLAG = False


def set_batch_flag(flag):
    global _BATCH_FLAG
    _BATCH_FLAG = flag


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="openssl4cj 全平台自动交叉编译 + 打包脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--platforms", default=",".join(ALL_PLATFORMS),
                    help="编译平台清单，逗号分隔（默认全部，OHOS=OpenHarmony/HarmonyOS）")
    ap.add_argument("--modes", default=",".join(ALL_MODES),
                    help="编译模式清单: debug,release（默认全部）")
    ap.add_argument("--arches", default=",".join(ALL_ARCHES),
                    help="架构清单: x86_64,arm64-v8a（默认全部）")
    ap.add_argument("--libtype", default=",".join(ALL_LIBTYPES),
                    help="库类型清单: static,shared（默认全部）")
    ap.add_argument("--ndk", default=None,
                    help="Android NDK 路径（或环境变量 ANDROID_NDK_HOME / OHOS_SDK）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="HarmonyOS / OpenHarmony NDK 路径（OHOS 平台，或环境变量 OHOS_SDK）")
    ap.add_argument("--msys2", default=None,
                    help="MSYS2 安装路径（WINDOWS 平台需要，默认自动探测）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 工具链目录（WINDOWS 平台用，默认从 PATH 探测）")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数（默认=CPU核数）")
    ap.add_argument("--dist", default=DIST_DIR, help="zip 与日志输出目录（默认 dist/）")
    ap.add_argument("--libs-dir", default=LIBS_DIR,
                    help="编译成功后复制库文件到该目录（默认父工程 libs/）")
    ap.add_argument("--no-libs-copy", action="store_true",
                    help="不复制库文件到 libs 目录")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空 dist/ 与 build/")
    ap.add_argument("--batch", "--no-interactive", dest="batch", action="store_true",
                    help="非交互模式")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="编译失败即停止")
    ap.add_argument("--skip-package", action="store_true",
                    help="只编译，不打包 zip")
    ap.add_argument("--no-trim", action="store_true",
                    help="不进行宏裁剪（编译完整 OpenSSL）")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序）：openssl,tlsbridge（默认=全量编译）")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def run(cmd, cwd=None, env=None, log=None):
    """执行命令并实时回显；返回退出码。"""
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


def collect_outputs(ssl_dir, platform, arch, libtype):
    """
    从 OpenSSL 源码目录收集编译产物。
    返回 (libs, headers) 列表，每个元素为 (绝对路径, 相对归档路径)。
    """
    libs = []
    headers = []

    # 收集库文件
    lib_exts = [".a", ".lib"] if libtype == "static" else [".so", ".dll", ".dylib", ".dll.a"]
    for root, _dirs, files in os.walk(ssl_dir):
        # 跳过 apps/ test/ 等无关目录
        rel = os.path.relpath(root, ssl_dir)
        if rel.startswith("apps") or rel.startswith("test") or rel.startswith("fuzz"):
            continue
        # 跳过 .git/
        if ".git" in rel:
            continue
        for f in files:
            low = f.lower()
            if libtype == "static" and (low.endswith(".a") or low.endswith(".lib")):
                full = os.path.join(root, f)
                # 排除 .dll.a (import libs)
                if not low.endswith(".dll.a"):
                    libs.append((full, os.path.join("lib", f)))
            elif libtype == "shared":
                if low.endswith(".so") or low.endswith(".dll") or low.endswith(".dylib"):
                    full = os.path.join(root, f)
                    libs.append((full, os.path.join("lib", f)))
                # DLL import libs (.dll.a) 也随 shared 打包
                if low.endswith(".dll.a"):
                    full = os.path.join(root, f)
                    libs.append((full, os.path.join("lib", f)))

    # 收集头文件
    include_dir = os.path.join(ssl_dir, "include", "openssl")
    if os.path.isdir(include_dir):
        for root, _dirs, files in os.walk(include_dir):
            for f in files:
                if f.lower().endswith(".h"):
                    full = os.path.join(root, f)
                    # rel 是 include/openssl/xxx.h 或 openssl/xxx.h
                    rel = os.path.relpath(full, ssl_dir)
                    headers.append((full, rel))

    # tlsbridge 库
    tlsbridge_lib = os.path.join(BUILD_DIR, "tlsbridge", "libtlsbridge.a")
    if os.path.isfile(tlsbridge_lib):
        libs.append((tlsbridge_lib, os.path.join("lib", "libtlsbridge.a")))

    # tlsbridge 头文件
    tlsbridge_header = os.path.join(TLSBRIDGE_DIR, "api.h")
    if os.path.isfile(tlsbridge_header):
        headers.append((tlsbridge_header, os.path.join("include", "tlsbridge", "api.h")))

    return libs, headers


# ---------------------------------------------------------------------------
# SDK 路径解析
# ---------------------------------------------------------------------------
def resolve_msys2(args):
    """探测 MSYS2 安装路径（WINDOWS 平台需要）。"""
    # CI-PATCH: GitHub runner 预装的 C:\msys64 是精简实例（无 perl/make），
    # setup-msys2 安装的完整实例在 hostedtoolcache 下——优先选带 perl 的实例。
    import glob as _glob
    candidates = [
        args.msys2,
        os.environ.get("MSYS2_ROOT"),
        r"D:\Venv\msys64",
        r"d:\workspace\Projects\three.cj\msys2_temp\msys64",
        r"C:\msys64",
        r"C:\msys2",
    ]
    candidates += sorted(
        _glob.glob(r"C:\hostedtoolcache\windows\msys2-installer\*\x64\msys64"),
        reverse=True)
    # CI-PATCH: setup-msys2 默认把实例装在 %RUNNER_TEMP%\msys64（location 未生效时的兜底）
    _rt = os.environ.get("RUNNER_TEMP")
    if _rt:
        candidates.append(os.path.join(_rt, "msys64"))
    candidates += sorted(_glob.glob(r"D:\a\_temp\msys*"), reverse=True)
    fallback = None
    for c in candidates:
        if c:
            # CI-PATCH: setup-msys2 的 destination=SFX 解包根会带 msys64\ 一级前缀
            # （如 C:\msys2-full\msys64），自动兼容两种布局
            if not os.path.isfile(os.path.join(c, "usr", "bin", "bash.exe")) \
                    and os.path.isfile(os.path.join(c, "msys64", "usr", "bin", "bash.exe")):
                c = os.path.join(c, "msys64")
            if not os.path.isfile(os.path.join(c, "usr", "bin", "bash.exe")):
                continue
            c = os.path.normpath(c)
            if os.path.isfile(os.path.join(c, "usr", "bin", "perl.exe")):
                return c          # 完整实例（openssl Configure 需要 perl）
            fallback = fallback or c
    if fallback:
        print("  [WARN] MSYS2 实例 %s 缺少 perl，openssl Configure 将失败" % fallback)
    return fallback


def resolve_mingw(args):
    """探测 MinGW-w64 工具链路径。"""
    # CI-PATCH: 候选含 GitHub runner 的 msys2 布局（C:\msys64\mingw64）
    # 与 MINGW_PREFIX 环境变量（msys2/setup-msys2 action 会注入）
    candidates = [
        args.mingw,
        os.environ.get("MINGW_PREFIX"),
        r"D:\Venv\C_Cpp\llvm-mingw",          # 通用，同时支持 x86_64 + arm64-v8a
        r"D:\Venv\C_Cpp\mingw-w64\mingw64_15.2.0",
        r"D:\Venv\C_Cpp\mingw-w64\mingw64",
        r"C:\msys64\mingw64",                 # GitHub runner msys2 工具链
        r"C:\msys2\mingw64",
        r"C:\msys64\clang64",                 # msys2 clang 工具链（clang.exe 兜底）
    ]
    for c in candidates:
        if c:
            # 检查常用编译器存在性
            for cc in ("gcc.exe", "clang.exe", "aarch64-w64-mingw32-gcc.exe", "x86_64-w64-mingw32-gcc.exe"):
                if os.path.isfile(os.path.join(c, "bin", cc)):
                    return os.path.normpath(c)
    return None


def resolve_ndk(args):
    """解析 NDK 路径（ANDROID 平台需要）。"""
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
    """解析 HarmonyOS / OpenHarmony NDK 路径（OHOS 平台需要）。"""
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


def probe_mingw_toolchain(arch, mingw_dir):
    """探测 mingw-w64 交叉工具链，返回 (cc, ar, strip) 或 None。"""
    triples = {"x86_64": "x86_64-w64-mingw32-", "arm64-v8a": "aarch64-w64-mingw32-"}
    pre = triples.get(arch, triples["x86_64"])
    exe = exe_suffix()
    # 优先尝试的编译器名（gcc / clang）
    cc_candidates = [pre + "gcc" + exe, pre + "clang" + exe]
    ar_name  = pre + "ar" + exe
    strip_name = pre + "strip" + exe
    # 1) --mingw 指定目录
    if mingw_dir and os.path.isdir(mingw_dir):
        bin_dir = os.path.join(mingw_dir, "bin")
        # 找 cc
        cc = None
        for name in cc_candidates:
            p = os.path.join(bin_dir, name)
            if os.path.isfile(p):
                cc = p
                break
        # 找 ar
        ar = os.path.join(bin_dir, ar_name)
        if not os.path.isfile(ar):
            ar = os.path.join(bin_dir, "ar" + exe)
        # 找 strip
        strip = os.path.join(bin_dir, strip_name)
        if not os.path.isfile(strip):
            strip = os.path.join(bin_dir, "strip" + exe)
        if cc:
            return (cc, ar, strip)
    # 2) PATH 中查找
    cc = None
    for name in cc_candidates:
        cc = find_tool(name)
        if cc:
            break
    ar = find_tool(ar_name) or find_tool("ar" + exe)
    if cc and ar:
        return (cc, ar, find_tool(strip_name) or find_tool("strip" + exe))
    return None


def probe_ndk_toolchain(ndk, arch, host):
    """
    探测 NDK 结构，返回 (cc, ar, sysroot, target)。
    兼容两种布局：
      - OpenHarmony NDK: <ndk>/llvm/bin/clang + <ndk>/sysroot
      - Android NDK:     <ndk>/toolchains/llvm/prebuilt/<host>/bin/clang
    """
    exe = exe_suffix()
    ohos_bin = os.path.join(ndk, "llvm", "bin", "clang" + exe)
    if os.path.isfile(ohos_bin) and os.path.isdir(os.path.join(ndk, "sysroot")):
        bin_dir = os.path.join(ndk, "llvm", "bin")
        sysroot = os.path.join(ndk, "sysroot")
        target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    else:
        # Android NDK
        hostdirs = {
            "WINDOWS": ["windows-x86_64"],
            "OSX":     ["darwin-arm64" if machine_arch() == "arm64-v8a" else "darwin-x86_64"],
            "LINUX":   ["linux-x86_64"],
        }.get(host, [])
        base = None
        for hd in hostdirs:
            cand = os.path.join(ndk, "toolchains", "llvm", "prebuilt", hd)
            if os.path.isdir(cand):
                base = cand
                break
        if base is None:
            prebuilt = os.path.join(ndk, "toolchains", "llvm", "prebuilt")
            if os.path.isdir(prebuilt):
                for c in sorted(os.listdir(prebuilt)):
                    if os.path.isfile(os.path.join(prebuilt, c, "bin", "clang" + exe)):
                        base = os.path.join(prebuilt, c)
                        break
        if base is None:
            raise RuntimeError("无法在 NDK 中找到 llvm 工具链: %s" % ndk)
        bin_dir = os.path.join(base, "bin")
        sysroot = os.path.join(base, "sysroot")
        target = "aarch64-linux-android24" if arch == "arm64-v8a" else "x86_64-linux-android24"
    cc = os.path.join(bin_dir, "clang" + exe)
    ar = os.path.join(bin_dir, "llvm-ar" + exe)
    if not os.path.isfile(ar):
        # 可能使用 ar 而非 llvm-ar
        ar = os.path.join(bin_dir, "ar" + exe)
    return cc, ar, sysroot, target


def probe_ohos_toolchain(sdk, arch):
    """探测 OpenHarmony NDK 工具链。"""
    exe = exe_suffix()
    bin_dir = os.path.join(sdk, "llvm", "bin")
    cc = os.path.join(bin_dir, "clang" + exe)
    ar = os.path.join(bin_dir, "llvm-ar" + exe)
    if not os.path.isfile(ar):
        ar = os.path.join(bin_dir, "ar" + exe)
    sysroot = os.path.join(sdk, "sysroot")
    if not (os.path.isfile(cc) and os.path.isdir(sysroot)):
        raise RuntimeError("OHOS SDK 结构不完整: %s" % sdk)
    target = "aarch64-linux-ohos" if arch == "arm64-v8a" else "x86_64-linux-ohos"
    return cc, ar, sysroot, target


# ---------------------------------------------------------------------------
# 可编译性判定
# ---------------------------------------------------------------------------
def can_build(platform, host, ctx):
    """
    返回 (ok, reason)。
    ctx: dict 携带 ndk / ohos / msys2 / mingw 等已解析的 SDK。
    """
    if platform == "WINDOWS":
        if host == "WINDOWS":
            if not ctx.get("msys2"):
                return False, "Windows 主机上缺少 MSYS2"
            if not ctx.get("mingw"):
                return False, "Windows 主机上缺少 MinGW-w64"
            return True, ""
        return False, "WINDOWS 目标需要在 Windows 主机上编译（当前: %s）" % host
    if platform == "LINUX":
        if host == "LINUX":
            return True, ""
        return False, "LINUX 目标需要在 Linux 主机上编译"
    if platform == "BSD":
        if host == "BSD":
            return True, ""
        return False, "BSD 目标需要在 BSD 主机上编译"
    if platform == "ANDROID":
        if ctx.get("ndk"):
            return True, ""
        return False, "缺少 NDK 路径（--ndk / ANDROID_NDK_HOME）"
    if platform == "OHOS":
        if ctx.get("ohos"):
            return True, ""
        return False, "缺少 OHOS SDK 路径（--ohos-sdk / OHOS_SDK）"
    if platform == "IOS":
        if host != "OSX":
            return False, "IOS 必须在 macOS 上编译（当前: %s）" % host
        if not find_tool("xcrun"):
            return False, "macOS 上未找到 xcrun（需要 Xcode）"
        return True, ""
    if platform == "OSX":
        if host != "OSX":
            return False, "OSX 必须在 macOS 上编译（当前: %s）" % host
        if not find_tool("xcrun") and not find_tool("clang"):
            return False, "macOS 上未找到 clang / xcrun（需要 Xcode CLI）"
        return True, ""
    return False, "未知平台: %s" % platform


def toolchains_for(platform, host):
    if platform == "WINDOWS" and host == "WINDOWS":
        return ["mingw"]
    return ["clang"]


# ---------------------------------------------------------------------------
# 清理 OpenSSL 构建产物
# ---------------------------------------------------------------------------
def _generated_asm_files(ssl_dir):
    """
    收集 OpenSSL 中所有由 perlasm 生成的 .s/.S 文件的绝对路径集合。

    权威来源是各目录 build.info 里的 GENERATE[target]=generator 映射：
    只有列在其中的 .s/.S 才是“生成物”，跨平台格式不同，切换平台后必须删除
    重新生成。其余的 .S（如 crypto/bn/asm/ia64.S、crypto/sparccpuid.S）是手写
    源码，必须保留，绝不能删。

    注意：旧实现用“同目录/asm 子目录是否存在同名 .pl”来判定，但 perlasm 的
    生成器文件名经常与产物不同（如 sha256-x86_64.s 由 asm/sha512-x86_64.pl
    生成），导致这类文件永远删不掉，残留下一个平台（如 Windows mingw COFF
    格式）的 .s 污染下一个平台（Android/OHOS ELF 汇编报 unknown directive）。
    """
    gen_re = re.compile(r"^[ \t]*GENERATE\[[ \t]*([^=\]]+?)[ \t]*\][ \t]*=", re.M)
    result = set()
    for root, _dirs, files in os.walk(ssl_dir):
        if "build.info" not in files:
            continue
        try:
            with open(os.path.join(root, "build.info"), "r",
                      encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for m in gen_re.finditer(content):
            target = m.group(1).strip()
            if not target or "=" in target:
                continue
            # 只关心汇编产物（生成器本身、.h 等不在此处理）
            if not target.lower().endswith(".s"):
                continue
            # 生成物总是与 build.info 同目录（GENERATE 的 target 相对路径不含子目录）
            full = os.path.normpath(os.path.join(root, target))
            if os.path.isfile(full):
                result.add(full)
    return result


def clean_openssl(ssl_dir, msys2=None):
    """
    清理 OpenSSL 构建产物，为下一个平台的构建准备干净的源码树。

    关键点：
      1. make distclean 只删 object/库/Makefile/configdata，不删 perlasm 生成的
         .s（它们在 GENERATED 里由 clean 删，但跨平台切换时 .s 的时间戳可能比
         .pl 新，make 会跳过重新生成，导致用上平台格式的 .s 编译）。
      2. 因此这里显式删除所有 GENERATE 映射中的 .s/.S（见 _generated_asm_files），
         保留手写 .S 源码。
      3. 兜底删除所有 .o/.obj（不同平台的 object 格式不同，绝不能混链）。
    """
    if is_windows() and msys2:
        msys2_bash = os.path.join(msys2, "usr", "bin", "bash.exe")
        ssl_dir_msys = to_msys2_path(ssl_dir)
        # CI-PATCH: distclean 依赖 Configure 生成的 Makefile；首次构建时源码树
        # 尚无 Makefile，make 会报 "No rule to make target 'distclean'"——先探测。
        run([msys2_bash, "-c",
             'cd "%s" && [ -f Makefile ] && make distclean 2>/dev/null; exit 0' % ssl_dir_msys],
             cwd=ssl_dir)
    elif not is_windows():
        if os.path.isfile(os.path.join(ssl_dir, "Makefile")):
            run(["make", "distclean"], cwd=ssl_dir)

    # 1) 删除 perlasm 生成的 .s/.S（按 GENERATE 映射，精确、不误删手写源码）
    gen_asm = _generated_asm_files(ssl_dir)
    for full in gen_asm:
        try:
            os.remove(full)
        except OSError:
            pass
    if gen_asm:
        print("    [CLEAN] 删除 %d 个 perlasm 生成的 .s/.S" % len(gen_asm))

    # 2) 兜底：删除全部 object 文件（.o/.obj）——不同平台格式不同，混链必错
    obj_count = 0
    for root, _dirs, files in os.walk(ssl_dir):
        for f in files:
            if f.endswith(".o") or f.endswith(".obj"):
                try:
                    os.remove(os.path.join(root, f))
                    obj_count += 1
                except OSError:
                    pass
    if obj_count:
        print("    [CLEAN] 删除 %d 个残留 object 文件" % obj_count)

    # 3) 清理旧的平台库产物（.a/.so/.dll）——不同平台/配置的库绝不能被复用，
    #    上次构建中断或切换目标时 make 未必会重建它们。
    lib_count = 0
    for root, _dirs, files in os.walk(ssl_dir):
        for f in files:
            if f.endswith((".a", ".dll")) or f == "libcrypto.so" or f == "libssl.so" \
                    or (f.startswith("lib") and ".so." in f):
                try:
                    os.remove(os.path.join(root, f))
                    lib_count += 1
                except OSError:
                    pass
    if lib_count:
        print("    [CLEAN] 删除 %d 个残留库文件" % lib_count)

    # 4) 清理 configdata.pm / Makefile 等 Configure 产物。
    #    注意：绝不删 Makefile.in —— 它是 OpenSSL 的源码模板（Configure 由它
    #    生成各平台的 Makefile），删了会导致后续 Configure 失败。
    for f in ("configdata.pm", "Makefile", "Makefile.save"):
        p = os.path.join(ssl_dir, f)
        if os.path.isfile(p):
            os.remove(p)


# ---------------------------------------------------------------------------
# OpenSSL 编译
# ---------------------------------------------------------------------------
def build_openssl(platform, arch, mode, libtype, toolchain, host, ctx, ssl_dir, log_path):
    """
    编译 OpenSSL。
    使用 Configure + make（不执行 make install），产物直接在源码目录中。
    """
    print("  [BUILD] 编译 OpenSSL %s-%s-%s-%s ..." % (platform.lower(), arch, mode, libtype))

    # 清理之前的构建产物
    clean_openssl(ssl_dir, ctx.get("msys2"))

    # 确定 Configure 目标
    target = OPENSSL_TARGET.get(platform, {}).get(arch, "linux-x86_64")

    # 构建环境（先于交叉注入：CI-PATCH 的 env[...] 赋值依赖它）
    env = os.environ.copy()

    # 构建 Configure 参数
    config_opts = [target]

    # CI-PATCH: LINUX/BSD arm64 交叉——linux-aarch64 目标默认用宿主 gcc，
    # x86_64 宿主编 arm64 产物时 arm_arch.h 报
    # "#error unsupported ARM architecture"（__ARM_ARCH 未定义），必须
    # 注入交叉工具链并关 asm（perlasm 产物按宿主探测，与 bgfx 同款缺口）。
    if platform in ("LINUX", "BSD") and arch == "arm64-v8a":
        import shutil as _sh
        cross_prefix = "aarch64-linux-gnu" if platform == "LINUX" else "aarch64-unknown-freebsd"
        cross_cc = _sh.which(cross_prefix + "-gcc") or _sh.which(cross_prefix + "-clang")
        if cross_cc:
            env["CC"] = cross_prefix + ("-gcc" if cross_cc.endswith("gcc") else "-clang")
            env["CXX"] = env["CC"].replace("gcc", "g++").replace("clang", "clang++")
            env["AR"] = cross_prefix + "-ar"
            env["RANLIB"] = cross_prefix + "-ranlib"
            # arm64 的 perlasm 探测宿主 CPU，交叉时关 asm 保正确性
            config_opts.append("no-asm")
            print("    [CROSS] %s: %s (no-asm)" % (arch, env["CC"]))
        else:
            print("    [WARN] arm64-v8a: 未找到 %s-gcc/clang，回退宿主工具链（将编译失败）" % cross_prefix)

    # 宏裁剪
    if not ctx.get("no_trim"):
        # CI-PATCH: CONFIG_SLIM 必须按空白拆成多个独立参数（extend + split）。
        # 原实现 append 成单个带空格的参数：WINDOWS 走 bash -c '%s' 拼接时被
        # bash 重新分词侥幸可用；macOS/Linux 走 subprocess 列表直传，OpenSSL
        # 收到引号包裹的整串，报 "Unsupported options: no-weak-ssl-ciphers ..."。
        config_opts.extend(CONFIG_SLIM.split())
        # 根据模式添加
        if mode == "debug":
            config_opts.append("--debug")
        else:
            config_opts.append("-O3")

    # 库类型
    if libtype == "static":
        config_opts.append("no-shared")
    else:
        config_opts.append("shared")

    # 禁用 module（shared 模式下默认会生成 .so 模块，不需要）
    if libtype == "static":
        config_opts.append("no-module")

    # 不生成 apps 和 tests
    config_opts.append("no-apps")
    config_opts.append("no-tests")

    if platform == "WINDOWS":
        # Windows: 使用 MSYS2 bash 执行
        msys2 = ctx.get("msys2")
        mingw = ctx.get("mingw")
        if not msys2 or not mingw:
            print("  [ERROR] WINDOWS 平台需要 MSYS2 和 MinGW-w64")
            return False

        msys2_bash = os.path.join(msys2, "usr", "bin", "bash.exe")
        mingw_bin = os.path.join(mingw, "bin")

        # CI-PATCH: WINDOWS arm64-v8a 交叉编译——OpenSSL 的 mingw64 目标默认
        # 按 x86_64 生成汇编与探测 gcc，交叉时必须：
        #   1) 注入 llvm-mingw 的 aarch64-w64-mingw32-* 工具链（CC/AR/...）
        #   2) no-asm（x86_64 perlasm 产物在 arm64 上不可用）
        #   3) make 命令行强制 RC + RCFLAGS——OpenSSL Makefile 写死
        #      RC=windres 且 RCFLAGS 追加 shared_rcflag=--target=pe-x86-64
        #      （Configurations/10-main.conf），仅覆盖 RC 不够：res.obj 仍被
        #      编成 x64，链接 DLL 时 "machine type x64 conflicts with arm64"。
        #      命令行 RCFLAGS 整体替换后指定 pe-aarch64。
        make_overrides = ""
        if arch == "arm64-v8a":
            cross_cc = os.path.join(mingw_bin, "aarch64-w64-mingw32-clang.exe")
            if os.path.isfile(cross_cc):
                env["CC"] = "aarch64-w64-mingw32-clang"
                env["CXX"] = "aarch64-w64-mingw32-clang++"
                env["AR"] = "aarch64-w64-mingw32-ar"
                env["RANLIB"] = "aarch64-w64-mingw32-ranlib"
                env["RC"] = "aarch64-w64-mingw32-windres"
                # CI-PATCH: llvm-mingw 的 windres(llvm-rc) 预处理走 clang，本机
                # 实测转发规则（llvm-mingw-20260616 复现）：
                #   1) 系统头在 <llvm-mingw>/include（顶层，全目标共享），
                #      不在 <target-root>/aarch64-w64-mingw32/include，必须显式 -I；
                #   2) RC 预处理不带 -D_WIN32，_mingw.h 报
                #      "Only Win32 target is supported!"，需补 -D_WIN32；
                #   3) llvm-rc 不认 --target=pe-aarch64/pe-arm64，只认完整
                #      triple aarch64-w64-mingw32。
                # 综上 RCFLAGS 三项：triple 目标 + _WIN32 宏 + 顶层 include。
                target_root = os.path.dirname(os.path.normpath(mingw_bin))
                rc_include = os.path.join(target_root, "include")
                make_overrides = (
                    "RC=aarch64-w64-mingw32-windres"
                    " RCFLAGS=--target=aarch64-w64-mingw32"
                    " RCFLAGS+=-D_WIN32"
                    " RCFLAGS+=-I%s"
                ) % rc_include.replace("\\", "/")
                config_opts.append("no-asm")
                print("    [CROSS] arm64-v8a: %s (no-asm)" % env["CC"])
            else:
                print("    [WARN] arm64-v8a: mingw 中无 aarch64-w64-mingw32-clang，回退宿主工具链")

        # MSYS2 路径转换
        ssl_dir_msys = to_msys2_path(ssl_dir)
        mingw_bin_msys = to_msys2_path(mingw_bin)

        # 构建 shell 命令
        config_str = " ".join(config_opts)
        shell_script = (
            'export PATH="%s:/usr/bin:$PATH"\n'
            'cd "%s" || exit 1\n'
            'echo "=== Configuring OpenSSL === "\n'
            'perl ./Configure %s 2>&1\n'
            'echo "CONFIGURE_EXIT:$?"\n'
            'echo "=== Building OpenSSL === "\n'
            'make %s -j%d 2>&1\n'
            'echo "MAKE_EXIT:$?"\n'
        ) % (mingw_bin_msys, ssl_dir_msys, config_str, make_overrides, ctx.get("jobs", 4))

        tmp_sh = os.path.join(ssl_dir, "_build_openssl.sh")
        with open(tmp_sh, "w", encoding="utf-8") as f:
            f.write(shell_script)

        cmd = [msys2_bash, "--login", tmp_sh]
        rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)

        if os.path.isfile(tmp_sh):
            os.remove(tmp_sh)

    elif platform in ("ANDROID", "OHOS"):
        # Android/OHOS: 使用 NDK clang 交叉编译
        if platform == "ANDROID":
            cc, ar, sysroot, ndk_target = probe_ndk_toolchain(ctx["ndk"], arch, host)
        else:
            cc, ar, sysroot, ndk_target = probe_ohos_toolchain(ctx["ohos"], arch)

        # 注意：不手动设置 CC/AR/CFLAGS，让 OpenSSL Configure 自动检测 NDK 工具链
        # 只需设置 ANDROID_NDK_ROOT 并将 NDK bin 加入 PATH 即可

        if host == "WINDOWS":
            # Windows 主机上需要通过 MSYS2 bash 执行（Windows 没有 perl）
            msys2 = ctx.get("msys2")
            if not msys2:
                print("  [ERROR] ANDROID/OHOS 在 Windows 上编译需要 MSYS2")
                return False
            msys2_bash = os.path.join(msys2, "usr", "bin", "bash.exe")
            ssl_dir_msys = to_msys2_path(ssl_dir)

            config_str = " ".join(config_opts)

            # NDK bin 目录加入 PATH，让 Configure 自动找到 clang
            ndk_bin_dir = os.path.dirname(cc)
            ndk_bin_msys = to_msys2_path(ndk_bin_dir)

            # 注意：这里不用 `set -e`。原因：Configure 失败时若直接靠 set -e 中断，
            # 我们拿不到退出码，也就无法从日志判断失败原因。改为显式捕获退出码、
            # 失败即中止，既能保证“Configure 失败绝不继续 make”（否则会拿上一个
            # 平台的残留 Makefile 编译，把不同平台的对象/库混链），又能在日志里
            # 留下准确的 CONFIGURE_EXIT / MAKE_EXIT 标记便于排查。
            shell_script_lines = [
                'export PATH="%s:$PATH"' % ndk_bin_msys,
            ]
            if platform == "ANDROID":
                ndk_msys = to_msys2_path(ctx["ndk"])
                shell_script_lines.append('export ANDROID_NDK_ROOT="%s"' % ndk_msys)
            else:
                # OHOS: 需要设置 CC 和 sysroot
                cc_msys = to_msys2_path(cc)
                ar_msys = to_msys2_path(ar)
                sysroot_msys = to_msys2_path(sysroot)
                shell_script_lines += [
                    'export CC="%s"' % cc_msys,
                    'export AR="%s"' % ar_msys,
                    'export CROSS_COMPILE=""',
                    'export CFLAGS="--target=%s --sysroot=%s"' % (ndk_target, sysroot_msys),
                    'export LDFLAGS="--target=%s --sysroot=%s"' % (ndk_target, sysroot_msys),
                ]
            shell_script_lines += [
                'cd "%s" || exit 1' % ssl_dir_msys,
                'echo "=== Configuring OpenSSL === "',
                'perl ./Configure %s' % config_str,
                'CONFIGURE_EXIT=$?',
                'echo "CONFIGURE_EXIT:$CONFIGURE_EXIT"',
                'if [ "$CONFIGURE_EXIT" -ne 0 ]; then',
                '    echo "CONFIGURE FAILED (exit $CONFIGURE_EXIT) -- 中止，不执行 make（避免用残留 Makefile 混链）"',
                '    exit 1',
                'fi',
                'echo "=== Building OpenSSL === "',
                'make -j%d' % ctx.get("jobs", 4),
                'MAKE_EXIT=$?',
                'echo "MAKE_EXIT:$MAKE_EXIT"',
                'exit "$MAKE_EXIT"',
            ]
            shell_script = '\n'.join(shell_script_lines) + '\n'

            tmp_sh = os.path.join(ssl_dir, "_build_openssl.sh")
            with open(tmp_sh, "w", encoding="utf-8") as f:
                f.write(shell_script)

            cmd = [msys2_bash, "--login", tmp_sh]
            rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)

            if os.path.isfile(tmp_sh):
                os.remove(tmp_sh)
        else:
            # Linux/macOS 主机：直接使用系统 perl + make
            # 同样，ANDROID 让 Configure 自动检测，OHOS 手动设置
            if platform == "ANDROID":
                env["ANDROID_NDK_ROOT"] = ctx["ndk"]
                ndk_bin_dir = os.path.dirname(cc)
                env["PATH"] = ndk_bin_dir + os.pathsep + env.get("PATH", "")
            else:
                env["CC"] = cc
                env["AR"] = ar
                env["CROSS_COMPILE"] = ""
                env["CFLAGS"] = "--target=" + ndk_target + " --sysroot=" + sysroot
                env["LDFLAGS"] = "--target=" + ndk_target + " --sysroot=" + sysroot

            cmd = ["perl", "./Configure"] + config_opts
            rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)
            if rc != 0:
                return False

            cmd = ["make", "-j%d" % ctx.get("jobs", 4)]
            rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)

    elif platform in ("LINUX", "BSD"):
        # Linux/BSD: 使用系统 gcc/clang
        # CI-PATCH: 用 perl 显式执行 Configure——macOS runner 的 checkout 不保留
        # exec 位，"./Configure" 直接执行报 Permission denied（perl 脚本）。
        cmd = ["perl", "./Configure"] + config_opts
        rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)
        if rc != 0:
            return False

        cmd = ["make", "-j%d" % ctx.get("jobs", 4)]
        rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)

    elif platform in ("IOS", "OSX"):
        # macOS: 使用 clang
        if platform == "IOS":
            # iOS 需要 xcrun
            sdk = "iphoneos" if arch == "arm64-v8a" else "iphonesimulator"
            sdk_path = subprocess.check_output(["xcrun", "--sdk", sdk, "--show-sdk-path"],
                                               stderr=subprocess.DEVNULL).decode().strip()
            target = "arm64-apple-ios" if arch == "arm64-v8a" else "x86_64-apple-ios-simulator"
            env["CC"] = "xcrun -sdk %s clang" % sdk
            env["CFLAGS"] = "-target " + target + " -isysroot " + sdk_path
        else:
            # macOS native
            target = "arm64-apple-macosx" if arch == "arm64-v8a" else "x86_64-apple-macosx"
            env["CC"] = find_tool("clang") or "clang"
            env["CFLAGS"] = "-target " + target

        # CI-PATCH: 用 perl 显式执行 Configure——macOS runner 的 checkout 不保留
        # exec 位，"./Configure" 直接执行报 Permission denied（perl 脚本）。
        cmd = ["perl", "./Configure"] + config_opts
        rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)
        if rc != 0:
            return False

        cmd = ["make", "-j%d" % ctx.get("jobs", 4)]
        rc = run(cmd, cwd=ssl_dir, env=env, log=log_path)

    else:
        print("  [ERROR] 不支持的平台: %s" % platform)
        return False

    if rc != 0:
        print("  [ERROR] OpenSSL 编译失败")
        return False

    # 验证产物
    libs, _ = collect_outputs(ssl_dir, platform, arch, libtype)
    if not libs:
        print("  [ERROR] 编译后未找到库文件")
        return False

    print("  [OK] OpenSSL 编译完成，共 %d 个库文件" % len(libs))
    return True


# ---------------------------------------------------------------------------
# tlsbridge 编译
# ---------------------------------------------------------------------------
def build_tlsbridge(platform, arch, mode, host, ctx, ssl_dir, log_path):
    """
    编译 tlsbridge 包装库。
    将 tlsbridge/*.c 编译为静态库 libtlsbridge.a，
    链接 OpenSSL 的 libcrypto.a + libssl.a。
    """
    print("  [BUILD] 编译 tlsbridge ...")

    # 确定编译器
    if platform == "WINDOWS":
        mingw = ctx.get("mingw")
        if not mingw:
            print("  [ERROR] 缺少 MinGW-w64")
            return False
        tc = probe_mingw_toolchain(arch, mingw)
        if not tc:
            print("  [ERROR] 无法找到 %s 的 mingw 工具链" % arch)
            return False
        cc, ar, _ = tc
        cflags = "-Wall -O2" if mode == "release" else "-Wall -g -O0"
        openssl_include = os.path.join(ssl_dir, "include")
        cflags += " -I" + openssl_include
        # 链接 OpenSSL 库
        ssl_libs = "-L" + ssl_dir + " -lcrypto -lssl"

    elif platform in ("ANDROID", "OHOS"):
        if platform == "ANDROID":
            cc, ar, sysroot, ndk_target = probe_ndk_toolchain(ctx["ndk"], arch, host)
        else:
            cc, ar, sysroot, ndk_target = probe_ohos_toolchain(ctx["ohos"], arch)
        cflags = "-Wall -O2 -fPIC" if mode == "release" else "-Wall -g -O0 -fPIC"
        cflags += " -I" + os.path.join(ssl_dir, "include")
        cflags += " --target=" + ndk_target + " --sysroot=" + sysroot
        ssl_libs = "-L" + ssl_dir + " -lcrypto -lssl"

    elif platform in ("LINUX", "BSD"):
        cc = "cc"
        ar = "ar"
        cflags = "-Wall -O2 -fPIC" if mode == "release" else "-Wall -g -O0 -fPIC"
        cflags += " -I" + os.path.join(ssl_dir, "include")
        ssl_libs = "-L" + ssl_dir + " -lcrypto -lssl"

    elif platform in ("IOS", "OSX"):
        cc = find_tool("clang") or "clang"
        ar = "ar"
        cflags = "-Wall -O2 -fPIC" if mode == "release" else "-Wall -g -O0 -fPIC"
        cflags += " -I" + os.path.join(ssl_dir, "include")
        if platform == "IOS":
            sdk = "iphoneos" if arch == "arm64-v8a" else "iphonesimulator"
            sdk_path = subprocess.check_output(["xcrun", "--sdk", sdk, "--show-sdk-path"],
                                               stderr=subprocess.DEVNULL).decode().strip()
            target = "arm64-apple-ios" if arch == "arm64-v8a" else "x86_64-apple-ios-simulator"
            cflags += " -target " + target + " -isysroot " + sdk_path
        else:
            target = "arm64-apple-macosx" if arch == "arm64-v8a" else "x86_64-apple-macosx"
            cflags += " -target " + target
        ssl_libs = "-L" + ssl_dir + " -lcrypto -lssl"

    else:
        print("  [ERROR] 不支持的平台: %s" % platform)
        return False

    # 收集所有 .c 文件
    src_files = sorted(glob.glob(os.path.join(TLSBRIDGE_DIR, "*.c")))
    if not src_files:
        print("  [ERROR] tlsbridge 目录下没有 .c 文件: %s" % TLSBRIDGE_DIR)
        return False

    tlsbridge_out = os.path.join(BUILD_DIR, "tlsbridge")
    os.makedirs(tlsbridge_out, exist_ok=True)

    # 编译每个 .c 文件为 .o
    obj_files = []
    for src in src_files:
        basename = os.path.splitext(os.path.basename(src))[0]
        obj = os.path.join(tlsbridge_out, basename + ".o")
        obj_files.append(obj)

        cmd = [cc, "-c", src, "-o", obj] + cflags.split()
        if run(cmd, cwd=SCRIPT_DIR, log=log_path) != 0:
            print("  [ERROR] 编译 %s 失败" % os.path.basename(src))
            return False

    # 链接为静态库
    lib_path = os.path.join(tlsbridge_out, "libtlsbridge.a")
    ar_cmd = [ar, "rcs", lib_path] + obj_files
    if run(ar_cmd, cwd=SCRIPT_DIR, log=log_path) != 0:
        print("  [ERROR] 创建 libtlsbridge.a 失败")
        return False

    print("  [OK] tlsbridge 编译完成: %s" % lib_path)
    return True


# ---------------------------------------------------------------------------
# 复制库文件到 libs/
# ---------------------------------------------------------------------------
def copy_libs(ssl_dir, libs_dir, subdir, platform, arch, libtype):
    """把 OpenSSL 库文件 + tlsbridge 库文件复制到 libs_dir/<subdir>。"""
    target = os.path.join(libs_dir, subdir)
    os.makedirs(target, exist_ok=True)
    copied = []

    # 收集并复制库文件
    libs, _ = collect_outputs(ssl_dir, platform, arch, libtype)
    for full, arcname in libs:
        dst = os.path.join(target, os.path.basename(arcname))
        shutil.copy2(full, dst)
        copied.append(dst)

    # 复制头文件
    include_dir = os.path.join(ssl_dir, "include", "openssl")
    if os.path.isdir(include_dir):
        target_include = os.path.join(target, "include", "openssl")
        os.makedirs(target_include, exist_ok=True)
        for root, _dirs, files in os.walk(include_dir):
            for f in files:
                if f.lower().endswith(".h"):
                    shutil.copy2(os.path.join(root, f), target_include)

    # 复制 tlsbridge 头文件
    tlsbridge_header = os.path.join(TLSBRIDGE_DIR, "api.h")
    if os.path.isfile(tlsbridge_header):
        target_tls = os.path.join(target, "include", "tlsbridge")
        os.makedirs(target_tls, exist_ok=True)
        shutil.copy2(tlsbridge_header, target_tls)

    if copied:
        print("  [OK] 已复制 %d 个文件到 %s" % (len(copied), target))
    else:
        print("  [WARN] 没有找到库文件可复制")


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------
def package(platform, mode, arch, libtype, ssl_dir, dist_dir, args):
    """打包编译产物为 zip。"""
    name = "openssl-%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)
    zip_path = os.path.join(dist_dir, name + ".zip")

    libs, headers = collect_outputs(ssl_dir, platform, arch, libtype)

    if not libs:
        print("  [WARN] 没有库文件可打包")
        return None

    os.makedirs(dist_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arcname in headers:
            z.write(full, os.path.join(name, arcname))
        for full, arcname in libs:
            z.write(full, os.path.join(name, arcname))
    return zip_path


# ---------------------------------------------------------------------------
# 构建锁（防止两个 build.py 同时编译同一棵 openssl/ 源码树）
# ---------------------------------------------------------------------------
# 同一时刻只能有一个构建进程操作 openssl/：两个进程并行时会互相覆盖
# Makefile / configdata.pm / .s，表现为 CONFIGURE_EXIT:2 后仍继续 make、
# 残留对象混链（undefined symbol）等连锁错误。
BUILD_LOCK_FILE = os.path.join(SCRIPT_DIR, ".buildlock")


def _pid_alive(pid):
    """判断进程号是否仍存活（用于识别 stale 锁）。"""
    if pid <= 0:
        return False
    try:
        if is_windows():
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(int(pid), 0)
        return True
    except (OSError, AttributeError, ValueError):
        pass
    return False


def acquire_build_lock():
    """获取独占构建锁；被活进程持有时直接退出，stale 锁自动回收。"""
    for _attempt in range(3):
        try:
            fd = os.open(BUILD_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("pid=%d\n" % os.getpid())
                f.write("time=%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                f.write("argv=%s\n" % " ".join(sys.argv))
            atexit.register(release_build_lock)
            return BUILD_LOCK_FILE
        except FileExistsError:
            try:
                with open(BUILD_LOCK_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                m = re.search(r"pid=(\d+)", content)
                pid = int(m.group(1)) if m else -1
                if _pid_alive(pid):
                    print("[ERROR] 已有另一个 build.py（PID %d）正在编译，"
                          "同一 openssl/ 源码树不能并发构建，请等其结束。" % pid)
                    sys.exit(1)
                print("  [WARN] 回收 stale 构建锁（上一进程 PID %d 已退出）" % pid)
                os.remove(BUILD_LOCK_FILE)
            except OSError:
                time.sleep(0.5)
        except OSError as e:
            print("[ERROR] 创建构建锁失败: %s" % e)
            sys.exit(1)
    print("[ERROR] 无法获取构建锁: %s" % BUILD_LOCK_FILE)
    sys.exit(1)


def release_build_lock():
    try:
        if os.path.isfile(BUILD_LOCK_FILE):
            os.remove(BUILD_LOCK_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------
def clean():
    for d in (BUILD_DIR, DIST_DIR):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            print("  已清理: %s" % d)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    host = detect_host()
    set_batch_flag(args.batch)

    # 独占锁：同一 openssl/ 源码树只允许一个构建进程
    acquire_build_lock()

    if args.clean:
        clean()

    print("=" * 60)
    print("  openssl4cj 全平台编译 + 打包")
    print("=" * 60)
    print("  当前主机: %s (%s)" % (host, machine_arch()))
    print("  源码目录: %s" % OPENSSL_DIR)
    print("  平台清单: %s" % args.platforms)
    print("  模式:     %s" % args.modes)
    print("  架构:     %s" % args.arches)
    print("  库类型:   %s" % args.libtype)
    print("  宏裁剪:   %s" % ("禁用" if args.no_trim else "启用"))
    print("=" * 60)

    platforms = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    modes     = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    arches    = [a.strip().lower() for a in args.arches.split(",") if a.strip()]
    libtypes  = [t.strip().lower() for t in args.libtype.split(",") if t.strip()]

    for p in platforms:
        if p not in ALL_PLATFORMS:
            print("  [WARN] 未知平台 %s，忽略" % p)
    platforms = [p for p in platforms if p in ALL_PLATFORMS]

    # 探测 SDK
    msys2 = resolve_msys2(args)
    mingw = resolve_mingw(args)
    ndk = resolve_ndk(args) if "ANDROID" in platforms else None
    ohos = resolve_ohos_sdk(args) if "OHOS" in platforms else None

    ctx = {
        "msys2": msys2,
        "mingw": mingw,
        "ndk": ndk,
        "ohos": ohos,
        "jobs": args.jobs,
        "no_trim": args.no_trim,
    }

    print("  MSYS2: %s" % (msys2 or "未找到（WINDOWS 需要）"))
    print("  MinGW: %s" % (mingw or "未找到（WINDOWS 需要）"))
    print("  NDK:   %s" % (ndk or "未设置（ANDROID 需要）"))
    print("  OHOS:  %s" % (ohos or "未设置（OHOS 需要）"))
    print("=" * 60)

    dist_dir = os.path.abspath(args.dist)
    results = []
    any_failed = False

    for platform in platforms:
        ok, reason = can_build(platform, host, ctx)
        if not ok:
            print("\n[SKIP] %s: %s" % (platform, reason))
            results.append((platform, "skip", reason))
            continue

        print("\n===== 平台 %s（%s 主机）=====" % (platform, host))

        # CI-PATCH: --libs 选择性构建（默认全量）：openssl,tlsbridge 按序只编指定库
        wanted = set(parse_libs_arg(args.libs, _ALLOWED_LIBS, "httpclient"))

        for mode in modes:
            for arch in arches:
                for libtype in libtypes:
                    tc_list = toolchains_for(platform, host)
                    for toolchain in tc_list:
                        combo = "%s-%s-%s-%s" % (platform.lower(), arch, mode, libtype)

                        # 编译 OpenSSL
                        if "openssl" not in wanted:
                            print("  [skip] openssl（--libs 未包含）")
                        else:
                            log_path = os.path.join(LOG_DIR, "openssl-%s.log" % combo)
                            if not build_openssl(
                                platform, arch, mode, libtype, toolchain, host, ctx,
                                OPENSSL_DIR, log_path,
                            ):
                                any_failed = True
                                results.append((combo, "fail", "OpenSSL 编译失败"))
                                if args.stop_on_error:
                                    sys.exit(1)
                                continue

                        # 编译 tlsbridge
                        if "tlsbridge" not in wanted:
                            print("  [skip] tlsbridge（--libs 未包含）")
                        else:
                            log_path = os.path.join(LOG_DIR, "tlsbridge-%s.log" % combo)
                            if not build_tlsbridge(
                                platform, arch, mode, host, ctx, OPENSSL_DIR, log_path,
                            ):
                                any_failed = True
                                results.append((combo, "fail", "tlsbridge 编译失败"))
                                if args.stop_on_error:
                                    sys.exit(1)
                                continue

                        # 复制库文件到 libs/
                        if not args.no_libs_copy:
                            copy_libs(OPENSSL_DIR, args.libs_dir,
                                      "%s-%s" % (platform.lower(), arch),
                                      platform, arch, libtype)

                        # 打包
                        if not args.skip_package:
                            zpath = package(platform, mode, arch, libtype,
                                            OPENSSL_DIR, dist_dir, args)
                            if zpath:
                                print("  [OK] 打包: %s" % zpath)
                                results.append((combo, "ok", "zip: " + zpath))
                            else:
                                results.append((combo, "ok", "编译成功，无产物可打包"))
                        else:
                            results.append((combo, "ok", "编译成功（--skip-package）"))

    # 汇总
    print("\n" + "=" * 60)
    print("  汇总报告")
    print("=" * 60)
    if not results:
        print("  （没有执行任何编译）")
    else:
        for name, status, note in results:
            mark = "[OK]  " if status == "ok" else "[SKIP]" if status == "skip" else "[FAIL]"
            print("  %s %-52s %s" % (mark, name, note))
    print("=" * 60)

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()