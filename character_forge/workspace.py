"""Character workspaces: characters/<id>/ with character.json, brief, references, stage runs and approvals."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import presets
from .config import load_machine
from .imageinfo import image_info
from .util import ForgeError, now, read_json, sha256_file, validate_id, write_json, write_text

CHARACTER_FORMAT = "character-forge/character@1"
VIEWS = ("front", "side", "back", "three_quarter", "portrait", "extra")


class Workspace:
    def __init__(self, root: Path, identifier: str):
        self.root = Path(root)
        self.id = validate_id(identifier)
        self.dir = self.root / "characters" / self.id

    # ------------------------------------------------------------ basics
    @property
    def character_path(self):
        return self.dir / "character.json"

    def exists(self):
        return self.character_path.is_file()

    def load(self):
        if not self.exists():
            raise ForgeError("No character %r; create it with `forge new %s --brief ...`" % (self.id, self.id))
        data = read_json(self.character_path)
        if data.get("format") != CHARACTER_FORMAT:
            raise ForgeError("Unsupported character.json format in " + str(self.dir))
        return data

    def save(self, data):
        write_json(self.character_path, data)

    @property
    def character(self):
        return self.load()

    @property
    def preset(self):
        return presets.load(self.load()["preset"], [self.root / "config" / "presets"])

    @property
    def machine(self):
        return load_machine(self.root)

    def stage_dir(self, stage):
        return self.dir / "stages" / stage

    def approvals_path(self):
        return self.dir / "approvals.json"

    def packages_dir(self):
        return self.root / "packages" / self.id

    # ------------------------------------------------------------ creation
    def create(self, brief: str, preset: str = "zombie", reference=None, view="front", review_policy="human",
               mode=None, motion_profile=None, height=None, seed=None, provenance="", adapters=None):
        if self.exists():
            raise ForgeError("Character %r already exists; existing work is preserved." % self.id)
        if not brief or not brief.strip():
            raise ForgeError("A text brief is required (it seeds references, prompts and review).")
        chosen = presets.load(preset, [self.root / "config" / "presets"])
        if review_policy not in ("human", "agent"):
            raise ForgeError("review policy must be human or agent")
        self.dir.mkdir(parents=True)
        for sub in ("reference", "stages", "notes"):
            (self.dir / sub).mkdir()
        data = {"format": CHARACTER_FORMAT, "id": self.id, "preset": chosen["name"], "brief": brief.strip(),
                "created": now(), "review_policy": review_policy,
                "mode": mode or self.machine.get("default_mode", "fake"), "adapters": dict(adapters or {}),
                "motion_profile": motion_profile or chosen.get("default_motion_profile", "pilot"),
                "params": {"height_m": float(height or chosen.get("default_height_m", 1.78)),
                           "seed": int(seed if seed is not None else (sum(ord(c) for c in self.id) * 7919) % 100000),
                           "reconstruct_backend": None, "texture_size": chosen["budgets"]["texture_size"],
                           "triangle_budget": chosen["budgets"]["triangles_lod0"]},
                "references": [], "landmarks_override": None,
                "motions": {"include": [], "exclude": [], "generate": []}}
        self.save(data)
        template = (Path(__file__).with_name("data") / "brief_template.md").read_text(encoding="utf-8")
        write_text(self.dir / "brief.md", template.format(id=self.id, brief=brief.strip(), preset=chosen["name"],
                                                         review_policy=review_policy, mode=data["mode"],
                                                         motion_profile=data["motion_profile"]))
        if reference:
            self.add_reference(reference, view, provenance or "supplied at creation")
        return data

    def add_reference(self, image, view="front", provenance=""):
        source = Path(image)
        if not source.is_file():
            raise ForgeError("Reference image not found: %s" % image)
        info = image_info(source)
        if view not in VIEWS:
            raise ForgeError("view must be one of " + ", ".join(VIEWS))
        data = self.load()
        target = self.dir / "reference" / ("%s%s" % (view, source.suffix.lower()))
        if target.exists():
            raise ForgeError("A %s reference already exists (%s); remove it or use view 'extra'." % (view, target.name))
        shutil.copy2(source, target)
        data["references"].append({"view": view, "file": target.relative_to(self.dir).as_posix(), "sha256": sha256_file(target),
                                   "width": info["width"], "height": info["height"], "format": info["format"],
                                   "provenance": provenance or "unspecified", "added": now()})
        self.save(data)
        return target
