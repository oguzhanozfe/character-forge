"""Packaging accepts final forms only."""
import pytest

from character_forge import packaging
from character_forge.util import ForgeError


def good(tmp_path, cid="z9"):
    root = tmp_path / "pkg"
    (root / "Textures").mkdir(parents=True)
    (root / "Motions").mkdir()
    (root / (cid + ".fbx")).write_bytes(b"fbx")
    (root / "character.manifest.json").write_text("{}")
    (root / "receipt.json").write_text("{}")
    (root / "README.txt").write_text("hi")
    (root / "Textures" / (cid + "_BaseColor.png")).write_bytes(b"png")
    (root / "Motions" / (cid + "@Walk_01.fbx")).write_bytes(b"fbx")
    return root


def test_final_forms_pass(tmp_path):
    assert packaging.verify(good(tmp_path), "z9", max_mb=1)


@pytest.mark.parametrize("relative", ["z9.blend", "source.glb", "Textures/head.ply", "raw/Walk.npz", "low.obj",
                                      "Motions/z9@Walk.bvh", "weights.safetensors", "logs/run.log"])
def test_intermediates_are_refused(tmp_path, relative):
    root = good(tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")
    with pytest.raises(ForgeError, match="intermediate|unexpected"):
        packaging.verify(root, "z9")


@pytest.mark.parametrize("relative", ["Textures/contact-sheet.png", "Textures/preview.png", "Textures/z9_render_front.png"])
def test_review_images_are_refused(tmp_path, relative):
    root = good(tmp_path)
    (root / relative).write_bytes(b"png")
    with pytest.raises(ForgeError, match="review"):
        packaging.verify(root, "z9")


def test_structure_rules(tmp_path):
    root = good(tmp_path)
    (root / "Motions" / "other@Walk.fbx").write_bytes(b"x")
    (root / "notes.md").write_text("x")
    issues = packaging.problems(root, "z9")
    assert any("Motions/" in i for i in issues) and any("unexpected top-level" in i for i in issues)
    root2 = good(tmp_path / "b")
    (root2 / "z9.fbx").unlink()
    assert any("missing model" in i for i in packaging.problems(root2, "z9"))


def test_ids_containing_review_words_are_fine(tmp_path):
    root = good(tmp_path, cid="strawman-preview")
    assert packaging.verify(root, "strawman-preview")


def test_size_budget(tmp_path):
    root = good(tmp_path)
    (root / "Textures" / "z9_Normal.png").write_bytes(b"0" * (2 * 1024 * 1024))
    with pytest.raises(ForgeError, match="budget"):
        packaging.verify(root, "z9", max_mb=1)


def test_package_stage_refuses_until_everything_is_approved(forge):
    forge("new", "p1", "--brief", "zombie", "--mode", "fake")
    code, out = forge("package", "p1")
    assert code == 3 and not (forge.root / "packages" / "p1").exists()
