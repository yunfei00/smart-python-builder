# Windows verification

Run `./run_phase2_tests.ps1` from PowerShell in the repository root.
It runs the complete pytest suite, builds OpenCV and the multi-file PySide6
project in independent environments, checks the console executable's exit code
and output, starts the GUI executable for ten seconds, and stops its process
tree. A third build checks an uploaded pyproject.toml is preserved without
colliding with the generated environment metadata.

Results (Build ID, artifact, behavior) are saved to `docs/phase2-acceptance.json`.
Scratch directories stay under the repository to avoid Windows TEMP ACL issues.
Phase 1 samples are retained as regression inputs; its historical script builds
all three samples using automatic dependency detection.
