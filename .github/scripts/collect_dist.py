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
# CI-PATCH2: 归包白名单——只收库产物与链接副产物，组 zip 里的头文件/
# 源码/工具脚本一律不入（shared/ 混 674 个 .h + 28 个 .cpp 的实测教训）
LIB_ARTIFACT_EXTS = tuple(STATIC_EXT | SHARED_EXT | SIDE_EXT)


def classify(name: str, forced: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    low = name.lower()
    if forced in ("static", "shared"):
        return forced
    # CI-PATCH: MinGW 导入库（libfoo.dll.a）是链接期伴随 DLL 的导入库，
    # 消费 shared 链接用——归 shared 而非按 .a 误入 static
    # （windows job 实测 libdlbridge.dll.a / librequirecj_ffi.dll.a 落错）
    if low.endswith(".dll.a") or low.endswith(".dll.lib"):
        return "shared"
    # CI-PATCH4: cangjie-runtime-stub.lib 是 requireCJLib 的运行时导入桩
    # （dlltool/lib 由 cangjie-runtime-stub.def 生成，InitCJRuntime 等符号
    # 加载期由宿主侧仓颉运行时 DLL 解析）——只随 shared 动态库消费，
    # 静态链接用不到它；按 .lib 归 static 是落错（windows arm64 job 实测
    # zip 里 static/ 下孤零零只有这一个文件，shared/ 38 个）
    if "runtime-stub" in low or "runtime_stub" in low:
        return "shared"
    if ext in STATIC_EXT:
        return "static"
    if ext in SHARED_EXT:
        # CI-PATCH6: Apple 平台（ios/macos）不消费 .so——luajit 等脚本
        # 残留的 Linux 命名产物混进 Apple 包（macos job 实测
        # libluajit.so）。归包侧兜底拒绝（source_root 末段含平台名时
        # 由调用方传入；此处按 --os 判定）。
        if getattr(main, "_apple_os", False) and ext == ".so":
            return ""
        return "shared"
    # CI-PATCH6: .pdb/.exp/.def 调试/链接副产物显式归 shared（跟随主
    # DLL 消费）——旧实现靠 main() 的 "kind if kind else shared" 兜底，
    # 该兜底已改为拒绝即跳过，副产物必须在此给出明确分类。
    if ext in SIDE_EXT:
        return "shared"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", dest="os_name", required=True,
                    help="目标系统目录名：linux/windows/macos/android/ohos/ios")
    ap.add_argument("--arch", required=True, help="架构目录名：x86_64 / arm64-v8a")
    ap.add_argument("--out", default="dist", help="归包根目录（默认 dist/）")
    ap.add_argument("--libtype", default=None,
                    # CI-PATCH: 允许多值（CI 双模式传 static,shared）——旧
                    # choices=["static","shared"] 会 argparse 报 invalid
                    # choice 直接退出；歧义消解只看是否含 "shared"
                    help="库类型：static / shared，可逗号分隔多值")
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
    # CI-PATCH6: Apple 平台标志——classify 用它拒绝 .so 混入 ios/macos 包
    main._apple_os = args.os_name in ("ios", "macos")
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
        # CI-PATCH: 按 zip 名中的库类型标记分子目录解包——组脚本命名约定
        # <name>-<arch>-<mode>-<libtype>-<toolchain>.zip。MSVC 的 .lib 歧义
        # （导入库 vs 真静态库扩展名相同）靠这个 per-file forced 消解：
        # shared zip 里的 .lib 是 DLL 导入库，归 shared。
        # CI-PATCH5: mode（debug/release）同样从 zip 名解析，解包到
        # tmp_unzip/<mode>/<libtype>/ 两层——walk 时按路径段派生，
        # 归包结构变为 <arch>/<mode>/<libtype>（用户约定的四元组拆包）。
        base = os.path.basename(zp).lower()
        if "-static-" in base or base.endswith("-static.zip"):
            sub = "static"
        elif "-shared-" in base or base.endswith("-shared.zip"):
            sub = "shared"
        else:
            sub = "plain"
        # mode 段：zip 名中 -debug- / -release- 标记，缺省 release
        if "-debug-" in base or base.endswith("-debug.zip"):
            mode_seg = "debug"
        else:
            mode_seg = "release"
        try:
            with zipfile.ZipFile(zp) as z:
                z.extractall(os.path.join(tmp_unzip, mode_seg, sub))
        except zipfile.BadZipFile:
            print(f"[collect] WARN 损坏的 zip，跳过: {zp}")
            continue
    # 解包出的目录并入收集源（与 --src 同路处理）
    # CI-PATCH5: 用户约定的最终打包结构按 mode 分层——
    #   <out>/<os>/<arch>/<debug|release>/<static|shared>/
    # 组脚本 zip 名约定 <name>-<arch>-<mode>-<libtype>-<toolchain>.zip
    # 同时携带 mode 与 libtype，解包时一并解析，mode 未知回落 release。
    # forced 只提供 libtype 消解 .lib 歧义；mode 由 source_root 末段
    # （debug/release）注入 dest_dir。
    srcs = []
    if os.path.isdir(tmp_unzip):
        srcs.append(tmp_unzip)
        args.src.append(tmp_unzip)

    for src in args.src:
        if not os.path.isdir(src):
            print(f"[collect] skip missing: {src}")
            continue
        # CI-PATCH: 来自 zip 解包的文件按其子目录派生分类——
        # 路径段形如 <mode>/<libtype>/...（CI-PATCH5：mode 层 +
        # static/shared/plain 层）。libtype 层消解 .lib 的扩展名歧义
        # （导入库 vs 真静态库）；.exp/.pdb 副产物跟随所在 zip 的库类型。
        # mode 层决定归包目录（debug/release），--src 直连目录无 mode
        # 层时归 release。
        for root, _dirs, files in os.walk(src):
            forced = ""
            mode = "release"
            rel = os.path.relpath(root, src).replace("\\", "/").lower()
            segs = [s for s in rel.split("/") if s]
            if segs and segs[0] in ("debug", "release"):
                mode = segs[0]
                segs = segs[1:]
            if "static" in segs:
                forced = "static"
            elif "shared" in segs:
                forced = "shared"
            for fn in files:
                low = fn.lower()
                # CI-PATCH2: 只收库产物与链接副产物——组 zip 里的头文件/
                # 源码/工具脚本（.h/.hpp/.cpp/.lua/.f90/...）一律不入归包
                # （上一版把 args.libtype 当全局 forced，shared 配置下
                # 674 个 .h + 28 个 .cpp 全部混进 shared/，windows job
                # 实测）；args.libtype 只用于消解 .lib 的歧义。
                if not low.endswith(LIB_ARTIFACT_EXTS):
                    continue
                kind = classify(fn, forced)
                if not kind and low.endswith(".lib"):
                    # CI-PATCH3: .lib 歧义消解兼容多值 libtype——CI 双模式
                    # 跑 --libtype static,shared 时旧判断 in ("static",
                    # "shared") 不命中，stub.lib 等导入库回落 static 落错
                    # （windows job 实测）；含 shared 即按 shared（PE 上
                    # .lib 主流是 DLL 导入库）
                    if "shared" in (args.libtype or ""):
                        kind = "shared"
                    elif args.libtype == "static":
                        kind = "static"
                # CI-PATCH6: 明确拒绝（classify 返回 "" 且无 .lib 歧义可
                # 消解，如 Apple 平台的 .so 残留）必须跳过——不能用
                # "kind if kind else shared" 兜底，那会把被拒文件复活
                # 进 shared（端到端自检实测）。
                if not kind:
                    print(f"[collect] WARN 拒绝归包 {fn}（平台不消费该形态）")
                    continue
                sub = kind
                # CI-PATCH5: 归包目录带 mode 层 —— <arch>/<mode>/<libtype>
                dest_dir = os.path.join(target_root, args.arch, mode, sub)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, fn)
                src_file = os.path.join(root, fn)
                if os.path.abspath(src_file) != os.path.abspath(dest):
                    shutil.copy2(src_file, dest)
                collected += 1
    print(f"[collect] {collected} files -> {target_root}/{args.arch}/{{debug,release}}/{{static,shared}}")

    # CI-PATCH: 清理解包临时目录
    if os.path.isdir(tmp_unzip):
        shutil.rmtree(tmp_unzip, ignore_errors=True)

    # OHOS 特例：<arch>/<mode>/static/<arch>/libSDL3.so
    if args.sdl_so:
        for m in ("release", "debug"):
            dest = os.path.join(target_root, args.arch, m, "static", args.arch)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(args.sdl_so, os.path.join(dest, os.path.basename(args.sdl_so)))
            print(f"[collect] SDL3 so -> {dest}")


if __name__ == "__main__":
    main()
