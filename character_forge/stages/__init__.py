"""The pipeline DAG, in order:

reference -> reconstruct -> preflight -> lowmesh -> rig -> pose-screen -> unity-import -> motion-screen -> package
"""
from .lowmesh import LowmeshStage
from .motion_screen import MotionScreenStage
from .package import PackageStage
from .pose_screen import PoseScreenStage
from .preflight import PreflightStage
from .reconstruct import ReconstructStage
from .reference import ReferenceStage
from .rig import RigStage
from .unity_import import UnityImportStage

STAGES = [ReferenceStage(), ReconstructStage(), PreflightStage(), LowmeshStage(), RigStage(), PoseScreenStage(),
          UnityImportStage(), MotionScreenStage(), PackageStage()]
ORDER = [s.name for s in STAGES]
BY_NAME = {s.name: s for s in STAGES}
