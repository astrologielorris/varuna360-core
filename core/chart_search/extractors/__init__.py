# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Extractors: the one seam between Find Chart and the calculation code.

One module per extractor, each exporting ``EXTRACTOR``; ``registry.py``
imports them explicitly (no discovery, like ``core/capabilities/registry.py``).
"""
