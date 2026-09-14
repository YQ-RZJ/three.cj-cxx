#!/usr/bin/env python3
"""
collect_dist.py — CI 统一归包脚本

把各 build.py 的编译产物归集到统一打包结构：

    <out>/<os>/<arch>/<static|shared>/   # 所有产物平铺（同 three/libs 风格）

特例（OHOS）：static 目录内额外带一个 <arch>/libSDL3.so 子目录
（对齐 three/test/ohos/base/entry/libs 布局：静态库平铺 + 架构目录下 SDL3 动态库）。

用法：
    python collect_dist.py --os linux --arch x86_64 --out dist \
        --src cxx/output/build-x86_64-release/libs --src ... [--src ...]

    # CI-PATCH: 从各组 *_build.py 产出的 zip 归包（对抗组间 --clean 互删，
    # zip 在各组跑完即持久化）——解包后按同样的分类规则平铺：
    python collect_dist.py --os ohos --arch arm64-v8a --out dist \
        --zip .github/scripts/dist/bgfx4cj-*.zip --zip ... [--src ...]

    # OHOS static 特例：
    python collect_dist.py --os ohos --arch arm64-v8a --out dist --libtype static \
        --src ... --sdl-so <path>/libSDL3.so

分类规则：.a/.lib → static；.so/.dll/.dylib → shared；
--libtype 指定时强制全部归入该类型（供只产出一种链接形态的库使用）。
"""
import argparse
import glob
import os
import shutil
import zipfile

STATIC_EXT = {".a", ".lib"}
SHARED_EXT = {".so", ".dll", ".dylib"}
# 导入库/调试伴随文件，跟随其主库类型归档
SIDE_EXT = {".pdb", ".exp", ".def"}


def classify(name: str, forced: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if forced in ("static", "shared"):
        return forced
    if ext in STATIC_EXT:
        return "static"
    if ext in SHARED_EXT:
        return "shared"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", dest="os_name", required=True,
                    help="目标系统目录名：linux/windows/macos/android/ohos/ios")
    ap.add_argument("--arch", required=True, help="架构目录名：x86_64 / arm64-v8a")
    ap.add_argument("--out", default="dist", help="归包根目录（默认 dist/）")
    ap.add_argument("--libtype", choices=["static", "shared"], default=None,
                    help="强制分类（无扩展名可判别时使用）")
    ap.add_argument("--src", action="append", default=[],
                    help="产物来源目录，可多次指定；递归收集其中的库文件")
    ap.add_argument("--zip", action="append", default=[],
                    help="CI-PATCH: 各组 *_build.py 产出的 zip（支持 glob），"
                         "可多次指定；解包后按同样分类规则平铺（对抗组间 --clean 互删）")
    ap.add_argument("--sdl-so", default=None,
                    help="OHOS 特例：把该 libSDL3.so 复制到 static/<arch>/ 子目录")
    ap.add_argument("--clean", action="store_true", help="先清空目标系统目录")
    args = ap.parse_args()

    target_root = os.path.join(args.out, args.os_name)
    if args.clean and os.path.isdir(target_root):
        shutil.rmtree(target_root)
    os.makedirs(target_root, exist_ok=True)

    collected = 0

    # ---- CI-PATCH: 从各组产出的 zip 归包（方案 A：对抗组间 --clean 互删）----
    # 子 zip 内部布局（各组 package() 约定）：<name>/include/** + <name>/<库文件>
    # 解包到临时目录后走与 --src 完全相同的分类平铺逻辑。
    zip_paths = []
    for pattern in args.zip:
        matched = sorted(glob.glob(pattern))
        if not matched:
            print(f"[collect] WARN zip glob 无匹配: {pattern}")
        zip_paths += matched
    tmp_unzip = os.path.join(args.out, "_unzip_tmp")
    for zp in zip_paths:
        if not os.path.isfile(zp):
            print(f"[collect] skip missing zip: {zp}")
            continue
        try:
            with zipfile.ZipFile(zp) as z:
                z.extractall(tmp_unzip)
        except zipfile.BadZipFile:
            print(f"[collect] WARN 损坏的 zip，跳过: {zp}")
            continue
    # 解包出的目录并入收集源（与 --src 同路处理）
    if os.path.isdir(tmp_unzip):
        args.src.append(tmp_unzip)

    for src in args.src:
        if not os.path.isdir(src):
            print(f"[collect] skip missing: {src}")
            continue
        for root, _dirs, files in os.walk(src):
            for fn in files:
                kind = classify(fn, args.libtype or "")
                ext = os.path.splitext(fn)[1].lower()
                if not kind and ext not in SIDE_EXT:
                    continue
                sub = "static" if kind == "static" or (not kind and ext in SIDE_EXT
                                                       and classify(fn.replace(".pdb", ".a").replace(".exp", ".a"), "") == "static") else "shared"
                dest_dir = os.path.join(target_root, args.arch, sub)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, fn)
                src_file = os.path.join(root, fn)
                if os.path.abspath(src_file) != os.path.abspath(dest):
                    shutil.copy2(src_file, dest)
                collected += 1
    print(f"[collect] {collected} files -> {target_root}/{args.arch}/{{static,shared}}")

    # CI-PATCH: 清理解包临时目录
    if os.path.isdir(tmp_unzip):
        shutil.rmtree(tmp_unzip, ignore_errors=True)

    # OHOS 特例：static/<arch>/libSDL3.so
    if args.sdl_so:
        dest = os.path.join(target_root, args.arch, "static", args.arch)
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(args.sdl_so, os.path.join(dest, os.path.basename(args.sdl_so)))
        print(f"[collect] SDL3 so -> {dest}")


if __name__ == "__main__":
    main()
