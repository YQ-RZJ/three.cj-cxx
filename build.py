#!/usr/bin/env python3
"""
build.py — cxx 全库统一构建入口（linux / windows / mac 本机可用）

编排 9 组经本机验证的编译脚本（.github/scripts/*_build.py），支持全量或局部构建：

    python build.py                              # 当前平台 × 全部架构 × 全部 9 组（全量）
    python build.py --groups sdl,jolt            # 局部：只编指定组
    python build.py --arches x86_64              # 局部：只编指定架构
    python build.py --modes release              # 局部：只编 release（默认 debug,release）
    python build.py --libtypes static            # 局部：只编静态（默认 static,shared）
    python build.py --platforms ANDROID --ndk D:/ndk
    python build.py --platforms OPHM --ohos-sdk D:/OpenHarmony/23/native
    python build.py --platforms WINDOWS --arches arm64-v8a --mingw D:/llvm-mingw

平台名：LINUX / WINDOWS / OSX / ANDROID / OPHM / IOS
（组内别名自动转换：sdl 组的 OHOS/MACOS；IOS/OSX 仅允许在 macOS 主机上执行）

产物：各组脚本按自身默认输出（cxx/output、cxx/build、cxx/dist zip、cxx|上层 libs/）；
日志：cxx/logs/<group>-<platform>-<arch>.log，结束时打印汇总表。
清理产物请用 clean.py。
"""
import argparse
import os
import platform as _platform
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))            # cxx/
SCRIPTS = os.path.join(HERE, ".github", "scripts")

# 组 → 收编脚本（与 .github/scripts 对齐）
GROUPS = ["bgfx", "imgui", "sdl", "openal", "jolt", "luajit",
          "httpclient", "cjbridge", "tracy"]

# CLI 暴露的平台（组内 BSD/EMSCRIPTEN 未暴露，如需手动调用各组脚本）
CLI_PLATFORMS = ["LINUX", "WINDOWS", "OSX", "ANDROID", "OPHM", "IOS"]

# 组 → 支持的平台（自各 build.py 的 ALL_PLATFORMS 归并，已折算别名）
GROUP_PLATFORMS = {
    "bgfx":      {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "imgui":     {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "sdl":       {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "openal":    {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "jolt":      {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "luajit":    {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "httpclient":{"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "cjbridge":  {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
    "tracy":     {"LINUX", "WINDOWS", "ANDROID", "OPHM", "OSX", "IOS"},
}

# 平台别名：统一 CLI 名 → 组脚本实际接受名
PLATFORM_ALIAS = {
    "sdl": {"OPHM": "OHOS", "OSX": "MACOS"},
}

# 仅允许在 macOS 主机上执行的平台
MAC_ONLY = {"OSX", "IOS"}


def detect_host() -> str:
    s = _platform.system()
    return {"Windows": "WINDOWS", "Darwin": "OSX"}.get(s, "LINUX")


def script_path(group: str) -> str:
    return os.path.join(SCRIPTS, f"{group}_build.py")


def supported_args(group: str) -> set:
    """扫描组脚本的 add_argument，得到其支持的 CLI 选项集合（防传错参）。"""
    with open(script_path(group), encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"add_argument\(\s*\"(--[\w-]+)\"", text))


def run_group(group: str, plat: str, arch: str, args, log_dir: str) -> bool:
    """调用单组脚本；返回是否成功。"""
    cmd = [sys.executable, script_path(group),
           "--platforms", PLATFORM_ALIAS.get(group, {}).get(plat, plat),
           "--arches", arch]
    sup = supported_args(group)
    if "--modes" in sup:
        cmd += ["--modes", args.modes]
    if "--libtype" in sup:
        cmd += ["--libtype", args.libtypes]
    if "--clean" in sup and args.clean:
        cmd += ["--clean"]
    if args.ndk and "--ndk" in sup:
        cmd += ["--ndk", os.path.abspath(args.ndk)]
    if args.ohos_sdk and "--ohos-sdk" in sup:
        cmd += ["--ohos-sdk", os.path.abspath(args.ohos_sdk)]
    if args.mingw and "--mingw" in sup:
        cmd += ["--mingw", os.path.abspath(args.mingw)]
    if "--android-api" in sup:
        cmd += ["--android-api", str(args.android_api)]

    log_file = os.path.join(log_dir, f"{group}-{plat}-{arch}.log")
    env = os.environ.copy()
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    print(f"\n>>> [{group}] {plat} {arch}  (log: {os.path.relpath(log_file, HERE)})",
          flush=True)
    print(f"    $ {' '.join(os.path.relpath(c, HERE) if c.startswith(HERE) else c for c in cmd)}",
          flush=True)
    t0 = time.time()
    with open(log_file, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, cwd=HERE, env=env, stdout=log,
                              stderr=subprocess.STDOUT)
    dt = time.time() - t0
    ok = proc.returncode == 0
    print(f"<<< [{'OK' if ok else 'FAIL'}] {group} {plat} {arch}  {dt:.0f}s",
          flush=True)
    if not ok:
        # 失败时回显日志尾部便于定位
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-30:]
            print("    ---- log tail ----")
            for line in tail:
                print("    " + line.rstrip())
        except OSError:
            pass
    return ok


def main():
    host = detect_host()
    ap = argparse.ArgumentParser(
        description="cxx 全库统一构建（详见文件头 docstring）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--platforms", default=host,
                    help=f"逗号分隔，可选 {','.join(CLI_PLATFORMS)}（默认当前主机 {host}）")
    ap.add_argument("--arches", default=None,
                    help="逗号分隔：x86_64,arm64-v8a（默认仅主机原生架构）")
    ap.add_argument("--modes", default="debug,release", help="逗号分隔：debug,release")
    ap.add_argument("--libtypes", default="static,shared",
                    help="逗号分隔：static,shared（不支持的组自动忽略）")
    ap.add_argument("--groups", default=None,
                    help=f"逗号分隔，可选 {','.join(GROUPS)}（默认全部）")
    ap.add_argument("--ndk", default=None, help="Android NDK 根目录（ANDROID 平台）")
    ap.add_argument("--ohos-sdk", default=None,
                    help="OHOS SDK native 目录，如 D:/OpenHarmony/23/native（OPHM 平台）")
    ap.add_argument("--mingw", default=None,
                    help="mingw-w64 / llvm-mingw 根目录（Windows arm64 交叉用）")
    ap.add_argument("--android-api", type=int, default=24, help="Android API level")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="并行编译任务数")
    ap.add_argument("--clean", action="store_true",
                    help="编译前清空各组产物目录（透传各组 --clean）")
    args = ap.parse_args()

    plats = [p.strip().upper() for p in args.platforms.split(",") if p.strip()]
    for p in plats:
        if p not in CLI_PLATFORMS:
            sys.exit(f"[build] 未知平台: {p}（可选 {','.join(CLI_PLATFORMS)}）")

    groups = ([g.strip() for g in args.groups.split(",")] if args.groups else GROUPS)
    for g in groups:
        if g not in GROUPS:
            sys.exit(f"[build] 未知组: {g}（可选 {','.join(GROUPS)}）")

    if args.arches:
        arches = [a.strip() for a in args.arches.split(",") if a.strip()]
    else:
        # 默认主机原生架构（mac arm64 主机 → arm64-v8a，其余 x86_64）
        arches = ["arm64-v8a"] if (_platform.machine() == "arm64" and host == "OSX") \
            else ["x86_64"]

    log_dir = os.path.join(HERE, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # MAC_ONLY 平台守卫
    if any(p in MAC_ONLY for p in plats) and host != "OSX":
        bad = [p for p in plats if p in MAC_ONLY]
        print(f"[build] 警告: {','.join(bad)} 仅可在 macOS 主机上编译，已跳过", flush=True)
        plats = [p for p in plats if p not in MAC_ONLY]
        if not plats:
            sys.exit("[build] 没有可执行的平台")

    results = []
    for plat in plats:
        for arch in arches:
            for g in groups:
                if plat not in GROUP_PLATFORMS.get(g, set()):
                    print(f"[skip] {g} 不支持 {plat}", flush=True)
                    results.append((g, plat, arch, None))
                    continue
                ok = run_group(g, plat, arch, args, log_dir)
                results.append((g, plat, arch, ok))

    # ---- 汇总 ----
    print("\n" + "=" * 62)
    print(f"{'group':<12}{'platform':<10}{'arch':<12}result")
    print("-" * 62)
    fail = 0
    for g, plat, arch, ok in results:
        tag = {True: "OK", False: "FAIL", None: "skip"}[ok]
        if ok is False:
            fail += 1
        print(f"{g:<12}{plat:<10}{arch:<12}{tag}")
    print("=" * 62)
    done = [r for r in results if r[3] is not None]
    print(f"total: {len(done)} built, {fail} failed, "
          f"{len(results) - len(done)} skipped; logs in cxx/logs/")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
