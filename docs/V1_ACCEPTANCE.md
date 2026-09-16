# V1 acceptance — 2026-09-17

Smart Python Builder V1 = COMPLETE. Phase 2–8 = CLOSED.

72 automated tests passed. 21 Windows executable checks passed. Console programs were run with exit/output assertions; GUI processes were started for ten seconds and their test process trees stopped. Deliberate failure rows pass when the expected failure and bounded recovery behavior occurs.

| Case | Status | Build ID |
|---|---|---|
| stdlib CLI | PASS | `dab1f64e6e884db4b0c490afd670d3b5` |
| requests | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| pandas | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| openpyxl | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| numpy | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| OpenCV | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| Pillow | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| pyserial | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| PyYAML | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| multi-file project | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| JSON config | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| image assets | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| requirements project | PASS | `ac8f4b303ba74fa3a6e457275c338803` |
| Tkinter | PASS | `0bc53798ecf34779aea4890483e65213` |
| PySide6 | PASS | `e97d561408274fa6b0e48773b2c4b8a5` |
| PyQt6 | PASS | `cf28016e40e146cb887b11373790b6e6` |
| pyproject project | PASS | `27f4ad351bc9497c98107377ee539efe` |
| normal build failure | PASS | `b4f6aa19477e48888a4feeadbc1ee567` |
| AI repair failure | PASS | `3f8a7dacec774905b0639d04c734000d` |
| AI repair success | PASS | `6b8f66cbd5e4493bb0b603fc0f438ae4` |
| approved experience hit | PASS | `1dc6593812c9461991d53c0bbdd312d3` |

Full artifact paths and behavior notes: [JSON matrix](v1-acceptance.json).
Web onedir ZIP acceptance: [record](phase8-web-acceptance.json).

The library cases share one executable with separate functional assertions. FakeAIProvider and FakeNotifier exercised recovery and notification behavior; real API billing and Feishu delivery were not invoked. The supplied Windows user ran the suite; a separate low-privilege account was not provisioned. See [operations and security](OPERATIONS.md).

## Phase history

| Phase | Implementation commit | Main merge |
|---|---|---|
| 2 | fe7b743 | 4e68ea5 |
| 3 | 26e7c29 | 87f777d |
| 4 | 5da0550 | da8cb70 |
| 5 | 11296eb | 6059c9a |
| 6 | d734b88 | 3a5481c |
| 7 | 90908b2 | e826860 |
