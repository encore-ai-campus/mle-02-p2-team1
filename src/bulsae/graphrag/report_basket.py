"""Local, persistent collection of answer snapshots for report preparation."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[3] / 'private_data' / 'report_basket.sqlite'


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS basket (id TEXT PRIMARY KEY, saved_at TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


def answer_id(result):
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    return str(result.get('run_id') or hashlib.sha256(payload.encode('utf-8')).hexdigest())


def save_answer(result, path=DEFAULT_PATH):
    """Save an answer once per execution; never replace an existing snapshot."""
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    item_id = answer_id(result)
    with closing(_connect(path)) as db, db:
        cursor = db.execute("INSERT OR IGNORE INTO basket (id, saved_at, payload) VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?)",
                            (item_id, payload))
        return cursor.rowcount == 1


def list_answers(path=DEFAULT_PATH):
    if not Path(path).exists():
        return []
    with closing(_connect(path)) as db:
        rows = db.execute('SELECT id, saved_at, payload FROM basket ORDER BY rowid DESC').fetchall()
    return [{'id': item_id, 'saved_at': saved_at, 'result': json.loads(payload)}
            for item_id, saved_at, payload in rows]


def remove_answer(item_id, path=DEFAULT_PATH):
    if not Path(path).exists():
        return
    with closing(_connect(path)) as db, db:
        db.execute('DELETE FROM basket WHERE id = ?', (item_id,))
