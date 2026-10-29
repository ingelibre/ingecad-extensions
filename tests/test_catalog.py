# SPDX-License-Identifier: GPL-3.0-or-later
"""The checks every pull request goes through. No network: ``fetch`` is
replaced by a dict of fake files."""
from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import catalog  # noqa: E402

GOOD_INIT = b'''"""Hello."""
from core.plugins import MenuItem, PluginSpec


def hello(ctx, *args):
    ctx.echo("Hello")


PLUGIN = PluginSpec(
    id="hola",
    name="Hello",
    version="1.0",
    commands={"HELLO": hello},
    menu=(MenuItem("Say hello", "HELLO"),),
)
'''

URL = "https://example.org/releases/download/v1.0/hola.zip"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(members: dict, links=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in members.items():
            zf.writestr(name, text)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


GOOD_ZIP = _zip({"hola/__init__.py": GOOD_INIT,
                 "hola/tools.py": b"x = 1\n",
                 "hola/i18n/es/ui.json": b'{"Say hello": "Saludar"}'})


def _entry(ident="hola", data=GOOD_ZIP, url=URL, **over) -> str:
    fields = {
        "id": ident, "version": "1.0", "author": "Ana",
        "license": "MIT", "repository": "https://example.org/repo",
        "download": url, "sha256": _sha(data), "ingecad": "0.7.0",
        "tags": ["topography"],
    }
    fields.update(over)
    lines = []
    for k, v in fields.items():
        if v is None:
            continue
        lines.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
    lines += ['[name]', 'es = "Hola"', '[summary]', 'en = "Says hello."']
    return "\n".join(lines) + "\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A catalog in tmp_path; ``files`` maps URL → bytes for fetch()."""
    (tmp_path / "extensions").mkdir()
    (tmp_path / "screenshots").mkdir()
    monkeypatch.setattr(catalog, "ENTRIES", tmp_path / "extensions")
    monkeypatch.setattr(catalog, "SHOTS", tmp_path / "screenshots")
    monkeypatch.setattr(catalog, "REVIEWED", tmp_path / "reviewed.toml")
    monkeypatch.setattr(catalog, "OUT", tmp_path / "catalog.json")
    files: dict = {}

    def fake_fetch(url):
        if url not in files:
            raise OSError("404")
        return files[url]
    monkeypatch.setattr(catalog, "fetch", fake_fetch)
    return tmp_path, files


def _add(repo, text, ident="hola", data=GOOD_ZIP, url=URL):
    root, files = repo
    (root / "extensions" / f"{ident}.toml").write_text(text, "utf-8")
    files[url] = data


def _add_zip(repo, members, links=()):
    data = _zip(members, links)
    _add(repo, _entry(data=data), data=data)


def test_a_good_entry_passes(repo, capsys):
    _add(repo, _entry())
    assert catalog.check() == 0
    assert "All good" in capsys.readouterr().out


def test_the_hash_must_match_and_the_error_tells_the_right_one(repo, capsys):
    _add(repo, _entry(sha256="0" * 64))
    assert catalog.check() == 1
    assert _sha(GOOD_ZIP) in capsys.readouterr().out


def test_a_download_that_is_gone_is_a_problem(repo, capsys):
    root, _ = repo
    (root / "extensions" / "hola.toml").write_text(_entry(), "utf-8")
    assert catalog.check() == 1
    assert "could not download" in capsys.readouterr().out


@pytest.mark.parametrize("init, words", [
    (b"x = 1\n", "no top-level PLUGIN"),
    # defined, but not at the top level: the loader reads module.PLUGIN
    (b"from core.plugins import PluginSpec\n"
     b"def make():\n    PLUGIN = PluginSpec(id='hola', name='H')\n",
     "no top-level PLUGIN"),
    # something else called PLUGIN
    (b"PLUGIN = dict(id='hola')\n", "no top-level PLUGIN"),
    # the loader refuses a PLUGIN.id that is not the folder name
    (b"from core.plugins import PluginSpec\n"
     b"PLUGIN = PluginSpec(id='otro', name='H')\n", "folder name"),
    (b"from core.plugins import PluginSpec\nPLUGIN = PluginSpec(id='hola')\n",
     "needs a name"),
])
def test_an_init_without_a_pluginspec_is_refused(repo, capsys, init, words):
    _add_zip(repo, {"hola/__init__.py": init})
    assert catalog.check() == 1
    assert words in capsys.readouterr().out


def test_a_pluginspec_through_the_module_counts(repo):
    init = (b"import core.plugins as cp\n"
            b"PLUGIN: cp.PluginSpec = cp.PluginSpec(id='hola', name='H')\n")
    _add_zip(repo, {"hola/__init__.py": init})
    assert catalog.check() == 0


def test_a_pluginspec_in_another_file_is_not_enough(repo, capsys):
    """IngeCAD imports __init__.py and reads PLUGIN there; a spec in
    another module only counts when __init__ assigns it — which the checker
    cannot see without running code, so it asks for the plain form."""
    _add_zip(repo, {"hola/__init__.py": b"from .spec import *\n",
                    "hola/spec.py": GOOD_INIT})
    assert catalog.check() == 1
    assert "no top-level PLUGIN" in capsys.readouterr().out


@pytest.mark.parametrize("over, words", [
    ({"license": "Proprietary"}, "free licence"),
    ({"license": "GPL-2.0-only"}, "free licence"),
    ({"tags": ["games"]}, "unknown tags"),
    ({"tags": ["bim"]}, "unknown tags"),           # IngeTrazo's, not ours
    ({"tags": ["civil", "gis", "drawing", "other", "education"]},
     "at most 4"),
    ({"id": "Other"}, "'id'"),
    ({"download": "http://example.org/v1.0/hola.zip"}, "https://"),
    ({"download": "https://example.org/v1.0/hola.py"}, ".zip"),
    ({"download": "https://raw.githubusercontent.com/a/b/main/hola.zip"},
     "branch"),
    ({"download": "https://github.com/a/b/archive/refs/heads/main.zip"},
     "branch"),
    ({"download": "https://github.com/a/b/archive/master.zip"}, "branch"),
    ({"ingecad": "latest"}, "'ingecad'"),
    ({"ingecad": None, "ingetrazo": "0.5.7"}, "missing 'ingecad'"),
    ({"version": None}, "missing 'version'"),
    ({"price": 5}, "unknown fields"),
    ({"sha256": "abc"}, "64-character"),
    ({"author_url": "http://github.com/ana"}, "author_url"),
])
def test_bad_fields_are_explained(repo, capsys, over, words):
    _add(repo, _entry(**over))
    assert catalog.check(offline=True) == 1
    assert words in capsys.readouterr().out


@pytest.mark.parametrize("ident", ["topografia", "terreno"])
def test_a_bundled_plugin_name_is_refused(repo, capsys, ident):
    _add(repo, _entry(ident=ident), ident=ident)
    assert catalog.check(offline=True) == 1
    assert "already ships" in capsys.readouterr().out


def test_every_tag_of_the_list_is_accepted(repo):
    for i, tag in enumerate(sorted(catalog.TAGS)):
        ident = f"p{i}"
        _add(repo, _entry(ident=ident, tags=[tag]), ident=ident)
    assert catalog.check(offline=True) == 0
    assert catalog.TAGS == {
        "topography", "civil", "architecture", "structures", "gis",
        "import-export", "drawing", "annotation", "productivity",
        "education", "other"}


def test_the_code_is_reported_never_run(repo, capsys, tmp_path):
    marker = tmp_path / "ran"
    init = (b"import subprocess\nopen(%r, 'w').write('x')\n"
            b"from core.plugins import PluginSpec\n"
            b"def run(ctx):\n    subprocess.run(['ls'])\n"
            b"PLUGIN = PluginSpec(id='hola', name='H')\n"
            % str(marker).encode())
    _add_zip(repo, {"hola/__init__.py": init,
                    "hola/net.py": b"import urllib.request\n"})
    assert catalog.check() == 0
    out = capsys.readouterr().out
    assert "for the reviewer to read" in out
    assert "imports subprocess" in out and "imports urllib.request" in out
    assert not marker.exists()


def test_qt_exec_is_not_reported_but_builtin_exec_is(repo, capsys):
    init = GOOD_INIT + b"def f(dlg):\n    dlg.exec()\n    exec('1')\n"
    _add_zip(repo, {"hola/__init__.py": init})
    catalog.check()
    out = capsys.readouterr().out
    assert out.count("runs text as code") == 1


def test_a_clean_plugin_has_nothing_for_the_reviewer(repo, capsys):
    _add(repo, _entry())
    catalog.check()
    assert "for the reviewer to read" not in capsys.readouterr().out


def test_a_finder_zip_with_macosx_is_accepted(repo):
    _add_zip(repo, {"hola/__init__.py": GOOD_INIT,
                    "__MACOSX/hola/._init__.py": b"\x00\x05"})
    assert catalog.check() == 0


@pytest.mark.parametrize("members, links, words", [
    ({"../evil/__init__.py": GOOD_INIT}, (), "escapes"),
    ({"hola/../../x.py": b"", "hola/__init__.py": GOOD_INIT}, (), "escapes"),
    ({"/abs/__init__.py": GOOD_INIT}, (), "plain relative"),
    ({"hola\\__init__.py": GOOD_INIT}, (), "plain relative"),
    ({"C:/hola/__init__.py": GOOD_INIT}, (), "plain relative"),
    ({"hola/__init__.py": GOOD_INIT, "otra/__init__.py": GOOD_INIT}, (),
     "exactly one folder"),
    ({"hola/__init__.py": GOOD_INIT, "README.md": b"hi"}, (),
     "exactly one folder"),
    ({"__init__.py": GOOD_INIT}, (), "exactly one folder"),
    ({"hola/sub/__init__.py": GOOD_INIT}, (), "directly inside"),
    ({"otro/__init__.py": GOOD_INIT}, (), "must be the same"),
    ({"hola/__init__.py": GOOD_INIT, "hola/fast.so": b"\x7fELF"}, (),
     "compiled code"),
    ({"hola/__init__.py": GOOD_INIT, "hola/x.pyc": b"\x00"}, (),
     "compiled code"),
    ({"hola/__init__.py": GOOD_INIT}, ("hola/link",), "symbolic link"),
    ({"hola/__init__.py": b"def broken(:\n"}, (), "does not parse"),
])
def test_bad_zips_are_refused(repo, capsys, members, links, words):
    _add_zip(repo, members, links)
    assert catalog.check() == 1
    assert words in capsys.readouterr().out


def test_a_zip_bomb_is_refused_without_unpacking(repo, capsys):
    _add_zip(repo, {"hola/__init__.py": GOOD_INIT,
                    "hola/data.txt": b"0" * (8 * 1024 * 1024)})
    assert catalog.check() == 1
    assert "suspiciously" in capsys.readouterr().out


def test_too_many_members_are_refused(repo, capsys, monkeypatch):
    monkeypatch.setattr(catalog, "MAX_MEMBERS", 3)
    _add_zip(repo, {"hola/__init__.py": GOOD_INIT, "hola/a.py": b"",
                    "hola/b.py": b"", "hola/c.py": b""})
    assert catalog.check() == 1
    assert "more than 3 files" in capsys.readouterr().out


def test_too_much_unpacked_data_is_refused(repo, capsys, monkeypatch):
    monkeypatch.setattr(catalog, "MAX_UNPACKED", 1000)
    _add_zip(repo, {"hola/__init__.py": GOOD_INIT,
                    "hola/big.py": b"# " + b"x" * 2000 + b"\n"})
    assert catalog.check() == 1
    assert "unpacks to more than" in capsys.readouterr().out


def test_a_file_that_is_not_a_zip_is_refused(repo, capsys):
    data = b"<html>not found</html>"
    _add(repo, _entry(data=data), data=data)
    assert catalog.check() == 1
    assert "zip" in capsys.readouterr().out.lower()


def test_the_real_fetch_stops_at_the_size_limit(monkeypatch):
    class Res(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    big = b"x" * (catalog.MAX_DOWNLOAD + 10)
    monkeypatch.setattr(catalog.urllib.request, "urlopen",
                        lambda req, timeout: Res(big))
    with pytest.raises(ValueError):
        catalog.fetch("https://example.org/v1/hola.zip")


def test_reviewed_badge_follows_the_hash(repo):
    root, _ = repo
    _add(repo, _entry())
    (root / "reviewed.toml").write_text(
        f'[hola]\nsha256 = "{_sha(GOOD_ZIP)}"\n', "utf-8")
    assert catalog.build()["extensions"][0]["reviewed"] is True
    new = _zip({"hola/__init__.py": GOOD_INIT + b"# v2\n"})
    _add(repo, _entry(data=new), data=new)
    assert catalog.build()["extensions"][0]["reviewed"] is False


def test_a_reviewed_name_without_an_entry_is_a_problem(repo, capsys):
    root, _ = repo
    (root / "reviewed.toml").write_text('[fantasma]\nsha256 = "x"\n', "utf-8")
    assert catalog.check(offline=True) == 1
    assert "'fantasma' has no entry" in capsys.readouterr().out


def test_only_toml_files_go_in_extensions(repo, capsys):
    root, _ = repo
    (root / "extensions" / "hola.zip").write_bytes(GOOD_ZIP)
    (root / "extensions" / ".gitkeep").write_text("")
    assert catalog.check(offline=True) == 1
    out = capsys.readouterr().out
    assert "hola.zip: only .toml" in out and ".gitkeep" not in out


def test_the_catalog_json_shape(repo):
    """What the extension center in IngeCAD and the web page parse."""
    _add(repo, _entry())
    data = catalog.build()
    assert data["format"] == 1
    assert data["tags"] == sorted(catalog.TAGS)
    e = data["extensions"][0]
    for key in ("id", "version", "author", "license", "repository",
                "download", "sha256", "ingecad", "tags", "name", "summary",
                "reviewed"):
        assert key in e
    assert "ingetrazo" not in e


def test_an_empty_catalog_builds(repo, capsys):
    assert catalog.check() == 0
    assert catalog.build()["extensions"] == []
    root, _ = repo
    assert catalog.main(["build"]) == 0
    written = json.loads((root / "catalog.json").read_text("utf-8"))
    assert written["format"] == 1 and written["extensions"] == []


def test_the_real_catalog_is_valid_offline():
    """The entries in this repository, without downloading."""
    assert catalog.check(offline=True) == 0


def test_the_committed_catalog_json_matches_the_entries():
    """catalog.json is generated: the same entries, in the same order."""
    committed = json.loads((catalog.ROOT / "catalog.json").read_text("utf-8"))
    built = catalog.build()
    assert committed["format"] == built["format"]
    assert committed["tags"] == built["tags"]
    assert [e["id"] for e in committed["extensions"]] == \
        [e["id"] for e in built["extensions"]]


def test_the_template_is_a_valid_entry_but_for_its_hash():
    """TEMPLATE.toml is what authors copy: every field it has is known,
    and the only thing wrong with it is the placeholder download."""
    import tomllib
    text = (catalog.ROOT / "TEMPLATE.toml").read_text("utf-8")
    entry = tomllib.loads(text)
    problems = catalog.Problems()
    catalog.check_fields(entry, entry["id"], problems)
    assert list(problems) == []


def _commit(root, message, when):
    import subprocess
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
           "PATH": "/usr/bin:/bin", "HOME": str(root)}
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True,
                   env=env)


def test_dates_come_from_git_history_and_follow_a_rename(repo):
    """added = first merge, updated = when the current version was merged;
    a metadata-only edit or a rename does not count as an update."""
    import subprocess
    root, _ = repo
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _add(repo, _entry())
    _commit(root, "add", "2026-10-01T10:00:00+00:00")
    _add(repo, _entry(version="1.1"))
    _commit(root, "1.1", "2026-10-05T12:30:00-05:00")
    _add(repo, _entry(version="1.1", tags=["topography", "civil"]))
    _commit(root, "tags only", "2026-10-07T09:00:00+00:00")
    old = root / "extensions" / "hola.toml"
    old.rename(root / "extensions" / "hola_lite.toml")
    _commit(root, "rename", "2026-10-09T09:00:00+00:00")
    dates = catalog.entry_dates(root / "extensions" / "hola_lite.toml")
    assert dates == {"added_at": "2026-10-01T10:00Z",
                     "updated_at": "2026-10-05T17:30Z"}


def test_an_entry_git_does_not_know_gets_no_dates(repo):
    root, _ = repo
    _add(repo, _entry())
    assert catalog.entry_dates(root / "extensions" / "hola.toml") == {}
    assert "added_at" not in catalog.build()["extensions"][0]
