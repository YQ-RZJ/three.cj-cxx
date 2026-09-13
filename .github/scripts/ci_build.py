#!/usr/bin/env python3
"""
ci_build.py — GitHub Actions 统一驱动脚本

按平台编排 9 组（22 个库）经本机验证的 build.py，全部产物经 collect_dist.py
归集为统一打包结构：

    dist/<os>/<arch>/{static,shared}/*          # 产物平铺（同 three/libs）
    dist/ohos/<arch>/static/<arch>/libSDL3.so   # OHOS static 特例

用法：
    python ci_build.py --platform LINUX  --arch x86_64
    python ci_build.py --platform ANDROID --arch arm64-v8a --ndk $ANDROID_NDK_HOME
    python ci_build.py --platform OPHM   --arch arm64-v8a --ohos-sdk <sdk>/native
    python ci_build.py --platform OSX    --arch arm64-v8a
    python ci_build.py --platform IOS    --arch arm64-v8a

说明：
- 每组 build.py 内部已按 模式(debug/release) × 链接(static/shared) 全编排，
  CI 侧按架构循环调用（--arches 单架构 + --clean 隔离，避免跨架构污染归包）。
- 组 → 平台 支持矩阵与各 build.py 的 ALL_PLATFORMS 对齐，不支持的平台自动跳过。
- Windows 工具链优先 mingw-w64（PATH 探测），失败自动回退 msvc（本地已验证）。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CXX_ROOT = os.path.dirname(os.path.dirname(HERE))          # cxx/
DIST_ROOT = os.path.join(CXX_ROOT, "dist")

# 平台 → 参与编译的组（与各 build.py 的 ALL_PLATFORMS 交集）
PLATFORM_GROUPS = {
    "LINUX":   ["bgfx", "httpclient", "imgui", "jolt", "luajit", "openal", "sdl", "tracy", "cjbridge"],
    "WINDOWS": ["bgfx", "httpclient", "imgui", "jolt", "luajit", "openal", "sdl", "tracy", "cjbridge"],
    "OSX":     ["bgfx", "httpclient", "imgui", "jolt", "luajit", "openal", "sdl", "tracy", "cjbridge"],
    "ANDROID": ["bgfx", "httpclient", "imgui", "jolt", "luajit", "openal", "sdl", "tracy", "cjbridge"],
    "OPHM":    ["bgfx", "httpclient", "imgui", "jolt", "luajit", "openal", "sdl", "tracy", "cjbridge"],
    "IOS":     ["tracy"],
}

# OS 目录名（打包结构第一级）
PLATFORM_OS_DIR = {
    "LINUX": "linux", "WINDOWS": "windows", "OSX": "macos",
    "ANDROID": "android", "OPHM": "ohos", "IOS": "ios",
}

# 归包扫描目录（相对 cxx 根；collect_dist.py 递归收集库扩展名）
COLLECT_SRC_DIRS = ["output", "libs", "build"]


def run(cmd, env):
    print(f"[ci] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, env=env, cwd=CXX_ROOT)
    if r.returncode != 0:
        sys.exit(f"[ci] FAILED: {' '.join(cmd)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True,
                    choices=sorted(PLATFORM_GROUPS.keys()))
    ap.add_argument("--arch", required=True, help="x86_64 / arm64-v8a")
    ap.add_argument("--ndk", default=None, help="Android NDK 根目录")
    ap.add_argument("--ohos-sdk", default=None, help="OHOS SDK native 目录")
    ap.add_argument("--mingw", default=None, help="mingw-w64 / llvm-mingw 根目录（Windows 可选）")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    env = os.environ.copy()
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    if args.ndk:
        env["ANDROID_NDK_HOME"] = os.path.abspath(args.ndk)
    if args.ohos_sdk:
        env["OHOS_SDK_NATIVE"] = os.path.abspath(args.ohos_sdk)

    plat = args.platform
    os_dir = PLATFORM_OS_DIR[plat]

    # OHOS static 特例需要 SDL3.so（sdl 组 shared 产物），编译前先记录占位
    sdl_so_hint = os.path.join(DIST_ROOT, os_dir, args.arch, "shared", "libSDL3.so")

    for group in PLATFORM_GROUPS[plat]:
        script = os.path.join(HERE, f"{group}_build.py")
        cmd = [sys.executable, script,
               "--platforms", plat,
               "--arches", args.arch,
               "--clean"]
        if args.ndk:
            cmd += ["--ndk", os.path.abspath(args.ndk)]
        if args.ohos_sdk:
            cmd += ["--ohos-sdk", os.path.abspath(args.ohos_sdk)]
        if args.mingw:
            cmd += ["--mingw", os.path.abspath(args.mingw)]
        run(cmd, env)

    # ---- 归包：dist/<os>/<arch>/{static,shared} ----
    srcs = []
    for d in COLLECT_SRC_DIRS:
        p = os.path.join(CXX_ROOT, d)
        if os.path.isdir(p):
            srcs += ["--src", p]
    collect = [sys.executable, os.path.join(HERE, "collect_dist.py"),
               "--os", os_dir, "--arch", args.arch,
               "--out", DIST_ROOT, "--clean"] + srcs
    # OHOS：static 内附带对应架构 SDL3 动态库（若本轮已产出）
    if plat == "OPHM" and os.path.isfile(sdl_so_hint):
        collect += ["--sdl-so", sdl_so_hint]
    run(collect, env)
    print(f"[ci] DONE {plat} {args.arch} -> dist/{os_dir}/{args.arch}/{{static,shared}}")


if __name__ == "__main__":
    main()
