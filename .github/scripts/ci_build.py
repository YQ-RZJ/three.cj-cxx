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
    python ci_build.py --platform OHOS   --arch arm64-v8a --ohos-sdk <sdk>/native
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
import shutil
import subprocess
import sys

# CI-PATCH: GitHub Windows runner 默认 cp1252 stdout，中文输出会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CXX_ROOT = os.path.dirname(os.path.dirname(HERE))          # cxx/
DIST_ROOT = os.path.join(CXX_ROOT, "dist")

# 平台 → 参与编译的组（与各 build.py 的 ALL_PLATFORMS 交集）
# 顺序即编译顺序：默认统一以 bgfx/sdl/imgui 开头（用户约定），
# imgui 依赖 bgfx/sdl 的预编译库，恰好排在其后（配合每组跑完
# 即暂存的收集策略，shared 组合的 --deps-lib 始终可用）
_BASE_GROUPS = ["bgfx", "sdl", "imgui", "httpclient", "jolt", "luajit", "openal", "tracy", "cjbridge"]
PLATFORM_GROUPS = {
    "LINUX":   list(_BASE_GROUPS),
    "WINDOWS": list(_BASE_GROUPS),
    "OSX":     list(_BASE_GROUPS),
    "ANDROID": list(_BASE_GROUPS),
    "OHOS":    list(_BASE_GROUPS),
    # IOS 与 OSX 同为 Apple 工具链（Xcode clang），各组脚本 ALL_PLATFORMS 均已
    # 声明支持 IOS，全量对齐 mac
    "IOS":     list(_BASE_GROUPS),
}

# OS 目录名（打包结构第一级）
PLATFORM_OS_DIR = {
    "LINUX": "linux", "WINDOWS": "windows", "OSX": "macos",
    "ANDROID": "android", "OHOS": "ohos", "IOS": "ios",
}

# 归包扫描目录（相对 cxx 根；collect_dist.py 递归收集库扩展名）
COLLECT_SRC_DIRS = ["output", "libs", "build"]


def run(cmd, env):
    print(f"[ci] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, env=env, cwd=CXX_ROOT)
    if r.returncode != 0:
        sys.exit(f"[ci] FAILED: {' '.join(cmd)}")


def script_supports(script: str, opt: str) -> bool:
    """扫描组脚本的 add_argument，判断其是否支持某 CLI 选项（CI-PATCH：tracy 无 --libtype 等）"""
    import re
    with open(script, encoding="utf-8") as f:
        return opt in re.findall(r"add_argument\(\s*\"(--[\w-]+)\"", f.read())


def script_allowed_libs(script: str) -> list:
    """CI-PATCH: 扫描组脚本的 _ALLOWED_LIBS 常量，得到其可选择的库名清单"""
    import re
    with open(script, encoding="utf-8") as f:
        m = re.search(r"_ALLOWED_LIBS\s*=\s*(\[[^\]]*\])", f.read())
        if not m:
            return []
        inner = m.group(1)[1:-1]    # 去掉外层方括号后再按逗号切分（否则首尾残留引号）
        return [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]


def script_arches(script: str) -> list:
    """CI-PATCH: 扫描组脚本的 ALL_ARCHES 常量，得到其支持的架构名清单。
    各组脚本架构命名不统一（bgfx/jolt 用 arm64-v8a，sdl/tracy 用 arm64），
    ci_build 需按脚本适配转发。"""
    import re
    with open(script, encoding="utf-8") as f:
        m = re.search(r"ALL_ARCHES\s*=\s*\[([^\]]*)\]", f.read())
        if not m:
            return []
        return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]


def arch_for_script(script: str, arch: str) -> str:
    """把 ci_build 的统一架构名映射为组脚本认识的架构名。
    例如统一名 arm64-v8a 在只认 arm64 的脚本（sdl/tracy）下映射为 arm64。"""
    sarches = script_arches(script)
    if not sarches or arch in sarches:
        return arch
    alt = {"arm64-v8a": "arm64", "arm64": "arm64-v8a"}.get(arch)
    return alt if alt and alt in sarches else arch


def salvage_zips(scripts_dir: str, arch: str):
    """CI-PATCH3: 每组跑完立即把新产出的 zip 挪进清理范围外的暂存区。

    各组 --clean 都会 rmtree cxx/dist/（windows x86 job 实测：9 组 zip
    全部落 cxx/dist/， salvage 扫 .github/scripts/dist/ 永远空，最终
    归包只剩最后一组产物）——zip 必须在下一组启动前抢救进 ci_deps/
    zips/<arch>/（清理范围外），归包按架构分目录收。"""
    import glob as _glob
    import shutil as _shutil
    src_dir = os.path.join(CXX_ROOT, "dist")
    if not os.path.isdir(src_dir):
        return
    dst_dir = os.path.join(CXX_ROOT, "ci_deps", "zips", arch)
    os.makedirs(dst_dir, exist_ok=True)
    for zp in _glob.glob(os.path.join(src_dir, "*.zip")):
        # 保守过滤：文件名含其它架构标记的 zip 不属于本轮（防多架构
        # 残留混入），无架构标记或含当前架构标记的都收
        base = os.path.basename(zp)
        other = {"arm64-v8a": "x86_64", "x86_64": "arm64-v8a"}.get(arch)
        if other and other in base and arch not in base:
            continue
        _shutil.move(zp, os.path.join(dst_dir, base))
    n = len(_glob.glob(os.path.join(dst_dir, "*.zip")))
    print(f"[ci] salvage zips -> ci_deps/zips/{arch}/ (累计 {n} 个)", flush=True)


def stage_imgui_deps(cxx_root: str, arch: str) -> str:
    """收集本轮已编出的 SDL3/bgfx 等库文件到暂存目录，供 imgui shared
    构建作为 --deps-lib 使用（imgui 排在 sdl/bgfx 之后编译）。

    CI-PATCH: 暂存目录必须放在 cxx 根下的 ci_deps/——不能放 output/、
    build/ 或 dist/，imgui_build.py 的 --clean 会 rmtree 这三个目录，
    暂存库会被刚拷进去就删掉（Windows/macOS 都踩过的时序坑）。

    CI-PATCH2: 只收集 imgui 真正依赖的库家族（SDL3 / bgfx 家族），
    其余 .a（如 httpclient 的 libtlsbridge.a）不掺入——选择性构建只跑
    imgui 组时，残留的无关库会被误当有效依赖，shared 链接因缺
    bgfx::/SDL 符号失败（macOS 实测）。libbgfx 或 libSDL3 任一缺失
    时返回空串：imgui 会干净地跳过 shared 组合而非带残缺依赖硬链。"""
    import glob
    import struct
    stage = os.path.join(cxx_root, "ci_deps", arch)
    os.makedirs(stage, exist_ok=True)
    dep_stems = ("libbgfx", "libbx", "libbimg", "libSDL3", "libsdl3",
                 "bgfx", "bx", "bimg", "SDL3", "sdl3")

    # CI-PATCH4: 机器架构校验 —— 打包规则调整后收集源里可能混入异架构
    # 库（Windows arm64-v8a 实测：sdl 组产出的 x64 libSDL3.dll.a 混入，
    # imgui shared 链接报 "machine type x64 conflicts with arm64"）。
    # PE/COFF：读 PE 头 machine 字段；ELF/Mach-O：读魔数后 e_machine/cputype。
    # 校验失败的文件跳过（视为本轮产物异常，不污染依赖）。
    def _lib_machine(path):
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096)
        except OSError:
            return None
        if head[:4] == b"\x7fELF":          # ELF
            if len(head) < 20:
                return None
            em = struct.unpack_from("<H", head, 18)[0]
            return {62: "x86_64", 183: "arm64", 40: "arm32"}.get(em)
        if head[:2] == b"MZ":               # PE/COFF（.lib/.dll.a）
            off = struct.unpack_from("<I", head, 0x3C)[0]
            # PE 签名可能不在前 4K（极端 stub），读不到按未知放行
            with open(path, "rb") as fh:
                fh.seek(off)
                if fh.read(4) != b"PE\0\0":
                    return None
                machine = struct.unpack("<H", fh.read(2))[0]
            return {0x8664: "x86_64", 0xAA64: "arm64", 0x14C: "x86",
                    0x1C4: "arm32"}.get(machine)
        if head[:8] == b"!<arch>\n":        # GNU ar 归档（dlltool 导入库）
            # CI-PATCH5: dlltool/lld 的导入库是 ar 容器，整体无 MZ 头 ——
            # 上一版按"未知格式放行"导致 x64 libSDL3.dll.a 混入（CI 复测）。
            # 遍历成员（60 字节头 + 数据，2 字节对齐），读第一个可判定
            # 成员的机器架构：COFF 对象头 2 字节即 machine；短导入对象
            # Sig1=0/Sig2=0xFFFF，machine 在偏移 6。
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                return None
            machines = {0x8664: "x86_64", 0xAA64: "arm64",
                        0x14C: "x86", 0x1C4: "arm32"}
            off = 8
            while off + 60 <= len(data):
                size_field = data[off + 48:off + 58].strip()
                if not size_field.isdigit():
                    break
                sz = int(size_field)
                # 跳过符号表/长名表成员（名字为 "/"、"//"、"/SYM64/"）——
                # 其内容是索引数据而非 COFF 对象，按对象头读前 2 字节
                # 可能撞上 0x8664/0xAA64 造成误判（如 GNU ar 大端符号计数
                # 恰为 0x6486 时小端读出 0x8664）
                mname = data[off:off + 16].strip()
                if mname in (b"/", b"//") or mname.startswith(b"/SYM64"):
                    off += 60 + sz + (sz & 1)
                    continue
                body = data[off + 60:off + 60 + sz]
                mm = None
                if body[:2] == b"MZ":
                    o = struct.unpack_from("<I", body, 0x3C)[0]
                    if o + 6 <= len(body) and body[o:o + 4] == b"PE\x00\x00":
                        mm = machines.get(struct.unpack_from("<H", body, o + 4)[0])
                elif len(body) >= 8 and body[2:4] == b"\xff\xff":
                    mm = machines.get(struct.unpack_from("<H", body, 6)[0])
                elif len(body) >= 2:
                    mm = machines.get(struct.unpack_from("<H", body, 0)[0])
                if mm:
                    return mm
                off += 60 + sz + (sz & 1)
            return None
        if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                        b"\xfe\xed\xfa\xcf", b"\xbe\xba\xfe\xca"):
            return "macho"
        return None    # 未知格式（纯文本/空文件等）——放行

    # 目标架构 → 期望机器标识（用于 PE/ELF 白名单）
    want = "arm64" if "arm64" in arch else "x86_64"

    # 暂存区自清理：上一轮残留的异架构库（ci_deps/ 不在任何 --clean
    # 范围内，错误文件会跨轮存活，必须在此主动清除）
    if os.path.isdir(stage):
        for old in os.listdir(stage):
            m = _lib_machine(os.path.join(stage, old))
            if m is not None and m not in (want, "macho"):
                print("[ci] WARN stage_imgui_deps: 清除残留异架构库 %s "
                      "(machine=%s, want=%s)" % (old, m, want), flush=True)
                os.remove(os.path.join(stage, old))

    for src_root in ("output", "build"):
        base = os.path.join(cxx_root, src_root)
        if not os.path.isdir(base):
            continue
        for pattern in ("*.a", "*.lib", "*.so", "*.dylib"):
            for f in glob.glob(os.path.join(base, "**", pattern), recursive=True):
                stem = os.path.basename(f)
                if not any(s.lower() in stem.lower() for s in dep_stems):
                    continue
                m = _lib_machine(f)
                if m is not None and m not in (want, "macho"):
                    print("[ci] WARN stage_imgui_deps: 跳过异架构库 %s "
                          "(machine=%s, want=%s)" % (stem, m, want), flush=True)
                    continue
                dst = os.path.join(stage, stem)
                if not os.path.isfile(dst):
                    shutil.copy2(f, dst)
    # CI-PATCH3: 以暂存目录的最终内容判断依赖完整性，而非本次新增——
    # 每组跑完即暂存（增量）时，imgui 启动前文件均已存在、本次新增为 0，
    # 按新增判断会误报"依赖不全"导致 shared 被跳过（mock 自检实测）。
    staged = os.listdir(stage)
    if not staged:
        return ""
    has_bgfx = any("bgfx" in s.lower() for s in staged)
    has_sdl = any("sdl3" in s.lower() for s in staged)
    if not (has_bgfx and has_sdl):
        print("[ci] WARN stage_imgui_deps: 依赖不全（bgfx=%s sdl3=%s），"
              "imgui shared 将被跳过" % (has_bgfx, has_sdl), flush=True)
        return ""
    return stage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True,
                    choices=sorted(PLATFORM_GROUPS.keys()))
    ap.add_argument("--arch", required=True, help="x86_64 / arm64-v8a")
    ap.add_argument("--ndk", default=None, help="Android NDK 根目录")
    ap.add_argument("--ohos-sdk", default=None, help="OHOS SDK native 目录")
    ap.add_argument("--mingw", default=None, help="mingw-w64 / llvm-mingw 根目录（Windows 可选）")
    ap.add_argument("--modes", default=None,
                    help="逗号分隔：debug,release（缺省=各组脚本默认全编排）")
    ap.add_argument("--libtypes", default=None,
                    help="逗号分隔：static,shared（缺省=各组脚本默认全编排）")
    # CI-PATCH: 选择性构建——组级按序过滤 + 库级全局清单（分发到各组，
    # 组收到 0 个自己的库时整组跳过）；缺省=全量
    ap.add_argument("--groups", default=None,
                    help="逗号分隔的组清单（按序）：bgfx,httpclient,imgui,jolt,luajit,openal,sdl,tracy,cjbridge")
    ap.add_argument("--libs", default=None,
                    help="逗号分隔的库清单（按序，全局）：如 bx,bgfx,openssl,tlsbridge")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    env = os.environ.copy()
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    # CI-PATCH: Windows runner 默认 cp1252，子进程中文输出统一强制 UTF-8
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if args.ndk:
        env["ANDROID_NDK_HOME"] = os.path.abspath(args.ndk)
    if args.ohos_sdk:
        env["OHOS_SDK_NATIVE"] = os.path.abspath(args.ohos_sdk)

    plat = args.platform
    os_dir = PLATFORM_OS_DIR[plat]

    # OHOS static 特例需要 SDL3.so（sdl 组 shared 产物），编译前先记录占位
    sdl_so_hint = os.path.join(DIST_ROOT, os_dir, args.arch, "shared", "libSDL3.so")

    # CI-PATCH: --groups 组级按序过滤（缺省=全量，顺序以 --groups 为准）
    all_groups = PLATFORM_GROUPS[plat]
    if args.groups:
        wanted_groups = [g.strip() for g in args.groups.split(",") if g.strip()]
        unknown = [g for g in wanted_groups if g not in all_groups]
        if unknown:
            sys.exit(f"[ci] --groups 未知组名: {','.join(unknown)}（可选 {','.join(all_groups)}）")
        groups = [g for g in wanted_groups if g in all_groups]
        if not groups:
            sys.exit(f"[ci] --groups 无本平台（{plat}）可编的组")
    else:
        groups = all_groups

    # CI-PATCH: --libs 全局库清单（缺省=全量）。
    # 全局校验未知库名 + 按组分发：组收到 0 个自己的库时整组跳过。
    if args.libs:
        global_wanted = [s.strip().lower() for s in args.libs.split(",") if s.strip()]
        known = {l for g in all_groups
                 for l in script_allowed_libs(os.path.join(HERE, f"{g}_build.py"))}
        unknown = [l for l in global_wanted if l not in known]
        if unknown:
            sys.exit(f"[ci] --libs 未知库名: {','.join(unknown)}（可选 {','.join(sorted(known))}）")
    else:
        global_wanted = None    # None = 全量，不传 --libs

    for group in groups:
        script = os.path.join(HERE, f"{group}_build.py")
        # CI-PATCH: 各组脚本架构命名不统一（bgfx/jolt 用 arm64-v8a，
        # sdl/tracy 用 arm64），按脚本适配转发
        script_arch = arch_for_script(script, args.arch)
        cmd = [sys.executable, script,
               "--platforms", plat,
               "--arches", script_arch,
               "--clean"]
        if args.ndk:
            cmd += ["--ndk", os.path.abspath(args.ndk)]
        if args.ohos_sdk:
            cmd += ["--ohos-sdk", os.path.abspath(args.ohos_sdk)]
        # CI-PATCH: --mingw 仅转发给支持该参数的组脚本（sdl_build.py 等不认识
        # --mingw，无条件转发会导致 argparse 报错、整组失败中断）
        if args.mingw and script_supports(script, "--mingw"):
            cmd += ["--mingw", os.path.abspath(args.mingw)]
        if args.modes and script_supports(script, "--modes"):
            cmd += ["--modes", args.modes]
        if args.libtypes and script_supports(script, "--libtype"):
            cmd += ["--libtype", args.libtypes]
        # --libs 按组分发（组脚本自行校验；只传属于自己的库，保持全局顺序）
        if global_wanted is not None:
            allowed = script_allowed_libs(script)
            subset = [l for l in global_wanted if l in allowed]
            if not subset:
                print(f"[ci] skip {group}（--libs 未包含本组库）", flush=True)
                continue
            cmd += ["--libs", ",".join(subset)]
        # CI-PATCH: imgui shared 构建需要 SDL3/bgfx 预编译库目录。
        # 各组跑完后立即暂存（见下），此处直接复用累计的暂存目录；
        # 若暂存为空再现场收集一次兜底（跳过前组时仍能收到）。
        if group == "imgui" and script_supports(script, "--deps-lib"):
            stage = stage_imgui_deps(CXX_ROOT, args.arch)
            if stage:
                cmd += ["--deps-lib", stage]
            else:
                print("[ci] WARN imgui: 未收集到依赖库产物，shared 组合将被跳过", flush=True)
        run(cmd, env)
        # CI-PATCH: 每组跑完立即暂存依赖库 —— 后续组的 --clean 会清空
        # 共享的 build/、dist/ 顶层目录，等 imgui 启动前才收集会两手空空
        # （Linux 实测：httpclient 的 --clean 删掉 bgfx 产物）。累计收集，
        # 暂存目录在 cxx 根下 ci_deps/（不在各脚本 --clean 的范围内）。
        if group != "imgui":
            stage_imgui_deps(CXX_ROOT, args.arch)
        # CI-PATCH3: 每组跑完立即抢救 zip —— 8 组的 DIST_DIR 都是共享的
        # .github/scripts/dist/，下一组 --clean 会 rmtree 它（macOS 实测：
        # 最终 zip 只剩最后两组的产物）。挪进清理范围外的 ci_deps/zips/
        # 累计暂存，归包时从这里收。
        salvage_zips(CXX_ROOT, args.arch)

    # ---- 归包：dist/<os>/<arch>/{static,shared} ----
    # CI-PATCH: 方案 A——从各组 *_build.py 产出的 zip 归包（zip 在各组跑完
    # 即持久化，不受后续组 --clean 影响；旧 --src 方式在多组互删后只剩
    # 最后一组的产物，归包结果残缺）。zip 源：ci_deps/zips/ 暂存区（每组
    # 跑完立即抢救）+ bgfx 的 cxx/dist/（其 DIST_DIR=ROOT/dist，无共享
    # 清理问题，兜底直收）。
    salvage_dir = os.path.join(CXX_ROOT, "ci_deps", "zips", args.arch)
    collect = [sys.executable, os.path.join(HERE, "collect_dist.py"),
               "--os", os_dir, "--arch", args.arch,
               "--out", DIST_ROOT, "--clean",
               "--zip", os.path.join(salvage_dir, "*.zip"),
               "--zip", os.path.join(DIST_ROOT, "*.zip")]
    # 兼容保留：目录源作为兜底（zip 缺失的组若目录还在则仍能收集）
    for d in COLLECT_SRC_DIRS:
        p = os.path.join(CXX_ROOT, d)
        if os.path.isdir(p):
            collect += ["--src", p]
    # OHOS：static 内附带对应架构 SDL3 动态库（若本轮已产出）
    if plat == "OHOS" and os.path.isfile(sdl_so_hint):
        collect += ["--sdl-so", sdl_so_hint]
    run(collect, env)
    print(f"[ci] DONE {plat} {args.arch} -> dist/{os_dir}/{args.arch}/{{static,shared}}")

    # ---- 最终压缩包：每个 <mode>×<libtype> 组合一个包（用户约定）----
    # 命名  native-libs-<os>-<arch>-<mode>-<libtype>.<ext>
    # 包内  ./<os>/<arch>/<mode>/<libtype>/...
    # 格式  windows=.zip，其余（linux/macos/android/ohos/ios）=.tar.gz
    # 归包树为 dist/<os>/<arch>/<mode>/<libtype>/（collect_dist CI-PATCH5）
    src_tree = os.path.join(DIST_ROOT, os_dir)
    if not os.path.isdir(src_tree):
        print(f"[ci] WARN 未找到归包目录 {src_tree}，跳过最终打包")
        return
    import tarfile
    import zipfile as _zipfile
    made = 0
    for mode in ("release", "debug"):
        for libtype in ("static", "shared"):
            combo_src = os.path.join(src_tree, args.arch, mode, libtype)
            if not os.path.isdir(combo_src) or not os.listdir(combo_src):
                continue  # 该组合本轮未编译（如 --modes release 单模式）
            if plat == "WINDOWS":
                final = os.path.join(
                    DIST_ROOT, f"native-libs-windows-{args.arch}-{mode}-{libtype}.zip")
                if os.path.isfile(final):
                    os.remove(final)
                with _zipfile.ZipFile(final, "w", _zipfile.ZIP_DEFLATED) as z:
                    for root, _dirs, files in os.walk(combo_src):
                        for f in files:
                            full = os.path.join(root, f)
                            # 包内路径 ./<os>/<arch>/<mode>/<libtype>/<file>
                            z.write(full, os.path.relpath(full, DIST_ROOT))
            else:
                final = os.path.join(
                    DIST_ROOT,
                    f"native-libs-{os_dir}-{args.arch}-{mode}-{libtype}.tar.gz")
                if os.path.isfile(final):
                    os.remove(final)
                with tarfile.open(final, "w:gz") as t:
                    # arcname 对齐包内 ./<os>/<arch>/<mode>/<libtype>
                    t.add(combo_src, arcname=os.path.join(
                        os_dir, args.arch, mode, libtype))
            made += 1
            print(f"[ci] 最终压缩包: {final}")
    if made == 0:
        print("[ci] WARN 归包目录为空，未产出任何最终压缩包")


if __name__ == "__main__":
    main()
