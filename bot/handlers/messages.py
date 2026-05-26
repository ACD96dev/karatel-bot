"""
Incoming message handler — routes to normal mode, bulk mode, or input-waiting flows.
"""
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from .common import (
    allowed_users_only, get_db, get_config,
    build_popup_text, build_main_keyboard, show_popup,
)
from ..db.database import PendingItem
from ..metadata.fetcher import fetch_metadata

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@allowed_users_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context)
    config = get_config(context)
    message = update.message
    user_id = update.effective_user.id

    session = await db.get_session(user_id)

    # ── Waiting-for-input flows ────────────────────────────────────────────────
    if session.get("waiting_for") == "api_key":
        await _handle_api_key_input(update, context, session)
        return

    if session.get("waiting_for") in ("title", "tags"):
        await _handle_field_input(update, context, session)
        return

    # ── Require linked account for everything below ────────────────────────────
    db_user = await db.get_user(user_id)
    if not db_user:
        await message.reply_text(
            "👋 Your Karakeep account isn't linked yet.\n"
            "Type /setapi to connect it — you'll need your API key from:\n"
            "Karakeep → Settings → API Keys"
        )
        return

    # ── Detect item type and build PendingItem ─────────────────────────────────
    item = await _classify_message(message, user_id, config)
    if item is None:
        return

    is_bulk = session.get("mode") == "bulk"
    item.is_bulk = is_bulk

    item_id = await db.add_pending_item(item)
    item.id = item_id

    if is_bulk:
        queue = await db.get_bulk_queue(user_id)
        await message.reply_text(f"✓ Queued ({len(queue)} item(s) in batch)")
        return

    # Normal mode: show popup
    msg_id = await show_popup(update, context, item)
    item.popup_message_id = msg_id
    await db.update_pending_item(item)


# ── Input-waiting handlers ─────────────────────────────────────────────────────

async def _handle_api_key_input(update: Update, context, session: dict):
    db = get_db(context)
    config = get_config(context)
    user_id = update.effective_user.id
    raw = (update.message.text or "").strip()

    if not raw or len(raw) < 10:
        await update.message.reply_text("That doesn't look like a valid API key. Try again.")
        return

    # Quick validation: try fetching lists
    from ..karakeep.client import KarakeepClient
    client = KarakeepClient(config.karakeep_internal_url, raw)
    try:
        lists = await client.get_lists()
        await db.save_user(user_id, raw)
        await db.clear_waiting(user_id)
        await update.message.reply_text(
            f"✅ Linked! Found {len(lists)} list(s) in your Karakeep.\n"
            f"Send me a link, image, PDF, or text to get started."
        )
    except Exception:
        await update.message.reply_text(
            "❌ Could not connect to Karakeep with that key.\n"
            "Check the key is correct and Karakeep is reachable, then try again.\n"
            "Type /setapi to re-enter your API key."
        )


async def _handle_field_input(update: Update, context, session: dict):
    db = get_db(context)
    user_id = update.effective_user.id
    field = session.get("waiting_for")
    ctx = session.get("waiting_context") or {}
    item_id = ctx.get("item_id")
    chat_id = update.effective_chat.id

    if not item_id:
        await db.clear_waiting(user_id)
        return

    item = await db.get_pending_item(item_id)
    if not item:
        await db.clear_waiting(user_id)
        return

    value = (update.message.text or "").strip()
    if field == "title":
        item.title = value
    elif field == "tags":
        item.tags = value

    await db.update_pending_item(item)
    await db.clear_waiting(user_id)

    # Delete the "send me your title" prompt if we stored its id
    prompt_msg_id = ctx.get("prompt_message_id")
    if prompt_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
        except Exception:
            pass

    # Also delete the user's reply
    try:
        await update.message.delete()
    except Exception:
        pass

    # Refresh the popup
    if item.popup_message_id:
        from .common import build_edit_keyboard
        text = build_popup_text(item)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=item.popup_message_id,
                text=text,
                reply_markup=build_edit_keyboard(item_id),
            )
        except Exception:
            pass


# ── Message classification ─────────────────────────────────────────────────────

async def _classify_message(message, user_id: int, config) -> "PendingItem | None":
    """Return a PendingItem with metadata pre-fetched, or None if we can't handle it."""

    # Photo
    if message.photo:
        photo = message.photo[-1]
        item = PendingItem(
            telegram_id=user_id, is_bulk=False, item_type="asset",
            file_id=photo.file_id, file_name="photo.jpg",
            title=message.caption or None,
        )
        return item

    # Document (PDF, .md, anything else)
    if message.document:
        doc = message.document
        item = PendingItem(
            telegram_id=user_id, is_bulk=False, item_type="asset",
            file_id=doc.file_id, file_name=doc.file_name or "file",
            title=message.caption or doc.file_name or None,
        )
        return item

    # Text — may contain a URL
    if message.text:
        text = message.text.strip()
        url_match = _URL_RE.search(text)

        if url_match:
            url = url_match.group(0).rstrip(".,;)")
            meta = await fetch_metadata(url, config.metadata_enrichment)
            return PendingItem(
                telegram_id=user_id, is_bulk=False, item_type="link",
                url=url,
                title=meta.title,
                description=meta.description,
                image_url=meta.image_url,
            )
        else:
            # Pure text note
            return PendingItem(
                telegram_id=user_id, is_bulk=False, item_type="text",
                text_content=text,
                title=None,
            )

    return None
