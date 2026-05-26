"""
Shared utilities: popup rendering, keyboard builders, send-to-Karakeep helper,
and the allowed-user decorator used by every handler.
"""
from functools import wraps
from urllib.parse import urlparse
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..db.database import PendingItem, User
from ..karakeep.client import KarakeepList


# ── Auth decorator ─────────────────────────────────────────────────────────────

def allowed_users_only(func):
    """Silently drop any update from a user not in TELEGRAM_ALLOWED_USER_IDS."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        config = context.application.bot_data["config"]
        uid = update.effective_user.id if update.effective_user else None
        if uid not in config.allowed_user_ids:
            return
        return await func(update, context)
    return wrapper


# ── Shortcut accessors ─────────────────────────────────────────────────────────

def get_db(context):
    return context.application.bot_data["db"]

def get_config(context):
    return context.application.bot_data["config"]


# ── Popup text ─────────────────────────────────────────────────────────────────

def build_popup_text(item: PendingItem) -> str:
    lines = []

    # Header line: type indicator + domain/label
    if item.item_type == "link" and item.url:
        domain = urlparse(item.url).netloc.removeprefix("www.")
        lines.append(f"🔗 {domain}")
    elif item.item_type == "text":
        lines.append("📝 Note")
    elif item.item_type == "asset":
        lines.append(f"📎 {item.file_name or 'File'}")

    if item.title:
        lines.append(f"📌 {item.title}")

    if item.description:
        desc = item.description
        if len(desc) > 220:
            desc = desc[:220] + "…"
        lines.append(f"💬 {desc}")

    if item.selected_list_name:
        lines.append(f"📂 → {item.selected_list_name}")

    if item.tags:
        lines.append(f"🏷️ {item.tags}")

    return "\n".join(lines) if lines else "Item ready to save."


# ── Keyboard builders ──────────────────────────────────────────────────────────

def build_main_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Pick List", callback_data=f"lists:{item_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{item_id}"),
        ],
        [
            InlineKeyboardButton("✅ Send", callback_data=f"send:{item_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{item_id}"),
        ],
    ])


def build_edit_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Lists", callback_data=f"lists:{item_id}"),
            InlineKeyboardButton("📝 Title", callback_data=f"edttitle:{item_id}"),
            InlineKeyboardButton("🏷️ Tags", callback_data=f"edttags:{item_id}"),
        ],
        [
            InlineKeyboardButton("✅ Send", callback_data=f"send:{item_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{item_id}"),
        ],
    ])


def _build_ordered_list_rows(lists: list) -> list:
    """Return lists ordered as: parent → its children (indented), then next parent, etc."""
    parents = [l for l in lists if not l.parent_id]
    children_by_parent: dict = {}
    known_ids = {l.id for l in lists}
    for l in lists:
        if l.parent_id:
            children_by_parent.setdefault(l.parent_id, []).append(l)

    ordered = []
    for parent in parents:
        ordered.append((parent, False))  # (list, is_child)
        for child in children_by_parent.get(parent.id, []):
            ordered.append((child, True))

    # Orphaned sub-lists (parent not returned by API) — show at end
    for l in lists:
        if l.parent_id and l.parent_id not in known_ids:
            ordered.append((l, True))

    return ordered


def build_list_keyboard(lists: list, item_id: int) -> InlineKeyboardMarkup:
    rows = []
    for lst, is_child in _build_ordered_list_rows(lists):
        label = f"  ↳ {lst.name}" if is_child else lst.name
        rows.append([InlineKeyboardButton(label, callback_data=f"sl:{item_id}:{lst.id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"backmain:{item_id}")])
    return InlineKeyboardMarkup(rows)


def build_bulk_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Assign List", callback_data="blists")],
        [
            InlineKeyboardButton("✅ Send All", callback_data="bsend"),
            InlineKeyboardButton("❌ Cancel", callback_data="bcancel"),
        ],
    ])


def build_bulk_list_keyboard(lists: list) -> InlineKeyboardMarkup:
    rows = []
    for lst, is_child in _build_ordered_list_rows(lists):
        label = f"  ↳ {lst.name}" if is_child else lst.name
        rows.append([InlineKeyboardButton(label, callback_data=f"bsl:{lst.id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="bbackmain")])
    return InlineKeyboardMarkup(rows)


# ── Popup lifecycle helpers ────────────────────────────────────────────────────

async def show_popup(update: Update, context, item: PendingItem) -> int:
    """Send the popup message and return the Telegram message_id."""
    text = build_popup_text(item)
    keyboard = build_main_keyboard(item.id)
    msg = await update.effective_message.reply_text(text, reply_markup=keyboard)
    return msg.message_id


async def refresh_popup(context, chat_id: int, message_id: int, item: PendingItem, edit_mode: bool = False):
    """Edit an existing popup in place."""
    text = build_popup_text(item)
    keyboard = build_edit_keyboard(item.id) if edit_mode else build_main_keyboard(item.id)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
        )
    except Exception:
        pass  # Message may already be gone — harmless


async def delete_popup(context, chat_id: int, message_id: Optional[int]):
    if message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
