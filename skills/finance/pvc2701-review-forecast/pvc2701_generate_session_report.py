#!/usr/bin/env python3
"""PVC2701 report-generator entry point."""

from pvc2701_adapter import load_generator


_IMPL = load_generator()

for _name, _value in vars(_IMPL).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


if __name__ == "__main__":
    raise SystemExit(_IMPL.main())

