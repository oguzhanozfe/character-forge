"""Adapters to external tools. Every adapter supports three modes:

  fake     deterministic synthetic outputs in pure Python (no GPU, no downloads, any OS) - for CI and dry rehearsal
  dry-run  record the exact commands that would run, execute nothing
  real     call the configured tool (Blender headless, a reconstruction backend, Kimodo, Unity batchmode)
"""
