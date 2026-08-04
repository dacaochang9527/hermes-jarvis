#!/usr/bin/env python3
"""PVC2701 normal review, quality-gate, and Feishu-document entry point."""

from pvc2701_adapter import load_publisher


_IMPL = load_publisher()


if __name__ == "__main__":
    raise SystemExit(_IMPL.main())

