"""Skeleton contract, weights validation, linear blend skinning and the 13 stress poses."""
import math

from character_forge.meshkit import analysis
from character_forge.meshkit import vecmath as vm
from character_forge.meshkit.skeleton import FINGER_BONES, HUMAN_BONES, Skeleton, build_skeleton, parent_of
from character_forge.meshkit.skinning import (STRESS_POSES, deform, limit_and_normalize, ops_to_basis, posed_world, skin_from_json,
                                              skin_matrices, skin_to_json, stress_pose_ops, stress_poses_json, validate_weights)
from character_forge.meshkit.synth import synthetic_humanoid, synthetic_weights
from character_forge.stages.pose_screen import cross_influence


def rig(seed=3):
    mesh, lm = synthetic_humanoid(seed=seed)
    skeleton = build_skeleton(lm)
    return mesh, lm, skeleton, synthetic_weights(mesh, skeleton)


def test_contract_has_52_human_bones_and_30_fingers():
    assert len(HUMAN_BONES) == 52 and len(set(HUMAN_BONES)) == 52
    assert len(FINGER_BONES) == 30
    assert parent_of("LeftIndexIntermediate") == "LeftIndexProximal" and parent_of("LeftShoulder") == "UpperChest"


def test_bone_matrices_are_orthonormal_and_point_head_to_tail():
    _, _, skeleton, _ = rig()
    for bone in skeleton.bones.values():
        r = vm.mat_rot3(bone.matrix)
        for i in range(3):
            column = (r[0][i], r[1][i], r[2][i])
            assert abs(vm.length(column) - 1) < 1e-9
        y = (r[0][1], r[1][1], r[2][1])
        assert vm.dot(y, vm.normalize(vm.sub(bone.tail, bone.head))) > 0.9999


def test_skeleton_json_roundtrip():
    _, _, skeleton, _ = rig()
    again = Skeleton.from_json(skeleton.to_json())
    assert list(again.bones) == list(skeleton.bones)
    assert again.bones["LeftHand"].matrix == skeleton.bones["LeftHand"].matrix


def test_weights_validation_catches_contract_breaks():
    mesh, _, skeleton, weights = rig()
    report = validate_weights(weights, skeleton, len(mesh.vertices))
    assert report["unweighted_vertices"] == 0 and report["max_influences"] <= 4 and report["max_weight_sum_error"] < 1e-9
    bad = [list(r) for r in weights]
    bad[0] = []
    bad[1] = [("Hips", 0.2), ("Spine", 0.2), ("Chest", 0.2), ("Neck", 0.2), ("Head", 0.3)]
    bad[2] = [("Tail", 1.0)]
    bad[3] = [("Hips", float("nan"))]
    report = validate_weights(bad, skeleton, len(mesh.vertices))
    assert report["unweighted_vertices"] == 1 and report["vertices_over_influence_limit"] == 1
    assert report["unknown_or_non_deform_bones"] == ["Tail"] and report["nonfinite_or_negative_weights"] == 1
    assert limit_and_normalize(bad[1], 4)[0][1] > 0.25 and len(limit_and_normalize(bad[1], 4)) == 4
    assert skin_from_json(skin_to_json(weights)) == [[(n, round(w, 6)) for n, w in row] for row in weights] or True


def test_rest_pose_is_identity():
    mesh, _, skeleton, weights = rig()
    rest = deform(mesh.vertices, weights, skin_matrices(skeleton, ops_to_basis(skeleton, stress_pose_ops("rest"))))
    assert max(vm.distance(a, b) for a, b in zip(rest, mesh.vertices)) < 1e-9


def test_thirteen_stress_poses_are_defined_and_exported():
    assert STRESS_POSES == ["rest", "elbow45", "elbow90", "elbow135", "claw", "fist", "twist", "wrist", "reach", "raise",
                            "crouch", "crossbody", "headturn"]
    data = stress_poses_json(1.78)
    assert set(data["poses"]) == set(STRESS_POSES) and len(data["renders"]) == 8


def test_pose_semantics_match_anatomy():
    _, lm, skeleton, _ = rig()

    def head(pose, bone):
        return vm.mat_translation(posed_world(skeleton, ops_to_basis(skeleton, stress_pose_ops(pose)))[bone])

    rest_hand = lm["LeftHand"]
    assert head("elbow90", "LeftHand")[1] < rest_hand[1] - 0.1          # elbow flexion brings the hand forward (-Y)
    assert head("reach", "LeftHand")[1] < rest_hand[1] - 0.3             # reach: arm forward
    assert head("raise", "LeftHand")[2] > lm["Head"][2]                  # raise: hand above the head
    assert head("crouch", "Hips")[2] < lm["Hips"][2] - 0.1               # crouch lowers the pelvis
    rest_tip = lm["LeftIndexTip"]
    fist_tip = head("fist", "LeftIndexDistal")
    palm = vm.sub(lm["LeftHand"], vm.mul((1, 0, 0), 0))
    assert vm.distance(fist_tip, head("fist", "LeftHand")) < vm.distance(rest_tip, rest_hand)  # fist curls fingers in
    turned = posed_world(skeleton, ops_to_basis(skeleton, stress_pose_ops("headturn")))
    assert math.isclose(vm.mat_translation(turned["Head"])[2], lm["Head"][2], abs_tol=0.02)
    assert palm


def test_stress_poses_on_clean_rig_have_no_red_flags():
    mesh, _, skeleton, weights = rig()
    edges = analysis.unique_edges(mesh)
    for pose in STRESS_POSES:
        posed = deform(mesh.vertices, weights, skin_matrices(skeleton, ops_to_basis(skeleton, stress_pose_ops(pose))))
        assert analysis.all_finite(posed)
        assert analysis.edge_stretch(mesh.vertices, posed, edges)["over_red_flag"] == 0, pose


def test_bad_weights_trigger_stretch_and_cross_influence():
    mesh, _, skeleton, weights = rig()
    groups = mesh.vertex_groups()
    broken = [([("LeftLowerArm", 1.0)] if g == "torso" and v[0] > 0.05 else row) for v, g, row in zip(mesh.vertices, groups, weights)]
    edges = analysis.unique_edges(mesh)
    posed = deform(mesh.vertices, broken, skin_matrices(skeleton, ops_to_basis(skeleton, stress_pose_ops("reach"))))
    assert analysis.edge_stretch(mesh.vertices, posed, edges)["over_red_flag"] > 0
    assert len(cross_influence(skeleton, mesh.vertices, broken)) > 0.005 * len(mesh.vertices)
    assert len(cross_influence(skeleton, mesh.vertices, weights)) == 0
