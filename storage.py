"""Local settings, OS credential store, and durable publication history."""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import keyring

DEFAULTS = {
    "model": "gpt-4.1-mini", "ig_user_id": "", "graph_version": "v24.0",
    "cloud_name": "", "fixed_hashtags": "", "tone": "친근",
    "token_expires_at": "",
}
SECRET_NAMES = ("openai_key", "ig_token", "cloud_api_key", "cloud_api_secret")


def app_dir():
    root = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "InstaUploader"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(name, default):
    path = app_dir() / name
    if not path.exists():
        return default.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError):
        raise ValueError(f"{name} 파일을 읽지 못했습니다. 파일을 백업한 뒤 확인해 주세요.") from None


def write_json(name, data):
    path = app_dir() / name
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_config():
    data = read_json("config.json", {})
    return {key: data.get(key, value) for key, value in DEFAULTS.items()}


def save_config(config):
    write_json("config.json", {key: config.get(key, value) for key, value in DEFAULTS.items()})


def credential_store():
    if os.name == "nt":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    backend = keyring.get_keyring()
    # Never fall back to keyrings.alt's plaintext/encrypted-file backends.
    if not type(backend).__module__.startswith((
        "keyring.backends.SecretService", "keyring.backends.kwallet", "keyring.backends.macOS"
    )):
        raise ValueError("보안 자격 증명 저장소를 사용할 수 없습니다. Windows에서 실행해 주세요.")
    return backend


def get_secret(name):
    if name not in SECRET_NAMES:
        raise ValueError("알 수 없는 자격 증명입니다.")
    try:
        return credential_store().get_password("InstaUploader", name) or ""
    except Exception:
        raise ValueError("보안 자격 증명 저장소에 접근하지 못했습니다. Windows 로그인 상태를 확인해 주세요.") from None


def save_secret(name, value):
    if name not in SECRET_NAMES:
        raise ValueError("알 수 없는 자격 증명입니다.")
    try:
        credential_store().set_password("InstaUploader", name, value)
    except Exception:
        raise ValueError("비밀값을 안전하게 저장하지 못했습니다. Windows 자격 증명 관리자를 확인해 주세요.") from None


def database():
    connection = sqlite3.connect(app_dir() / "history.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
        product TEXT NOT NULL, caption TEXT NOT NULL, images TEXT NOT NULL,
        status TEXT NOT NULL, media_id TEXT DEFAULT '', permalink TEXT DEFAULT '',
        detail TEXT DEFAULT '')""")
    connection.commit()
    return connection


def start_record(product, caption, paths):
    with closing(database()) as db, db:
        cursor = db.execute(
            "INSERT INTO posts(created_at,product,caption,images,status) VALUES(?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), json.dumps(product, ensure_ascii=False),
             caption, json.dumps([str(p) for p in paths], ensure_ascii=False), "준비 중"),
        )
        return cursor.lastrowid


def update_record(record_id, status, media_id="", permalink="", detail=""):
    with closing(database()) as db, db:
        db.execute("UPDATE posts SET status=?,media_id=?,permalink=?,detail=? WHERE id=?",
                   (status, media_id, permalink, detail, record_id))


def history():
    with closing(database()) as db:
        return [dict(row) for row in db.execute("SELECT * FROM posts ORDER BY id DESC")]
