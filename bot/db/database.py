import json
import aiosqlite
from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    telegram_id: int
    karakeep_api_key: str


@dataclass
class PendingItem:
    telegram_id: int
    is_bulk: bool
    item_type: str          # 'link' | 'text' | 'asset'
    id: Optional[int] = None
    url: Optional[str] = None
    text_content: Optional[str] = None
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    selected_list_id: Optional[str] = None
    selected_list_name: Optional[str] = None
    tags: Optional[str] = None
    popup_message_id: Optional[int] = None


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    karakeep_api_key TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    telegram_id INTEGER PRIMARY KEY,
                    mode TEXT DEFAULT 'normal',
                    waiting_for TEXT,
                    waiting_context TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    is_bulk INTEGER DEFAULT 0,
                    item_type TEXT NOT NULL,
                    url TEXT,
                    text_content TEXT,
                    file_id TEXT,
                    file_name TEXT,
                    title TEXT,
                    description TEXT,
                    image_url TEXT,
                    selected_list_id TEXT,
                    selected_list_name TEXT,
                    tags TEXT,
                    popup_message_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    # ── Users ─────────────────────────────────────────────────────────────────

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT telegram_id, karakeep_api_key FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ) as cur:
                row = await cur.fetchone()
                return User(telegram_id=row[0], karakeep_api_key=row[1]) if row else None

    async def save_user(self, telegram_id: int, api_key: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO users (telegram_id, karakeep_api_key) VALUES (?, ?)",
                (telegram_id, api_key),
            )
            await db.commit()

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def get_session(self, telegram_id: int) -> dict:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT mode, waiting_for, waiting_context FROM sessions WHERE telegram_id = ?",
                (telegram_id,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return {
                        "mode": row[0],
                        "waiting_for": row[1],
                        "waiting_context": json.loads(row[2]) if row[2] else None,
                    }
                return {"mode": "normal", "waiting_for": None, "waiting_context": None}

    async def set_session(
        self,
        telegram_id: int,
        mode: Optional[str] = None,
        waiting_for: Optional[str] = None,
        waiting_context: Optional[dict] = None,
    ):
        current = await self.get_session(telegram_id)
        new_mode = mode if mode is not None else current["mode"]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO sessions (telegram_id, mode, waiting_for, waiting_context, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    mode = excluded.mode,
                    waiting_for = excluded.waiting_for,
                    waiting_context = excluded.waiting_context,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_id,
                    new_mode,
                    waiting_for,
                    json.dumps(waiting_context) if waiting_context else None,
                ),
            )
            await db.commit()

    async def clear_waiting(self, telegram_id: int):
        await self.set_session(telegram_id, waiting_for=None, waiting_context=None)

    # ── Pending items ─────────────────────────────────────────────────────────

    async def add_pending_item(self, item: PendingItem) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO pending_items
                (telegram_id, is_bulk, item_type, url, text_content, file_id, file_name,
                 title, description, image_url, selected_list_id, selected_list_name, tags, popup_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.telegram_id, int(item.is_bulk), item.item_type,
                    item.url, item.text_content, item.file_id, item.file_name,
                    item.title, item.description, item.image_url,
                    item.selected_list_id, item.selected_list_name,
                    item.tags, item.popup_message_id,
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def get_pending_item(self, item_id: int) -> Optional[PendingItem]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT * FROM pending_items WHERE id = ?", (item_id,)
            ) as cur:
                row = await cur.fetchone()
                return self._row_to_item(row) if row else None

    async def update_pending_item(self, item: PendingItem):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE pending_items
                SET title = ?, description = ?, image_url = ?,
                    selected_list_id = ?, selected_list_name = ?,
                    tags = ?, popup_message_id = ?
                WHERE id = ?
                """,
                (
                    item.title, item.description, item.image_url,
                    item.selected_list_id, item.selected_list_name,
                    item.tags, item.popup_message_id, item.id,
                ),
            )
            await db.commit()

    async def delete_pending_item(self, item_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM pending_items WHERE id = ?", (item_id,))
            await db.commit()

    async def get_bulk_queue(self, telegram_id: int) -> list:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT * FROM pending_items WHERE telegram_id = ? AND is_bulk = 1 ORDER BY created_at",
                (telegram_id,),
            ) as cur:
                rows = await cur.fetchall()
                return [self._row_to_item(r) for r in rows]

    async def clear_bulk_queue(self, telegram_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM pending_items WHERE telegram_id = ? AND is_bulk = 1",
                (telegram_id,),
            )
            await db.commit()

    async def set_bulk_list(self, telegram_id: int, list_id: str, list_name: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE pending_items SET selected_list_id = ?, selected_list_name = ?
                WHERE telegram_id = ? AND is_bulk = 1
                """,
                (list_id, list_name, telegram_id),
            )
            await db.commit()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _row_to_item(self, row) -> PendingItem:
        return PendingItem(
            id=row[0], telegram_id=row[1], is_bulk=bool(row[2]),
            item_type=row[3], url=row[4], text_content=row[5],
            file_id=row[6], file_name=row[7], title=row[8],
            description=row[9], image_url=row[10],
            selected_list_id=row[11], selected_list_name=row[12],
            tags=row[13], popup_message_id=row[14],
        )
