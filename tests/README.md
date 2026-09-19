# Tests

Run the automated regression suite on every change:

```powershell
uv run pytest
```

Pytest covers analyzer, build planning/engine behavior, AI repair contracts, experience learning,
notifications, administrator/settings behavior, repository import, stability/security limits and Web APIs.

For release candidates on Windows, run the maintained real-build matrix:

```powershell
uv run python tests/windows_acceptance.py
```

Additional focused Windows acceptance scripts remain for Web upload/ZIP flows, notification URLs,
AI repair/learning and deliberate packaging failures. They are explicit release/diagnostic checks and
are not collected by pytest.

`tests/samples/` contains small reusable application fixtures. Generated workspaces, acceptance
results and build artifacts must stay outside source control.
