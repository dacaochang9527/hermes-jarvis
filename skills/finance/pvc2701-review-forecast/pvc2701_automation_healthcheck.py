#!/usr/bin/env python3
"""PVC2701 automation pre-flight healthcheck entry point."""

from pvc2701_adapter import load_healthcheck


_IMPL = load_healthcheck()

for _name, _value in vars(_IMPL).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


if __name__ == "__main__":
    raise SystemExit(_IMPL.main())
