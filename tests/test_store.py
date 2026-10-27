import sqlite3

from notify_hub.models import Level, make_message
from notify_hub.store import SCHEMA_VERSION, Outbox

# 第一段建的表：没有 kind、bundle_id
STEP_ONE_SCHEMA = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, source TEXT NOT NULL, level TEXT NOT NULL,
    title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', link TEXT, msg_key TEXT, dedup_key TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL, claimed_at REAL,
    sent_at REAL, last_error TEXT, note TEXT
);
"""


def test_upgrades_a_step_one_database(tmp_path):
    path = tmp_path / "outbox.db"
    conn = sqlite3.connect(path)
    conn.executescript(STEP_ONE_SCHEMA)
    conn.execute(
        "INSERT INTO messages (created_at, source, level, title, dedup_key, status) VALUES (1, 'mail', 'digest', '旧消息', 'k', 'digest')"
    )
    conn.commit()
    conn.close()

    box = Outbox(path)
    row = box.get(1)
    assert row["title"] == "旧消息" and row["kind"] == "message" and row["bundle_id"] is None
    assert box.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert box.make_bundle(status="digest", level=Level.DIGEST, title=str, now=2) == (2, 1)
    box.close()
    Outbox(path).close()  # 再打开一次也没问题


def test_each_message_goes_into_one_card_only(tmp_path):
    first, second = Outbox(tmp_path / "o.db"), Outbox(tmp_path / "o.db")
    for i in range(3):
        first.add(make_message(f"m{i}", level="digest"), dedup_key=f"k{i}", status="digest", now=10)
    first.add(make_message("later", level="digest"), dedup_key="k9", status="digest", now=30)
    assert first.make_bundle(status="digest", level=Level.DIGEST, title=str, now=20) == (5, 3)
    assert second.make_bundle(status="digest", level=Level.DIGEST, title=str, now=20) is None
    assert [r["title"] for r in second.members(5)] == ["m0", "m1", "m2"]
    card = second.get(5)
    assert card["kind"] == "bundle" and card["status"] == "pending" and card["title"] == "3"
    assert second.get(4)["status"] == "digest"  # 合并之后才来的，留到下一次
    first.close()
    second.close()


def test_meta_swap_lets_only_one_process_win(tmp_path):
    first, second = Outbox(tmp_path / "o.db"), Outbox(tmp_path / "o.db")
    first.meta_init("last_digest_at", "1.0")
    first.meta_init("last_digest_at", "9.0")  # 已经有了，不改
    assert second.meta_get("last_digest_at") == "1.0"
    assert first.meta_swap("last_digest_at", "1.0", "2.0")
    assert not second.meta_swap("last_digest_at", "1.0", "3.0")
    assert second.meta_get("last_digest_at") == "2.0"
    assert first.meta_swap("other", None, "x") and not second.meta_swap("other", None, "y")
    assert first.meta_get("missing") is None
    first.close()
    second.close()
