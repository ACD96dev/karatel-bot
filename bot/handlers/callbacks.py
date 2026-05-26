"""
Inline keyboard callback handler — all button presses route through here.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from .common import (
    allowed_users_only, get_db, get_config,
    build_main_keyboard, build_edit_keyboard,
    build_list_keyboard, build_bulk_main_keyboard, build_bulk_list_keyboard,
    build_popup_text, delete_popup, refresh_popup,
)
from ..karakeep.client import KarakeepClient, send_item_to_karakeep

log = logging.getLogger(__name__)


@allowed_users_only
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    db = get_db(context)
    config = get_config(context)

    # ── Normal-mode single-item callbacks ──────────────────────────────────────

    if data.startswith("send:"):
        await _cb_send(query, context, user_id, chat_id, int(data.split(":")[1]))

    elif data.startswith("cancel:"):
        await _cb_cancel(query, context, user_id, chat_id, int(data.split(":")[1]))

    elif data.startswith("lists:"):
        await _cb_show_lists(query, context, user_id, int(data.split(":")[1]))

    elif data.startswith("edit:"):
        await _cb_edit_mode(query, context, int(data.split(":")[1]))

    elif data.startswith("sl:"):
        # sl:{item_id}:{list_id}
        parts = data.split(":", 2)
        await _cb_select_list(query, context, user_id, int(parts[1]), parts[2])

    elif data.startswith("edttitle:"):
        await _cb_edit_field(query, context, user_id, chat_id, int(data.split(":")[1]), "title")

    elif data.startswith("edttags:"):
        await _cb_edit_field(query, context, user_id, chat_id, int(data.split(":")[1]), "tags")

    elif data.startswith("backmain:"):
        await _cb_back_to_main(query, context, int(data.split(":")[1]))

    # ── Bulk-mode callbacks ────────────────────────────────────────────────────

    elif data == "bsend":
        await _cb_bulk_send(query, context, user_id, chat_id)

    elif data == "bcancel":
        await _cb_bulk_cancel(query, context, user_id, chat_id)

    elif data == "blists":
        await _cb_bulk_show_lists(query, context, user_id)

    elif data.startswith("bsl:"):
        list_id = data.split(":", 1)[1]
        await _cb_bulk_select_list(query, context, user_id, list_id)

    elif data == "bbackmain":
        await _cb_bulk_back_main(query, context, user_id)


# ── Single-item handlers ───────────────────────────────────────────────────────

async def _cb_send(query, context, user_id: int, chat_id: int, item_id: int):
    db = get_db(context)
    config = get_config(context)

    item = await db.get_pending_item(item_id)
    if not item:
        await query.edit_message_text("⚠️ Item not found — it may have already been sent.")
        return

    db_user = await db.get_user(user_id)
    if not db_user:
        await query.edit_message_text("⚠️ No Karakeep account linked. Use /setapi.")
        return

    await query.edit_message_text("⏳ Saving…")
    try:
        bookmark_id = await send_item_to_karakeep(item, db_user, context.bot, config)
        await db.delete_pending_item(item_id)
        view_url = f"{config.karakeep_external_url}/bookmarks/{bookmark_id}"
        await query.edit_message_text(
            f"✅ Saved!\n[View in Karakeep]({view_url})",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("Failed to save item %s", item_id)
        await query.edit_message_text(f"❌ Save failed: {e}\n\nTry again or use /setapi to re-check your API key.")


async def _cb_cancel(query, context, user_id: int, chat_id: int, item_id: int):
    db = get_db(context)
    await db.delete_pending_item(item_id)
    await db.clear_waiting(user_id)
    try:
        await query.delete_message()
    except Exception:
        await query.edit_message_text("❌ Cancelled.")


async def _cb_show_lists(query, context, user_id: int, item_id: int):
    db = get_db(context)
    config = get_config(context)
    db_user = await db.get_user(user_id)
    if not db_user:
        await query.answer("No Karakeep account linked — use /setapi.", show_alert=True)
        return

    item = await db.get_pending_item(item_id)
    if not item:
        return

    try:
        client = KarakeepClient(config.karakeep_internal_url, db_user.karakeep_api_key)
        lists = await client.get_lists()
    except Exception:
        await query.answer("Could not reach Karakeep. Check server is running.", show_alert=True)
        return

    keyboard = build_list_keyboard(lists, item_id)
    text = build_popup_text(item) + "\n\n_Choose a list:_"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _cb_edit_mode(query, context, item_id: int):
    db = get_db(context)
    item = await db.get_pending_item(item_id)
    if not item:
        return
    text = build_popup_text(item)
    await query.edit_message_text(text, reply_markup=build_edit_keyboard(item_id))


async def _cb_select_list(query, context, user_id: int, item_id: int, list_id: str):
    db = get_db(context)
    config = get_config(context)
    db_user = await db.get_user(user_id)
    if not db_user:
        return

    # Look up the list name
    list_name = list_id  # fallback
    try:
        client = KarakeepClient(config.karakeep_internal_url, db_user.karakeep_api_key)
        lists = await client.get_lists()
        for lst in lists:
            if lst.id == list_id:
                list_name = lst.name
                break
    except Exception:
        pass

    item = await db.get_pending_item(item_id)
    if not item:
        return

    item.selected_list_id = list_id
    item.selected_list_name = list_name
    await db.update_pending_item(item)

    # Return to main popup view
    text = build_popup_text(item)
    await query.edit_message_text(text, reply_markup=build_main_keyboard(item_id))


async def _cb_edit_field(query, context, user_id: int, chat_id: int, item_id: int, field: str):
    db = get_db(context)
    item = await db.get_pending_item(item_id)
    if not item:
        return

    prompts = {
        "title": f"📝 Send me the new title:\n_(current: {item.title or 'none'})_",
        "tags": f"🏷️ Send me tags (comma-separated):\n_(current: {item.tags or 'none'})_",
    }
    prompt_text = prompts.get(field, "Send the new value:")

    prompt_msg = await context.bot.send_message(chat_id=chat_id, text=prompt_text, parse_mode="Markdown")
    await db.set_session(
        user_id,
        waiting_for=field,
        waiting_context={
            "item_id": item_id,
            "prompt_message_id": prompt_msg.message_id,
        },
    )


async def _cb_back_to_main(query, context, item_id: int):
    db = get_db(context)
    item = await db.get_pending_item(item_id)
    if not item:
        return
    text = build_popup_text(item)
    await query.edit_message_text(text, reply_markup=build_main_keyboard(item_id))


# ── Bulk handlers ──────────────────────────────────────────────────────────────

async def _cb_bulk_send(query, context, user_id: int, chat_id: int):
    db = get_db(context)
    config = get_config(context)
    db_user = await db.get_user(user_id)
    if not db_user:
        await query.edit_message_text("⚠️ No Karakeep account linked. Use /setapi.")
        return

    queue = await db.get_bulk_queue(user_id)
    if not queue:
        await query.edit_message_text("Queue is empty.")
        return

    await query.edit_message_text(f"⏳ Saving {len(queue)} item(s)…")

    success = 0
    failed = 0
    for item in queue:
        try:
            await send_item_to_karakeep(item, db_user, context.bot, config)
            success += 1
        except Exception:
            log.exception("Bulk save failed for item %s", item.id)
            failed += 1

    await db.clear_bulk_queue(user_id)
    await db.set_session(user_id, mode="normal", waiting_for=None, waiting_context=None)

    result = f"✅ {success} saved"
    if failed:
        result += f", ❌ {failed} failed"
    result += "\n↩️ Returned to normal mode."

    view_url = config.karakeep_external_url
    await query.edit_message_text(
        f"{result}\n\n[Open Karakeep]({view_url})", parse_mode="Markdown"
    )


async def _cb_bulk_cancel(query, context, user_id: int, chat_id: int):
    db = get_db(context)
    await db.clear_bulk_queue(user_id)
    await db.set_session(user_id, mode="normal", waiting_for=None, waiting_context=None)
    await query.edit_message_text("❌ Bulk session cancelled. Queue cleared.\n↩️ Normal mode.")


async def _cb_bulk_show_lists(query, context, user_id: int):
    db = get_db(context)
    config = get_config(context)
    db_user = await db.get_user(user_id)
    if not db_user:
        await query.answer("No Karakeep account linked.", show_alert=True)
        return

    try:
        client = KarakeepClient(config.karakeep_internal_url, db_user.karakeep_api_key)
        lists = await client.get_lists()
    except Exception:
        await query.answer("Could not reach Karakeep.", show_alert=True)
        return

    queue = await db.get_bulk_queue(user_id)
    n = len(queue)
    assigned = queue[0].selected_list_name if queue else None
    list_line = f"\n📂 Currently: {assigned}" if assigned else ""

    text = f"📦 {n} item(s) queued{list_line}\n\n_Choose a list to assign to all:_"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=build_bulk_list_keyboard(lists))


async def _cb_bulk_select_list(query, context, user_id: int, list_id: str):
    db = get_db(context)
    config = get_config(context)
    db_user = await db.get_user(user_id)
    if not db_user:
        return

    list_name = list_id
    try:
        client = KarakeepClient(config.karakeep_internal_url, db_user.karakeep_api_key)
        lists = await client.get_lists()
        for lst in lists:
            if lst.id == list_id:
                list_name = lst.name
                break
    except Exception:
        pass

    await db.set_bulk_list(user_id, list_id, list_name)
    await _cb_bulk_back_main(query, context, user_id)


async def _cb_bulk_back_main(query, context, user_id: int):
    db = get_db(context)
    queue = await db.get_bulk_queue(user_id)
    n = len(queue)
    assigned = queue[0].selected_list_name if queue else None
    list_line = f"\n📂 List: {assigned}" if assigned else ""
    text = f"📦 *{n} item(s) queued*{list_line}\n\nType /send to dispatch or add more items."
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=build_bulk_main_keyboard())
