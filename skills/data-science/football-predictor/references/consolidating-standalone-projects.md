# Consolidating Standalone Predictor Projects

Use this reference when the user asks to stop maintaining a separate local project and make a Hermes skill the single source of truth for a small runnable predictor.

## Pattern

1. Keep the class-level skill as the canonical home.
2. Move runnable code into `scripts/`.
3. Move sample or working data into `data/`.
4. Move dependency notes and clean templates into `references/`.
5. Update `SKILL.md` with:
   - canonical directory;
   - run commands from the skill root;
   - maintenance rule that standalone exports are non-canonical;
   - verification checklist.
6. Archive the old standalone directory with a reversible rename instead of deleting it, unless the user explicitly requests deletion.

## Path Pitfall

After moving a CLI from a project root into `scripts/`, any relative data lookup such as `Path(__file__).parent / "data"` usually becomes wrong. Prefer resolving data from the skill root, for example:

```python
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
```

## Verification

- Compile moved Python files with `python3 -m py_compile`.
- Verify the CLI can resolve data paths from the skill root.
- If runtime dependencies are missing, record the install command but do not treat the missing package as a durable skill constraint.
