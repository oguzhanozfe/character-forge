# characters/

One workspace per character, created by `forge new <id>`:

```
characters/<id>/
  character.json      identity, preset, review policy, modes, params, references, motion steering   (committable)
  brief.md            the brief and identity checklist                                               (committable)
  approvals.json      every approve/reject decision bound to a run hash and gate report              (committable)
  gates/              summary.json/.csv + contact-sheet-request.json (committable); contact-sheet.png (ignored)
  reference/          reference images (ignored)
  stages/<stage>/     current.json + runs/<hash>/ with all intermediates, reports and logs (ignored)
  motions/            optional character-local motion library (ignored)
```

Intermediates never leave this folder except through `forge package`.
