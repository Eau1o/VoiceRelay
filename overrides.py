import json
import os
import tempfile
from pathlib import Path


def read(path):
    try:
        contents = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    records = json.loads(contents)
    if not isinstance(records, dict) or any(
        not key or value not in ("TYPELESS", "WETYPE") for key, value in records.items()
    ):
        raise ValueError("overrides.json 格式错误")
    return {key.lower(): value for key, value in records.items()}


def save(path, records):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="overrides-", suffix=".tmp", delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write((json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
