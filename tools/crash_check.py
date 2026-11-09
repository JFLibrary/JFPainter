#!/usr/bin/env python3
"""crash_check.py -- JFPainter crash reports (src/diagnostics/crash.rs, the library's crash
handler; docs/DIAGNOSTICS.md).

For every target JFPainter (the Cargo debug build, tools/jfp.py) runs a script whose `cmd 911`
writes to address 0x10 (crash_test), with `--crash-dir <out>/crash_check/<target>/logs`
(headless: the protocol is written, no report window is started).  Checked:

  * the process ends with exit code 3 and the library's stderr line
  * exactly one protocol "Absturz_JJJJ-MM-TT_hh-mm-ss.txt" with the exception (Zugriffsverletzung
    beim Schreiben an Adresse 0x10), RAX = 0x10, the registers, the diagnostics part
  * the call chain, resolved with the linker's map of the program: jflib-build has the linker
    write it as program.map into the build script's OUT_DIR (target/[TRIPLE/]debug/build/
    JFPainter-*/out/; of several the one written together with the program is taken).  Names
    are demangled (Rust v0, as LLVM prints them; lld-link writes them mangled, ld.lld
    demangled), return addresses are looked up at the call instruction before them, and the
    chain must start plat::crash_test <- jfpainter::diagnostics::a1_diag_cmd <-
    jfpainter::diagnostics::diag_cmd, contain jfgui_main and end in the platform entry
    (mainCRTStartup; Linux _start, or for a program against glibc plat's glibc_main, whose
    caller __libc_start_main is outside the program).  The crash handler unwinds exactly (PE
    unwind data / .eh_frame CFI), so every return address must also follow a call instruction
    whose direct target is the start of the function below it, or of a function that passes
    control to it by tail calls (such a function has no frame and is shown as "(tail call)"):
    a jmp rel32 to its start (jfgui_main), or an indirect jmp while the address of the
    function below is stored in the program (a table of handlers: pn_cmd) -- no stale stack
    values.
  * `--crash-report FILE` opens the report window with that protocol (a script checks the probe)

  python tools/crash_check.py [--target win|linux|both] [--out build] [--no-build]
  python tools/crash_check.py --resolve PROTOCOL.txt [--release]
                                 (prints the chain of a protocol with the functions of the
                                 debug (release) build's map, demangled; the target from the
                                 protocol; the build must be the one that wrote the protocol)

The real report window (a second process started by plat_spawn_self) is not opened here
(no windows on the desktop); JFLib's plattest --test spawn covers plat_spawn_self.
"""
import argparse
import bisect
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jfp  # noqa: E402

ROOT = jfp.ROOT


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def map_path(target, release=False):
    """the linker's map of jfp.exe(target): program.map in the OUT_DIR of JFPainter's build
    script (jflib-build), the one written closest in time to the program"""
    exe = jfp.exe(target, release)
    maps = list((jfp.target_dir(target, release) / "build").glob("JFPainter-*/out/program.map"))
    if not exe.exists() or not maps:
        return None
    t = exe.stat().st_mtime
    return min(maps, key=lambda m: abs(m.stat().st_mtime - t))


def load_map(path, target):
    """(offset, name) sorted, names demangled (ld.lld's may contain blanks)"""
    syms = []
    for line in open(path, encoding="utf-8", errors="replace"):
        p = line.split()
        if target == "win":
            if len(p) >= 4 and re.match(r"^[0-9a-f]{16}$", p[2]) and not p[1].startswith("."):
                syms.append((int(p[2], 16) - 0x140000000, demangle(p[1])))
        elif (len(p) >= 5 and re.match(r"^[0-9a-f]+$", p[0]) and re.match(r"^[0-9a-f]+$", p[1])
              and p[3] == "1" and not p[4].startswith(".")):
            syms.append((int(p[0], 16), demangle(" ".join(p[4:]))))
    syms.sort()
    return syms


def resolve(syms, offs):
    """the function (start, name) of every offset of the chain; a return address (every
    offset but the first, the crash address) is looked up at the call instruction before it"""
    out = []
    for k, o in enumerate(offs):
        q = o - 1 if k > 0 else o
        i = bisect.bisect_right(syms, (q, "~")) - 1
        out.append(syms[i] if i >= 0 else (None, "?"))
    return out


class Image:
    """the bytes of an executable at offsets as the protocol shows them (PE: image offsets,
    ELF: addresses)"""

    def __init__(self, path, target):
        self.data = pathlib.Path(path).read_bytes()
        self.ranges = []  # (offset, size, file offset)
        self.interp = False  # ELF: PT_INTERP (a program against glibc)
        self.base = 0  # PE: ImageBase (offsets are relative to it)
        d = self.data
        if target == "win":
            nt = int.from_bytes(d[0x3C:0x40], "little")
            self.base = int.from_bytes(d[nt + 48:nt + 56], "little")
            nsec = int.from_bytes(d[nt + 6:nt + 8], "little")
            sh = nt + 24 + int.from_bytes(d[nt + 20:nt + 22], "little")
            for k in range(nsec):
                e = sh + 40 * k
                va, raw, ptr = (int.from_bytes(d[e + o:e + o + 4], "little") for o in (12, 16, 20))
                self.ranges.append((va, raw, ptr))
        else:
            phoff = int.from_bytes(d[32:40], "little")
            phsz = int.from_bytes(d[54:56], "little")
            for k in range(int.from_bytes(d[56:58], "little")):
                e = phoff + k * phsz
                if int.from_bytes(d[e:e + 4], "little") == 1:  # PT_LOAD
                    off, va, fsz = (int.from_bytes(d[e + o:e + o + 8], "little") for o in (8, 16, 32))
                    self.ranges.append((va, fsz, off))
                self.interp |= int.from_bytes(d[e:e + 4], "little") == 3

    def read(self, at, n):
        for va, size, off in self.ranges:
            if va <= at and at + n <= va + size:
                return self.data[off + at - va:off + at - va + n]
        return None

    def pointer_to(self, at):
        """the address of offset at is stored somewhere in the file (a function pointer)"""
        return (self.base + at).to_bytes(8, "little") in self.data


def call_before(img, ret):
    """the call instruction ending at ret: ("direct", target), ("indirect", None) or None (as
    the crash handlers decode it: E8 rel32, FF /2 with every ModRM / SIB form)"""
    b = img.read(ret - 7, 7)
    if b is None:
        return None

    def at(k):  # the byte k before ret
        return b[7 - k]

    if at(5) == 0xE8:
        return "direct", ret + int.from_bytes(b[3:7], "little", signed=True)
    for n in (2, 3, 4, 6, 7):
        m = at(n - 1)
        if at(n) != 0xFF or (m >> 3) & 7 != 2:
            continue
        md, rm = m >> 6, m & 7
        if md == 3 or (md == 0 and rm not in (4, 5)):
            want = 2
        elif md == 0 and rm == 5:
            want = 6
        elif md == 0:
            want = 7 if n >= 3 and at(n - 2) & 7 == 5 else 3
        elif md == 1:
            want = 4 if rm == 4 else 3
        else:
            want = 7 if rm == 4 else 6
        if want == n:
            return "indirect", None
    return None


def tail_calls(img, syms, start, want, depth=2):
    """the functions from start on that pass control to want by tail calls (in the code of each,
    up to the next symbol; at most depth of them): a jmp rel32 to want, or an indirect jmp
    (FF /4) when want's address is stored in the program (a handler table) -> [start, ...] or None"""
    i = bisect.bisect_right(syms, (start, "~"))
    code = img.read(start, (syms[i][0] if i < len(syms) else start + 4096) - start) or b""
    targets = {start + k + 5 + int.from_bytes(code[k + 1:k + 5], "little", signed=True)
               for k in range(len(code) - 4) if code[k] == 0xE9}
    if want in targets or (any(code[k] == 0xFF and (code[k + 1] >> 3) & 7 == 4 for k in range(len(code) - 1))
                           and img.pointer_to(want)):
        return [start]
    for t in sorted(targets) if depth > 1 else []:
        j = bisect.bisect_right(syms, (t, "~")) - 1
        if t != start and j >= 0 and syms[j][0] == t:
            rest = tail_calls(img, syms, t, want, depth - 1)
            if rest:
                return [start] + rest
    return None


def name_at(syms, at):
    i = bisect.bisect_right(syms, (at, "~")) - 1
    return syms[i][1] if i >= 0 else "?"


# ---- Rust v0 symbol names (lld-link writes them mangled into the .map; ld.lld demangles)

B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASIC = {"a": "i8", "b": "bool", "c": "char", "d": "f64", "e": "str", "f": "f32", "h": "u8", "i": "isize",
         "j": "usize", "l": "i32", "m": "u32", "n": "i128", "o": "u128", "s": "i16", "t": "u16", "u": "()",
         "v": "...", "x": "i64", "y": "u64", "z": "!", "p": "_"}


class V0:
    """the Rust v0 mangling grammar (rustc symbol-mangling-version=v0), printed like the LLVM
    demangler prints it in ld.lld's map: `<JFPainter::PnApp as ui::App>::command`"""

    def __init__(self, s):
        self.s = s  # after "_R"
        self.p = 0
        self.bound = 0  # lifetimes bound by the enclosing binders (for<'a, ...>)

    def peek(self):
        return self.s[self.p] if self.p < len(self.s) else ""

    def take(self):
        c = self.peek()
        if not c:
            raise ValueError("end of symbol")
        self.p += 1
        return c

    def eat(self, c):
        if self.peek() == c:
            self.p += 1
            return True
        return False

    def b62(self):
        if self.eat("_"):
            return 0
        n = 0
        while True:
            c = self.take()
            if c == "_":
                return n + 1
            n = n * 62 + B62.index(c)

    def decimal(self):
        if self.eat("0"):
            return 0  # a leading 0 is the whole number
        start = self.p
        while self.peek().isdigit():
            self.p += 1
        if start == self.p:
            raise ValueError("number expected")
        return int(self.s[start:self.p])

    def ident(self):
        dis = self.b62() + 1 if self.eat("s") else 0
        puny = self.eat("u")
        n = self.decimal()
        self.eat("_")
        name = self.s[self.p:self.p + n]
        self.p += n
        if puny:
            try:
                k = name.rfind("_")
                name = (name[:k] + "-" + name[k + 1:] if k >= 0 else "-" + name).encode().decode("punycode")
            except Exception:
                pass
        return dis, name

    def backref(self, fn):
        pos = self.b62()
        save = self.p
        self.p = pos
        try:
            return fn()
        finally:
            self.p = save

    def path(self, in_type=False):
        c = self.take()
        if c == "C":
            return self.ident()[1]
        if c == "N":
            ns = self.take()
            inner = self.path(in_type)
            dis, name = self.ident()
            if ns.isupper():
                kind = {"C": "closure", "S": "shim"}.get(ns, ns)
                return f"{inner}::{{{kind}{':' + name if name else ''}#{dis}}}"
            return f"{inner}::{name}" if name else inner
        if c == "M":
            if self.eat("s"):
                self.b62()
            self.path()  # the impl's parent (not printed)
            return f"<{self.type()}>"
        if c == "X":
            if self.eat("s"):
                self.b62()
            self.path()
            t = self.type()
            return f"<{t} as {self.path(True)}>"
        if c == "Y":
            t = self.type()
            return f"<{t} as {self.path(True)}>"
        if c == "I":
            p = self.path(in_type)
            args = []
            while not self.eat("E"):
                a = self.generic_arg()
                if a is not None:
                    args.append(a)
            return f"{p}{'' if in_type else '::'}<{', '.join(args)}>"
        if c == "B":
            return self.backref(lambda: self.path(in_type))
        raise ValueError(f"path tag {c!r}")

    def lifetime_name(self, i):
        if i == 0:
            return "'_"
        if i - 1 >= self.bound:
            raise ValueError("unbound lifetime")
        d = self.bound - i
        return "'" + (chr(ord("a") + d) if d < 26 else f"z{d - 25}")

    def binder(self):
        """an optional binder G: for<'a, 'b> (the lifetimes stay bound for the caller's scope)"""
        if not self.eat("G"):
            return ""
        n = self.b62() + 1
        names = []
        for _ in range(n):
            self.bound += 1
            names.append(self.lifetime_name(1))
        return f"for<{', '.join(names)}> "

    def generic_arg(self):
        if self.eat("L"):
            return self.lifetime_name(self.b62())
        if self.eat("K"):
            return self.const()
        return self.type()

    def const(self):
        if self.eat("p"):
            return "_"
        if self.eat("B"):
            return self.backref(self.const)
        t = self.take()
        neg = self.eat("n")
        start = self.p
        while self.peek() != "_":
            self.take()
        digits = self.s[start:self.p]
        self.take()
        v = int(digits, 16) if digits else 0
        if t == "b":
            return "true" if v else "false"
        if t == "c":
            return repr(chr(v))
        return str(-v if neg else v)

    def fn_sig(self):
        save = self.bound
        try:
            return self.binder() + self.fn_sig_rest()
        finally:
            self.bound = save

    def fn_sig_rest(self):
        unsafe = self.eat("U")
        abi = ""
        if self.eat("K"):
            abi = '"C"' if self.eat("C") else '"' + self.ident()[1].replace("_", "-") + '"'
        args = []
        while not self.eat("E"):
            args.append(self.type())
        s = ("unsafe " if unsafe else "") + (f"extern {abi} " if abi else "") + f"fn({', '.join(args)})"
        return s if self.eat("u") else f"{s} -> {self.type()}"

    def type(self):
        c = self.peek()
        if c in BASIC:
            self.p += 1
            return BASIC[c]
        self.p += 1
        if c == "A":
            t = self.type()
            return f"[{t}; {self.const()}]"
        if c == "S":
            return f"[{self.type()}]"
        if c == "T":
            ts = []
            while not self.eat("E"):
                ts.append(self.type())
            return f"({ts[0]},)" if len(ts) == 1 else f"({', '.join(ts)})"
        if c in "RQ":
            lt = ""
            if self.eat("L"):
                i = self.b62()
                lt = self.lifetime_name(i) + " " if i else ""
            return "&" + lt + ("mut " if c == "Q" else "") + self.type()
        if c in "PO":
            return ("*const " if c == "P" else "*mut ") + self.type()
        if c == "F":
            return self.fn_sig()
        if c == "D":
            save = self.bound
            try:
                b = self.binder()
                traits = []
                while not self.eat("E"):
                    t = self.path(True)
                    binds = []
                    while self.eat("p"):
                        name = self.ident()[1]
                        binds.append(f"{name} = {self.type()}")
                    if binds:
                        t = t[:-1] + ", " + ", ".join(binds) + ">" if t.endswith(">") else t + "<" + ", ".join(binds) + ">"
                    traits.append(t)
            finally:
                self.bound = save
            s = "dyn " + b + " + ".join(traits)
            if not self.eat("L"):
                raise ValueError("dyn without lifetime")
            i = self.b62()
            return s + (" + " + self.lifetime_name(i) if i else "")
        if c == "B":
            return self.backref(self.type)
        self.p -= 1
        return self.path(True)


def demangle(name):
    """a Rust v0 name (with or without an LLVM suffix such as .llvm.123) demangled; any other
    name as it is (without the suffix)"""
    base = re.sub(r"\.llvm\.\d+$", "", name)
    base = re.sub(r" \(\.llvm\.\d+\)$", "", base)  # ld.lld's demangled form of the suffix
    if not base.startswith("_R"):
        return base
    s = base[2:]
    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1  # an encoding version
    try:
        d = V0(s)
        d.p = i
        return d.path()
    except (ValueError, IndexError):
        return base


class Check:
    def __init__(self, target, out):
        self.target = target
        self.out = out
        self.fails = 0

    def ok(self, cond, text, detail=""):
        print(f"[{self.target}] {'PASS' if cond else 'FAIL'} {text}" + (f" -- {detail}" if detail and not cond else ""))
        self.fails += 0 if cond else 1
        return cond

    def run(self, args):
        return jfp.run_exe(self.target, jfp.exe(self.target), args, timeout=120)

    def main(self):
        base = self.out / "crash_check" / self.target
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
        script = base / "crash.uis"
        script.write_text("size 1280 800\ncmd 911\n", encoding="utf-8")
        crash_dir = base / "logs"
        res = self.run(["--crash-dir", rel(crash_dir), "--script", rel(script)])
        self.ok(res.returncode == 3, "the crash ends the process with exit code 3", f"exit {res.returncode}")
        self.ok("jfgui: crash" in res.stderr, "the library prints its stderr line", res.stderr[-200:])
        logs = sorted(crash_dir.glob("Absturz_*.txt")) if crash_dir.exists() else []
        if not self.ok(len(logs) == 1, "one protocol file Absturz_*.txt", str(logs)):
            return
        log = logs[0]
        self.ok(re.match(r"Absturz_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.txt$", log.name) is not None,
                "the file name carries date and time", log.name)
        text = log.read_text(encoding="utf-8")
        for needle in ["JFPainter ist abgestürzt.", "Zugriffsverletzung (beim Schreiben an Adresse 0x10)",
                       "RAX 0000000000000010", "Register:", "Aufrufkette", "---- Diagnose ----",
                       "Logische Prozessoren:"]:
            self.ok(needle in text, f"protocol contains {needle!r}")
        exe = "JFPainter.exe" if self.target == "win" else "JFPainter"
        offs = [int(m, 16) for m in re.findall(re.escape(exe) + r" \+ 0x([0-9a-f]+)\n", text)]
        mp = map_path(self.target)
        if self.ok(mp is not None, "the build's linker map (program.map) exists", str(jfp.target_dir(self.target))):
            print(f"[{self.target}]   map: {rel(mp)}")
            self.chain(offs, load_map(mp, self.target))
        # the report window shows this protocol
        rscript = base / "report.uis"
        rscript.write_text(f'size 680 520\nexpect text:"JFPainter wurde unerwartet beendet" exists\n'
                           f'expect #6720 text "{rel(log)}"\nclick #6701\nexpect #6706 exists\n',
                           encoding="utf-8")
        res = self.run(["--crash-report", rel(log), "--script", rel(rscript)])
        fails = [l for l in res.stdout.splitlines() if l.startswith("FAIL")]
        self.ok(res.returncode == 0 and not fails, "--crash-report shows the protocol",
                "; ".join(fails) or f"exit {res.returncode}")

    def chain(self, offs, syms):
        """the call chain: crash_test <- a1_diag_cmd <- diag_cmd ... jfgui_main <- the entry,
        and exact (every link is a call into the function below, or into one that tail-calls it)"""
        funcs = resolve(syms, offs)
        names = [n for _, n in funcs]
        img = Image(jfp.exe(self.target), self.target)
        bad, shown = [], names[:1]
        for k in range(1, len(offs)):
            call = call_before(img, offs[k])
            via = []
            if call is None:
                bad.append(f"{names[k]}: no call before 0x{offs[k]:x}")
            elif call[0] == "direct" and call[1] != funcs[k - 1][0]:
                via = tail_calls(img, syms, call[1], funcs[k - 1][0]) or []
                if not via:
                    bad.append(f"{names[k]}: calls 0x{call[1]:x}, not {names[k - 1]}")
            shown += [name_at(syms, v) + " (tail call)" for v in reversed(via)] + [names[k]]
        chain = " <- ".join(shown)
        # the program's code is the library crate jfpainter (Cargo.toml [lib])
        self.ok(names[:3] == ["plat::crash_test", "jfpainter::diagnostics::a1_diag_cmd", "jfpainter::diagnostics::diag_cmd"],
                "the call chain starts plat::crash_test <- jfpainter::diagnostics::a1_diag_cmd <- "
                "jfpainter::diagnostics::diag_cmd", chain)
        # against glibc the program starts in glibc_main, called by __libc_start_main (libc)
        entry = ("mainCRTStartup" if self.target == "win" else
                 "plat::linux::glibc::glibc_main" if img.interp else "_start")
        self.ok(any(n.split(" (")[0] == "jfgui_main" for n in shown) and names[-1] == entry,
                f"the call chain reaches jfgui_main and the entry point {entry}", chain)
        self.ok(len(offs) > 1 and not bad,
                "every return address follows a call into the function below it (an exact chain)",
                "; ".join(bad) or "no frames")
        print(f"[{self.target}]   chain: {chain}")


def resolve_protocol(path, release=False):
    """--resolve: the chain of a protocol, one line per address, with the functions of the
    build's map (the target from the protocol's "JFPainter.exe + 0x..." lines)"""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    target = "win" if "JFPainter.exe + 0x" in text else "linux"
    exe = "JFPainter.exe" if target == "win" else "JFPainter"
    offs = [int(m, 16) for m in re.findall(re.escape(exe) + r" \+ 0x([0-9a-f]+)\n", text)]
    mp = map_path(target, release)
    if mp is None:
        print(f"crash_check: no program.map below {jfp.target_dir(target, release)}")
        return 1
    print(f"  (map {rel(mp)})")
    for k, ((start, name), o) in enumerate(zip(resolve(load_map(mp, target), offs), offs)):
        where = f"{name} + 0x{o - start:x}" if start is not None else name
        print(f"  {exe} + 0x{o:x}  {where}{'  (crash)' if k == 0 else ''}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="both", choices=["win", "linux", "both"])
    ap.add_argument("--out", default="build", help="folder for the results (crash_check/<target>)")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--resolve", metavar="PROTOCOL", help="print the call chain of a crash protocol")
    ap.add_argument("--release", action="store_true", help="--resolve: with the map of the release build")
    a = ap.parse_args()
    out = ROOT / a.out
    if a.resolve:
        return resolve_protocol(a.resolve, a.release)
    os.environ.pop("JFPainter_CONFIG_DIR", None)    # (reaches the program through jfp.run_exe)
    targets = jfp.targets(a.target)
    if not a.no_build:
        jfp.build(targets)
    fails = 0
    for t in targets:
        c = Check(t, out)
        c.main()
        fails += c.fails
    print("crash_check:", "all passed" if fails == 0 else f"{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
