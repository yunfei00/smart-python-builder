import json

import pandas as pd
import requests


def main() -> None:
    frame = pd.DataFrame([{"builder": "smart-python-builder", "status": "ok"}])
    payload = {
        "pandas_rows": len(frame),
        "requests_version": requests.__version__,
    }
    print(json.dumps(payload, ensure_ascii=False))
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
