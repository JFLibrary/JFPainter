#!/usr/bin/env python3
"""plugins.py -- JFPainter's plugins written in Rust (plugins/*): build them and lay out the folders
the test scripts load

    python tools/plugins.py                     the plugins for this machine, next to target/debug
    python tools/plugins.py --release           ... next to target/release
    python tools/plugins.py --target x86_64-unknown-linux-gnu
                                                ... for another target, next to target/TRIPLE/debug

plugins/ is a workspace of its own (plugins/README.md): a plugin links against nothing, with no
entry point and position independent, unlike the program.  This script builds every plugin there
with `cargo build --release` and fills, next to the program that `cargo jflib test` runs:

  ptest/Effects, ptest/FileTypes, ptest/Shapes   the plugins tests/plugins*.uis load
                                                 (--plugins=@ptest: <exe folder>/ptest)
  rsplug/Effects                                 the other plugins, for tests/plugins_rsdemo.uis
                                                 and tests/plugins_prepcheck.uis (--plugins=@rsplug)

To use a plugin yourself, copy it from plugins/target/TRIPLE/release into Effects, FileTypes or
Shapes next to JFPainter (README.md, "Plugins").
"""
import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
# the plugins tests/plugins*.uis expect in <exe folder>/ptest (JFLib's build_rs.py PLUGIN_TEST_SET)
TEST_SET = {"Effects": ["swapchan", "sepiastr", "crash", "crashpf", "crashq", "toonew", "badinfo"],
            "FileTypes": ["qoi"], "Shapes": ["pshapes"]}


def host_triple():
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(l.split(": ", 1)[1].strip() for l in out.splitlines() if l.startswith("host: "))


def build(triple):
    """cargo build --release of every plugin -> {name: library file}"""
    cmd = ["cargo", "build", "--release", "--locked", "--target", triple, "--message-format=json-render-diagnostics"]
    r = subprocess.run(cmd, cwd=PLUGINS, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"plugins.py: cargo build in plugins/ failed (exit {r.returncode})")
    libs = {}
    for line in r.stdout.splitlines():
        m = json.loads(line) if line.startswith("{") else {}
        if m.get("reason") == "compiler-artifact" and "cdylib" in m["target"]["kind"]:
            libs[m["target"]["name"]] = next(Path(f) for f in m["filenames"] if f.endswith((".dll", ".so")))
    return libs


def fill(folder, layout, libs):
    """folder/SUB/NAME.dll|.so for every SUB: [NAME] of layout, the folder emptied first"""
    for sub, names in layout.items():
        d = folder / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            f.unlink()
        for n in names:
            # NAME.dll / NAME.so: Cargo calls the Linux file libNAME.so
            shutil.copy2(libs[n], d / (n + libs[n].suffix))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", help="the target triple (default: this machine's)")
    ap.add_argument("--release", action="store_true", help="next to target/release instead of target/debug")
    a = ap.parse_args()
    host = host_triple()
    triple = a.target or host
    libs = build(triple)
    missing = [n for ns in TEST_SET.values() for n in ns if n not in libs]
    if missing:
        sys.exit(f"plugins.py: no plugin {', '.join(missing)} in plugins/")
    exe_dir = ROOT / "target" / ("" if a.target is None else triple) / ("release" if a.release else "debug")
    others = sorted(n for n in libs if n not in {m for ns in TEST_SET.values() for m in ns})
    fill(exe_dir / "ptest", TEST_SET, libs)
    fill(exe_dir / "rsplug", {"Effects": others}, libs)
    print(f"{len(libs)} plugins for {triple} ({platform.system()} host {host}):")
    print(f"  {exe_dir.relative_to(ROOT).as_posix()}/ptest   {', '.join(n for ns in TEST_SET.values() for n in ns)}")
    print(f"  {exe_dir.relative_to(ROOT).as_posix()}/rsplug  {', '.join(others)}")


if __name__ == "__main__":
    main()
