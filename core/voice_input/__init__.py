# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Local voice input (td-mgcw8, test stage; main and LTS since 2026-10-22): speech to text on the
user's own computer with sherpa-onnx, no graphics card and no account.

Qt-free. ``catalog`` lists the models the app can install, ``store`` downloads
and unpacks them into a per-user cache folder shared by every checkout, and
``engine`` turns 16 kHz mono samples into text. The Settings > Voice Input
section (``ui/voice_input_settings.py``) is the only caller for now; the AI
task window comes after the test."""
