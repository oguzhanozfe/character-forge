"""Shared fixtures. Every test runs in its own temporary forge project; fixtures (meshes, images, motions) are generated
on the fly, so the repository holds no binary test data."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from character_forge import cli, config  # noqa: E402
from character_forge.meshkit import raster  # noqa: E402
from character_forge.workspace import Workspace  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_LOCK_ROOT", str(tmp_path / "locks"))
    monkeypatch.delenv("FORGE_ROOT", raising=False)
    yield


@pytest.fixture
def project(tmp_path):
    root = config.init_project(tmp_path / "proj")
    return root


class Forge:
    def __init__(self, root, capsys):
        self.root = root
        self.capsys = capsys

    def __call__(self, *args):
        code = cli.main(["--root", str(self.root), *map(str, args)])
        out = self.capsys.readouterr()
        return code, out.out + out.err

    def ws(self, identifier):
        return Workspace(self.root, identifier)

    def approve_all_and_run(self, identifier, by="human", limit=20):
        """Run, approving each gate as it appears, until done or a non-approval stop."""
        for _ in range(limit):
            code, out = self("run", identifier)
            if code == 0:
                return code, out
            if code != 3 or "awaiting approval" not in out and "awaiting-approval" not in out:
                return code, out
            stage = [line for line in out.splitlines() if "awaiting" in line][0].split()[0]
            c, o = self("approve", identifier, "--stage", stage, "--by", by, "--note", "test approval", "--reviewer", "pytest")
            assert c == 0, o
        raise AssertionError("pipeline did not finish")


@pytest.fixture
def forge(project, capsys):
    return Forge(project, capsys)


@pytest.fixture
def png_file(tmp_path):
    path = tmp_path / "ref.png"
    raster.write_png(path, [[(120, 110, 100)] * 1100 for _ in range(1200)], rgb=True)
    return path
