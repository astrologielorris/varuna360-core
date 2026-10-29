# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Screen recorder, Qt-free half (SPEC-REC-001).

Pure pieces the manager and the dialog share: quality presets and the size
estimate, region math, the ffmpeg command line, audio device listing, output
naming and crash recovery, the notification silencer and the microphone level
watch. Nothing here imports Qt.
"""
