# Claude Code instructions

Follow [AGENTS.md](AGENTS.md) - it is the contract for every agent in this repository - and use the skill
[.agents/skills/character-forge/SKILL.md](.agents/skills/character-forge/SKILL.md) for the step-by-step procedure.

Claude-specific notes:

* You can read PNG files directly: after `forge run` stops at a gate, open the images listed by `forge show <id> --stage <stage>`
  (`preview.png`, `pose-sheet.png`, `renders/*.png`, `characters/<id>/gates/contact-sheet.png`) and describe what you
  see before asking the human to approve. Say plainly when you cannot judge something from a thumbnail.
* Ask for approval with the exact command you will run, e.g.
  `forge approve demo --stage preflight --by human --note "<owner's words>"`, and run it only after the human agrees.
* Long real-mode stages (reconstruction, Kimodo) hold the machine-wide `gpu` lock; run them in the background and wait for
  completion instead of polling in a tight loop.
* Before finishing a session: `forge clean <id>` for characters you worked on, remove scratch files you created, and
  report what is fake, what is real, which gates are WARN/FAIL and what the human still needs to review.
