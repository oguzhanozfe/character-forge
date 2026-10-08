"""Stage interface. A stage declares its upstream stages, the adapter whose mode applies, its parameters,
runs into a fresh run directory keyed by the hash of all inputs, and returns labelled outputs plus a gate."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..gates import Gate


@dataclass
class Context:
    ws: object
    character: dict
    preset: dict
    machine: dict
    stage: str
    run_dir: Path
    mode: str
    inputs: dict            # "stage.label" -> Path
    upstream: dict          # stage -> run record
    params: dict
    log: Callable = print
    plan: list = field(default_factory=list)

    def out(self, name) -> Path:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def thresholds(self):
        return self.preset.get("thresholds", {})

    @property
    def height(self):
        return float(self.character["params"]["height_m"])

    def owner(self):
        return "forge:%s:%s" % (self.ws.id, self.stage)

    def gate(self):
        return Gate(self.stage, self.ws.id, self.mode)


class Stage:
    name = ""
    title = ""
    version = 1
    needs: tuple = ()
    adapter = "python"          # reconstruct | blender | kimodo | unity | python
    tool_files: tuple = ()      # extra files whose bytes are part of the input hash (e.g. Blender scripts)

    def params(self, ws, character, preset, machine) -> dict:
        return {}

    def extra_inputs(self, ws, character, machine) -> dict:
        """Files outside upstream stages that feed this stage (references, libraries)."""
        return {}

    def run(self, ctx: Context) -> dict:
        raise NotImplementedError

    def gate(self, ctx: Context, outputs: dict) -> Gate:
        raise NotImplementedError
