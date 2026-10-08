"""Motion format, retargeting, screening and library selection."""
import math

import pytest

from character_forge import library
from character_forge.meshkit import analysis
from character_forge.meshkit import vecmath as vm
from character_forge.meshkit.motion import (SOMA_MAPPING, baked_basis, bone_radii, fmotion_from_global_rotations, ground_clamp,
                                            procedural_clip, retarget, screen, tpose_alignment)
from character_forge.meshkit.skeleton import HUMAN_BONES, build_skeleton
from character_forge.meshkit.skinning import posed_world
from character_forge.meshkit.synth import synthetic_humanoid, synthetic_weights
from character_forge.util import ForgeError


@pytest.fixture(scope="module")
def character():
    mesh, lm = synthetic_humanoid(seed=9)
    skeleton = build_skeleton(lm)
    weights = synthetic_weights(mesh, skeleton)
    return mesh, lm, skeleton, weights, analysis.unique_edges(mesh)


def identity_clip(frames=3):
    rotations = {b: [[1, 0, 0, 0]] * frames for b in HUMAN_BONES}
    return {"format": "character-forge/motion@1", "id": "TPose", "kind": "Idle", "fps": 30, "frames": frames, "loop": True,
            "in_place": True, "reference_hip_height": 0.95, "root": [[0, 0, 0.95]] * frames, "rotations": rotations, "events": {}}


def test_identity_clip_puts_character_in_tpose(character):
    _, lm, skeleton, _, _ = character
    baked = retarget(identity_clip(), skeleton)
    world = posed_world(skeleton, baked_basis(baked, 0))
    for side, sign in (("Left", 1), ("Right", -1)):
        shoulder = vm.mat_translation(world[side + "UpperArm"])
        hand = vm.mat_translation(world[side + "Hand"])
        direction = vm.normalize(vm.sub(hand, shoulder))
        assert direction[0] * sign > 0.999, side          # arms straight out along +/-X
    hips = vm.mat_translation(world["Hips"])
    assert math.isclose(hips[2], lm["Hips"][2], rel_tol=1e-6)  # hip height scaled to this character


def test_tpose_alignment_only_touches_arm_chains(character):
    _, _, skeleton, _, _ = character
    align = tpose_alignment(skeleton)
    assert align["Spine"] == vm.quat_identity() and align["LeftUpperLeg"] == vm.quat_identity()
    assert align["LeftIndexDistal"] == align["LeftHand"] != vm.quat_identity()


def test_procedural_clips_retarget_and_pass_screen(character):
    mesh, _, skeleton, weights, edges = character
    radii = bone_radii(skeleton, mesh.vertices, weights)
    for kind, region in (("Idle", None), ("Walk", None), ("Run", None), ("Attack", None), ("Hit", "LeftForearm"), ("Death", None)):
        clip = procedural_clip(kind, kind, seed=2, region=region, hip_height=skeleton.bones["Hips"].head[2])
        baked = ground_clamp(retarget(clip, skeleton), skeleton, radii)
        result = screen(baked, skeleton, mesh.vertices, weights, edges, 1.78)
        assert result["finite"] and result["status"] == "PASS", (kind, result["problems"])
    attack = screen(retarget(procedural_clip("Attack", "A", hip_height=0.95), skeleton), skeleton, mesh.vertices, weights, edges, 1.78)
    assert attack["attack_reach_per_height"] is not None


def test_screen_flags_floor_penetration_and_loop_seam(character):
    mesh, _, skeleton, weights, edges = character
    clip = procedural_clip("Walk", "W", hip_height=skeleton.bones["Hips"].head[2])
    clip["root"] = [[x, y, z - 0.2] for x, y, z in clip["root"]]          # sink the body
    sunk = screen(retarget(clip, skeleton), skeleton, mesh.vertices, weights, edges, 1.78)
    assert any("floor penetration" in p for p in sunk["problems"])
    clip = procedural_clip("Idle", "I", hip_height=skeleton.bones["Hips"].head[2])
    clip["rotations"]["Spine"][-1] = list(vm.quat_axis_angle((1, 0, 0), 40))  # last frame differs from the first
    seam = screen(retarget(clip, skeleton), skeleton, mesh.vertices, weights, edges, 1.78)
    assert any("loop seam" in p for p in seam["problems"])


def test_kimodo_style_conversion_identity_and_mapping():
    names = [SOMA_MAPPING[b] for b in HUMAN_BONES]
    eye = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    frames = 4
    rots = [[eye for _ in names] for _ in range(frames)]
    root = [[0.0, 0.95, 0.1 * f] for f in range(frames)]                  # y-up, walking toward +z (generator forward)
    clip = fmotion_from_global_rotations("K", "Walk", names, rots, root, 30)
    assert set(clip["rotations"]) == set(HUMAN_BONES)
    assert all(q == [1.0, 0.0, 0.0, 0.0] for q in clip["rotations"]["Hips"])
    assert clip["root"][0][:2] == [0.0, 0.0] and clip["root"][-1][1] < -0.29  # +z forward -> -y forward, z up
    assert math.isclose(clip["root"][0][2], 0.95)


def test_conversion_maps_a_rotation_about_generator_up_to_forge_up():
    names = ["Hips"]
    q90 = [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]          # 90 deg about +Y (generator up)
    clip = fmotion_from_global_rotations("K", "Idle", names, [[q90]], [[0, 1, 0]], 30, mapping={"Hips": "Hips"}, remove_heading=False)
    w, x, y, z = clip["rotations"]["Hips"][0]
    assert math.isclose(abs(z), math.sqrt(0.5), abs_tol=1e-6) and abs(x) < 1e-6 and abs(y) < 1e-6


def test_library_select_include_exclude_and_missing(tmp_path):
    library.synth(tmp_path / "lib", regions=["Chest"])
    lib = library.load(tmp_path / "lib")
    slots = [("Idle", None), ("Walk", None), ("Hit", "Chest"), ("Hit", "Head"), ("Attack", None)]
    chosen, missing = library.select([lib], slots)
    assert [c["clip"]["id"] for c in chosen] == ["Proc_Idle_01", "Proc_Walk_01", "Proc_Hit_Chest_01", "Proc_Attack_01"]
    assert missing == [["Hit", "Head"]]
    chosen, missing = library.select([lib], slots, exclude=["Proc_Walk_01"])
    assert ["Walk", None] in missing
    with pytest.raises(ForgeError):
        library.select([lib], slots, include=["Nope"])
    with pytest.raises(ForgeError):
        library.synth(tmp_path / "lib")                                   # never overwrite an existing library


def test_library_add_requires_fmotion_and_unique_ids(tmp_path):
    from character_forge.util import write_json
    clip = write_json(tmp_path / "c.fmotion.json", procedural_clip("Walk", "MyWalk"))
    library.add_clip(tmp_path / "lib", clip, licence="own")
    with pytest.raises(ForgeError):
        library.add_clip(tmp_path / "lib", clip, licence="own")
    bogus = write_json(tmp_path / "b.json", {"format": "other"})
    with pytest.raises(ForgeError):
        library.add_clip(tmp_path / "lib", bogus, licence="own")
    assert library.load(tmp_path / "lib")["clips"][0]["licence"] == "own"
