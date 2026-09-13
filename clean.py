#!/usr/bin/env python3
"""
clean.py — cxx 全库产物清理

删除全量构建产生的中间目录与输出（与 build.py 的产物约定对应）：

    cxx/output/            各组 cmake/xmake 构建产物根（bgfx/imgui/jolt/openal/cjbridge/tracy…）
    cxx/build/             构建中间产物（httpclient/tlsbridge、sdl、openssl 等）
    cxx/dist/              各组 zip 与日志
    cxx/logs/              build.py 的运行日志
    cxx/libs/              各组拷入的仓颉侧链接库（jolt/cjbridge 组）

用法：
    python clean.py               # 交互确认后清理上述全部目录
    python clean.py -y            # 免确认
    python clean.py -k libs       # 保留 cxx/libs（例如还想继续用仓颉侧链接产物）
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # cxx/

# 目录名 → 说明
TARGETS = {
    "output": "各组 cmake/xmake 构建产物根",
    "build":  "构建中间产物（httpclient/sdl/openssl 等）",
    "dist":   "各组 zip 与日志",
    "logs":   "build.py 运行日志",
    "libs":   "仓颉侧链接库拷贝（jolt/cjbridge 组）",
}


def rmtree(path: str, dry=False) -> bool:
    """返回是否执行了删除。"""
    if not os.path.isdir(path):
        return False
    if dry:
        print(f"  [dry] {path}")
        return True
    shutil.rmtree(path, ignore_errors=True)
    print(f"  [del] {path}")
    return True


def main():
    ap = argparse.ArgumentParser(description="cxx 全库产物清理（详见文件头 docstring）")
    ap.add_argument("-y", "--yes", action="store_true", help="免确认直接清理")
    ap.add_argument("-k", "--keep", default="", metavar="DIRS",
                    help="逗号分隔要保留的目录名（如 -k libs,dist）")
    ap.add_argument("-n", "--dry-run", action="store_true", help="只列出将删除的目录")
    args = ap.parse_args()

    keep = {k.strip() for k in args.keep.split(",") if k.strip()}
    todo = {name: desc for name, desc in TARGETS.items() if name not in keep}
    missing = keep - set(TARGETS)
    if missing:
        sys.exit(f"[clean] 未知保留项: {','.join(sorted(missing))}（可选 {','.join(TARGETS)}）")

    existing = {name: os.path.join(HERE, name) for name in todo
                if os.path.isdir(os.path.join(HERE, name))}
    if not existing:
        print("[clean] 没有可清理的产物目录")
        return
    for name, path in existing.items():
        print(f"  - {name}/  {todo[name]}  ({path})")

    if not args.yes and not args.dry_run:
        try:
            ans = input("确认删除以上目录? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("[clean] 已取消")
            return

    n = 0
    for name, path in existing.items():
        if rmtree(path, dry=args.dry_run):
            n += 1
    print(f"[clean] 完成，清理 {n} 个目录"
          + ("（dry-run 未实际删除）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
