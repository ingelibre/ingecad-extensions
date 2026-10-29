#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Check the catalog entries and build ``catalog.json``.

The catalog lists IngeCAD plugins; it never holds their code. Each entry is
one ``extensions/<id>.toml`` naming the author's ``.zip`` by URL **and** its
SHA-256, so what a maintainer reviewed is exactly what users download: a new
version is a new pull request with a new hash.

An IngeCAD plugin is a FOLDER whose ``__init__.py`` defines
``PLUGIN = PluginSpec(...)`` (``core/plugins.py`` and ``docs/plugins.md`` in
the IngeCAD repository). The download is a zip holding exactly that one
folder, named like the entry's ``id`` — the loader refuses a plugin whose
``PLUGIN.id`` is not its folder name.

Usage::

    catalog.py check [--offline] [ids…]   validate entries (CI on every PR)
    catalog.py build                      write catalog.json (CI on main)

``check`` downloads each zip, verifies the hash, checks that it unpacks
safely and reads the code with ``ast`` — it is **never executed**, here or
in CI. What it finds that a reviewer should look at (processes, network,
``eval``…) is printed as a report, not an error: plenty of honest plugins
need the network.

Standard library only (Python 3.11+), so CI needs no installs.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "extensions"
SHOTS = ROOT / "screenshots"
REVIEWED = ROOT / "reviewed.toml"
OUT = ROOT / "catalog.json"

LANGS = ("es", "en", "pt")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}([.-]?[a-z0-9]+)?$")
APP_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+){0,2}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

#: The plugins IngeCAD ships with. A catalog entry can never take their
#: folder name: the bundled one would win and the download would be dead.
BUNDLED = {"topografia", "terreno"}

#: Free licences a plugin may carry. It is loaded into a GPL-3.0 program,
#: so licences that cannot live with GPL-3.0 (GPL-2.0-only) are out.
LICENCES = {
    "GPL-3.0-only", "GPL-3.0-or-later", "GPL-2.0-or-later",
    "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "AGPL-3.0-only", "AGPL-3.0-or-later",
    "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "MPL-2.0",
    "ISC", "Zlib", "0BSD", "Unlicense", "CC0-1.0",
}

#: The tags the web page and the extension center filter by. A fixed list
#: keeps the filter useful; propose a new one in the pull request if none fits.
TAGS = {
    "topography", "civil", "architecture", "structures", "gis",
    "import-export", "drawing", "annotation", "productivity", "education",
    "other",
}

REQUIRED = ("id", "name", "summary", "author", "license", "repository",
            "version", "download", "sha256", "ingecad", "tags")
OPTIONAL = ("author_url", "screenshot", "description")

MAX_DOWNLOAD = 5 * 1024 * 1024      # a plugin is code, not assets
MAX_UNPACKED = 40 * 1024 * 1024     # what the zip may unpack to
MAX_MEMBERS = 2000
MAX_RATIO = 200                     # unpacked / packed, per member
MAX_SHOT = 600 * 1024

#: Calls a reviewer should look at. Not forbidden: reported.
_SENSITIVE_MODULES = {
    "subprocess": "runs other programs",
    "socket": "opens network connections",
    "urllib": "uses the network",
    "http": "uses the network",
    "requests": "uses the network",
    "ctypes": "calls native code",
    "shutil": "copies or deletes files",
    "pickle": "loads pickled data (can run code)",
    "marshal": "loads compiled code",
}
#: Built-ins, flagged only when called bare (``exec(…)``, not Qt's
#: ``dialog.exec()``).
_SENSITIVE_BUILTINS = {
    "eval": "evaluates text as code", "exec": "runs text as code",
    "compile": "compiles text as code", "__import__": "imports by name",
}
#: Methods, flagged when called on anything (``os.system(…)``).
_SENSITIVE_METHODS = {
    "system": "runs a shell command (os.system)",
    "popen": "runs a shell command (os.popen)",
    "unlink": "deletes files", "rmtree": "deletes folders",
}
#: Compiled or native files: nothing a reviewer can read.
_BINARY_CODE = (".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib", ".exe")


class Problems(list):
    def add(self, ident: str, msg: str) -> None:
        self.append(f"{ident}: {msg}")


# --------------------------------------------------------------- reading

def load_entry(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_reviewed() -> dict:
    if not REVIEWED.is_file():
        return {}
    with open(REVIEWED, "rb") as fh:
        return tomllib.load(fh)


def entry_paths(ids=None) -> list[Path]:
    paths = sorted(ENTRIES.glob("*.toml"))
    if ids:
        paths = [p for p in paths if p.stem in set(ids)]
    return paths


# --------------------------------------------------------------- checking

def _texts(value, field: str, ident: str, problems: Problems,
           limit: int) -> None:
    """A text in up to three languages: ``{es = "…", en = "…"}``. At least
    Spanish or English, so the page always has something to show."""
    if not isinstance(value, dict):
        problems.add(ident, f"'{field}' must be a table like "
                            f'{{ es = "…", en = "…", pt = "…" }}')
        return
    extra = set(value) - set(LANGS)
    if extra:
        problems.add(ident, f"'{field}' has unknown languages {sorted(extra)}"
                            f" (use es, en, pt)")
    if not (value.get("es") or value.get("en")):
        problems.add(ident, f"'{field}' needs at least 'es' or 'en'")
    for lang, text in value.items():
        if not isinstance(text, str) or not text.strip():
            problems.add(ident, f"'{field}.{lang}' must be non-empty text")
        elif len(text) > limit:
            problems.add(ident, f"'{field}.{lang}' is longer than {limit} "
                                f"characters")


def _https(url, field: str, ident: str, problems: Problems) -> bool:
    if not isinstance(url, str) or not url.startswith("https://"):
        problems.add(ident, f"'{field}' must be an https:// address")
        return False
    return True


#: Addresses that name a branch, whose content changes after the review.
_BRANCH_URLS = (
    re.compile(r"raw\.githubusercontent\.com/[^/]+/[^/]+/"
               r"(refs/heads/)?(main|master|develop|dev)/"),
    re.compile(r"/archive/refs/heads/"),
    re.compile(r"/archive/(main|master|develop|dev)\.zip$"),
    re.compile(r"/-/archive/(main|master|develop|dev)/"),
)


def check_fields(entry: dict, stem: str, problems: Problems) -> None:
    ident = stem
    for key in REQUIRED:
        if key not in entry:
            problems.add(ident, f"missing '{key}'")
    unknown = set(entry) - set(REQUIRED) - set(OPTIONAL)
    if unknown:
        problems.add(ident, f"unknown fields {sorted(unknown)}")

    eid = entry.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        problems.add(ident, "'id' must be lowercase letters, digits and _ "
                            "(2–48), starting with a letter")
    elif eid != stem:
        problems.add(ident, f"'id' ({eid}) must match the file name "
                            f"({stem}.toml)")
    elif eid in BUNDLED:
        problems.add(ident, f"'{eid}' is a plugin IngeCAD already ships; "
                            f"choose another id")

    if "name" in entry:
        _texts(entry["name"], "name", ident, problems, 60)
    if "summary" in entry:
        _texts(entry["summary"], "summary", ident, problems, 240)
    if "description" in entry:
        _texts(entry["description"], "description", ident, problems, 2000)

    if not isinstance(entry.get("author", ""), str) or not entry.get("author"):
        problems.add(ident, "'author' must be your name")
    if "author_url" in entry:
        _https(entry["author_url"], "author_url", ident, problems)

    lic = entry.get("license")
    if lic not in LICENCES:
        problems.add(ident, f"'license' must be a free licence compatible "
                            f"with GPL-3.0, written as SPDX "
                            f"(one of: {', '.join(sorted(LICENCES))})")

    if "repository" in entry:
        _https(entry["repository"], "repository", ident, problems)

    ver = entry.get("version")
    if not isinstance(ver, str) or not VERSION_RE.match(ver):
        problems.add(ident, "'version' must look like \"1.0\" or \"0.3.2\"")
    app = entry.get("ingecad")
    if not isinstance(app, str) or not APP_VERSION_RE.match(app):
        problems.add(ident, "'ingecad' must be the IngeCAD version you "
                            "tested with, like \"0.7.0\"")

    tags = entry.get("tags")
    if not isinstance(tags, list) or not tags:
        problems.add(ident, "'tags' must be a list with at least one tag")
    else:
        bad = [t for t in tags if t not in TAGS]
        if bad:
            problems.add(ident, f"unknown tags {bad} "
                                f"(use: {', '.join(sorted(TAGS))})")
        if len(tags) > 4:
            problems.add(ident, "at most 4 tags")

    url = entry.get("download")
    if "download" in entry and _https(url, "download", ident, problems):
        if not url.lower().endswith(".zip"):
            problems.add(ident, "'download' must point at a .zip holding "
                                "your plugin folder")
        if any(p.search(url) for p in _BRANCH_URLS):
            problems.add(ident, "'download' points at a branch, which "
                                "changes; use a tag or a commit in the "
                                "address (a release asset …/download/v1.0/"
                                "<id>.zip is best)")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        problems.add(ident, "'sha256' must be the 64-character SHA-256 of "
                            "the downloaded file (sha256sum <id>.zip)")

    shot = entry.get("screenshot")
    if shot is not None:
        p = SHOTS / str(shot)
        if (not isinstance(shot, str) or "/" in shot or "\\" in shot
                or not re.match(r"^[a-z0-9_.-]+\.(png|jpg|jpeg|webp)$", shot)):
            problems.add(ident, "'screenshot' must be a file name in "
                                "screenshots/ (.png, .jpg or .webp)")
        elif not p.is_file():
            problems.add(ident, f"screenshot {shot} is not in screenshots/")
        elif p.stat().st_size > MAX_SHOT:
            problems.add(ident, f"screenshot {shot} is larger than "
                                f"{MAX_SHOT // 1024} KB")
        elif not _is_image(p.read_bytes()[:16]):
            problems.add(ident, f"screenshot {shot} is not an image")


def _is_image(head: bytes) -> bool:
    return (head.startswith(b"\x89PNG\r\n\x1a\n")
            or head.startswith(b"\xff\xd8\xff")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"))


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ingecad-extensions-catalog"})
    with urllib.request.urlopen(req, timeout=30) as res:
        data = res.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError(f"larger than {MAX_DOWNLOAD // 1024 // 1024} MB")
    return data


def plugin_sources(data: bytes, ident: str) -> dict[str, str]:
    """``{member name: source}`` of the plugin's Python files, after the
    checks an installer relies on: the zip holds exactly one folder, named
    like the entry's id, with an ``__init__.py`` directly inside, and
    unpacks safely (no member escapes the folder, no links, no huge or
    endless files). The zip is read, never extracted."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError(f"the zip has more than {MAX_MEMBERS} files")
    seen: set[str] = set()
    total = 0
    files: list[str] = []
    for info in infos:
        n = info.filename
        if "\\" in n or ":" in n or n.startswith("/") or "\x00" in n:
            raise ValueError(f"zip member {n!r} is not a plain relative path")
        parts = PurePosixPath(n).parts
        if not parts or ".." in parts or "." in parts:
            raise ValueError(f"zip member {n!r} escapes its folder")
        if n in seen:
            raise ValueError(f"zip member {n!r} appears twice")
        seen.add(n)
        if info.flag_bits & 0x1:
            raise ValueError(f"zip member {n!r} is encrypted")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError(f"zip member {n!r} is a symbolic link")
        if info.is_dir():
            continue
        total += info.file_size
        if info.compress_size and info.file_size > MAX_RATIO * max(
                info.compress_size, 1024):
            raise ValueError(f"zip member {n!r} unpacks to suspiciously "
                             f"much data")
        files.append(n)
    if total > MAX_UNPACKED:
        raise ValueError(f"the zip unpacks to more than "
                         f"{MAX_UNPACKED // 1024 // 1024} MB")

    loose = [n for n in files if len(PurePosixPath(n).parts) == 1]
    if loose:
        raise ValueError("the zip must hold exactly one folder (your plugin)"
                         f" and nothing beside it, but {loose[0]!r} is loose")
    tops = {PurePosixPath(i.filename).parts[0] for i in infos}
    tops.discard("__MACOSX")            # what macOS's Finder adds
    if len(tops) != 1:
        raise ValueError("the zip must hold exactly one folder (your plugin)"
                         f", not {sorted(tops) or 'nothing'}")
    top = tops.pop()
    if f"{top}/__init__.py" not in files:
        raise ValueError(f"the zip must hold one folder with an __init__.py "
                         f"directly inside ({ident}/__init__.py)")
    if top != ident:
        raise ValueError(f"the folder in the zip is {top!r} but the entry's "
                         f"id is {ident!r}: IngeCAD names a plugin after its "
                         f"folder, so they must be the same")
    for n in files:
        if n.lower().endswith(_BINARY_CODE) and not n.startswith("__MACOSX/"):
            raise ValueError(f"zip member {n!r} is compiled code, which "
                             f"nobody can review; ship the source only")
    return {n: zf.read(n).decode("utf-8") for n in files
            if n.endswith(".py") and not n.startswith("__MACOSX/")}


def _is_pluginspec_call(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    return ((isinstance(fn, ast.Name) and fn.id == "PluginSpec")
            or (isinstance(fn, ast.Attribute) and fn.attr == "PluginSpec"))


def find_spec(tree: ast.Module) -> ast.Call | None:
    """The ``PLUGIN = PluginSpec(...)`` at the top level of a module."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "PLUGIN" for t in targets) \
                and _is_pluginspec_call(node.value):
            return node.value
    return None


def review_report(sources: dict[str, str],
                  ident: str) -> tuple[str | None, list[str]]:
    """``(problem, notes)``: ``problem`` says why IngeCAD would load nothing
    (no ``PLUGIN = PluginSpec(...)`` in the folder's ``__init__.py``, or one
    whose literal ``id`` is not the folder name), ``notes`` the lines a
    reviewer should read."""
    notes: list[str] = []
    problem: str | None = None
    init = f"{ident}/__init__.py"
    for name, src in sources.items():
        try:
            tree = ast.parse(src, filename=name)
        except SyntaxError as exc:
            raise ValueError(f"{name} does not parse: {exc}") from None
        if name == init:
            spec = find_spec(tree)
            if spec is None:
                problem = (f"{init} has no top-level PLUGIN = PluginSpec(...)"
                           f": IngeCAD would load nothing from it")
            else:
                given = {k.arg: k.value for k in spec.keywords if k.arg}
                pid = given.get("id")
                if isinstance(pid, ast.Constant) and pid.value != ident:
                    problem = (f"PluginSpec(id={pid.value!r}) must be the "
                               f"folder name {ident!r}")
                if "name" not in given and len(spec.args) < 2:
                    problem = problem or "PluginSpec needs a name="
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = ([a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""])
                for m in mods:
                    why = _SENSITIVE_MODULES.get(m.split(".")[0])
                    if why:
                        notes.append(f"{name}:{node.lineno} imports {m} "
                                     f"— {why}")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    fname, why = fn.id, _SENSITIVE_BUILTINS.get(fn.id)
                elif isinstance(fn, ast.Attribute):
                    fname, why = fn.attr, _SENSITIVE_METHODS.get(fn.attr)
                else:
                    fname, why = "", None
                if why:
                    notes.append(f"{name}:{node.lineno} calls {fname}() "
                                 f"— {why}")
    return problem, notes


def check_download(entry: dict, problems: Problems,
                   reports: dict) -> None:
    ident = entry.get("id", "?")
    url, sha = entry.get("download"), entry.get("sha256")
    if not isinstance(url, str) or not url.startswith("https://"):
        return
    try:
        data = fetch(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        problems.add(ident, f"could not download {url}: {exc}")
        return
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        problems.add(ident, f"sha256 does not match the file at 'download'"
                            f" — the file there has sha256 = \"{got}\"")
        return
    try:
        sources = plugin_sources(data, ident)
        problem, notes = review_report(sources, ident)
    except (ValueError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        problems.add(ident, str(exc))
        return
    if problem:
        problems.add(ident, problem)
    reports[ident] = notes


def check(ids=None, offline: bool = False) -> int:
    problems = Problems()
    reports: dict = {}
    paths = entry_paths(ids)
    for path in paths:
        try:
            entry = load_entry(path)
        except tomllib.TOMLDecodeError as exc:
            problems.add(path.stem, f"not valid TOML: {exc}")
            continue
        check_fields(entry, path.stem, problems)
        if not offline:
            check_download(entry, problems, reports)
    for path in ENTRIES.iterdir():
        if path.suffix != ".toml" and path.name != ".gitkeep":
            problems.add(path.name, "only .toml files go in extensions/")
    reviewed = load_reviewed()
    known = {p.stem for p in entry_paths()}
    for ident in reviewed:
        if ident not in known:
            problems.add("reviewed.toml", f"'{ident}' has no entry")

    print(f"Checked {len(paths)} entr{'y' if len(paths) == 1 else 'ies'}.")
    for ident, notes in reports.items():
        if notes:
            print(f"\n{ident} — for the reviewer to read:")
            for n in notes:
                print(f"  · {n}")
    if problems:
        print("\nProblems:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("All good.")
    return 0


# --------------------------------------------------------------- dates

def _git(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _stamp(iso: str) -> str:
    """A commit's date as UTC, to the minute — the same shape as
    ``generated``."""
    when = datetime.fromisoformat(iso.strip()).astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%MZ")


def entry_dates(path: Path) -> dict:
    """``{"added_at", "updated_at"}`` from the git history of an entry:
    when it was first merged, and when its current ``version`` was. A
    rename keeps its history; an entry git does not know yet (not
    committed, or no git at all) gets neither, and the page and the app
    then treat it as the oldest."""
    where = path.resolve().parent
    log = _git(["log", "--follow", "--format=%x00%H%x00%cI", "--name-only",
                "--", path.name], where)
    if not log:
        return {}
    commits = []                        # oldest first: (hash, date, path)
    parts = log.split("\x00")[1:]
    for i in range(0, len(parts) - 1, 2):
        sha = parts[i].strip()
        date, _, rest = parts[i + 1].partition("\n")
        names = [n for n in rest.split("\n") if n.strip()]
        if names:                       # repository-relative, as git shows
            commits.append((sha, date, names[0]))
    commits.reverse()
    if not commits:
        return {}
    dates = {"added_at": _stamp(commits[0][1])}
    version, since = None, None
    for sha, date, name in commits:
        text = _git(["show", f"{sha}:{name}"], where)
        try:
            v = tomllib.loads(text).get("version") if text else None
        except tomllib.TOMLDecodeError:
            v = None
        if v is not None and v != version:
            version, since = v, date
    dates["updated_at"] = _stamp(since or commits[0][1])
    return dates


# --------------------------------------------------------------- building

def build() -> dict:
    reviewed = load_reviewed()
    out = []
    for path in entry_paths():
        entry = load_entry(path)
        rev = reviewed.get(entry["id"], {})
        # Reviewed means THIS file: a new hash is unreviewed until a
        # maintainer looks again.
        entry["reviewed"] = rev.get("sha256") == entry["sha256"]
        entry.update(entry_dates(path))
        out.append(entry)
    out.sort(key=lambda e: (not e["reviewed"],
                            (e["name"].get("es") or e["name"].get("en")
                             or "").lower()))
    return {
        "format": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "tags": sorted(TAGS),
        "extensions": out,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--offline", action="store_true",
                   help="skip downloading the files")
    c.add_argument("ids", nargs="*")
    sub.add_parser("build")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return check(args.ids, args.offline)
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(data['extensions'])} plugins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
