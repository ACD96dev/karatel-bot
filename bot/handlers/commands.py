"""
/start, /setapi, /bulk, /normal, /send
"""
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.ext import ContextTypes

from .common import allowed_users_only, get_db, get_config, build_bulk_main_keyboard
from ..karakeep.client import KarakeepClient


@allowed_users_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *KaraTel Bot* — Karakeep ingestion bot with metadata editing, image, note & bulk support\n"
        "_Built for quick mobile efficiency_\n\n"
        "👉 *First time?* Type /setapi to connect your Karakeep account before sending anything.\n\n"
        "*Normal mode* (default)\n"
        "Send me a link, image, PDF, .md file, or plain text and I'll show you a save popup.\n\n"
        "*Bulk mode*\n"
        "Use /bulk to enter bulk mode. Send items one by one — I'll queue them quietly.\n"
        "Type /send when done to dispatch everything at once.\n\n"
        "*Commands*\n"
        "/start — this message\n"
        "/setapi — link or update your Karakeep API key\n"
        "/bulk — enter bulk mode\n"
        "/normal — force return to normal mode\n\n"
        "Made by [ACD96dev](https://github.com/ACD96dev) · [Buy Me a Coffee](https://buymeacoffee.com/acd96)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


@allowed_users_only
async def setapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context)
    config = get_config(context)
    user_id = update.effective_user.id

    db_user = await db.get_user(user_id)
    session = await db.get_session(user_id)

    status = "✅ Linked" if db_user else "❌ Not linked"
    mode = session.get("mode", "normal").capitalize()

    lists_info = ""
    if db_user:
        try:
            client = KarakeepClient(config.karakeep_internal_url, db_user.karakeep_api_key)
            lists = await client.get_lists()
            lists_info = f"\n📋 *Lists available:* {len(lists)}"
        except Exception:
            lists_info = "\n📋 Lists: (could not reach Karakeep)"

    link_prompt = (
        "\n\nTo link or re-link your Karakeep account, paste your API key now.\n"
        "_(Generate one in Karakeep → Settings → API Keys)_"
    )
    view_prompt = (
        "\n\nTo re-link your account, paste your API key now.\n"
        "_(Generate one in Karakeep → Settings → API Keys)_"
    )

    text = (
        f"⚙️ *Settings*\n\n"
        f"👤 Account: {status}{lists_info}\n"
        f"🔄 Mode: {mode}"
        + (view_prompt if db_user else link_prompt)
    )
    await update.message.reply_text(text, parse_mode="Markdown")

    # Only enter "waiting for API key" state — the next plain text message will be treated as a key.
    # This is intentional: /setapi is the explicit entry point for key linking.
    await db.set_session(user_id, waiting_for="api_key")


@allowed_users_only
async def bulk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context)
    user_id = update.effective_user.id
    session = await db.get_session(user_id)

    if session.get("mode") == "bulk":
        queue = await db.get_bulk_queue(user_id)
        await update.message.reply_text(
            f"Already in bulk mode. {len(queue)} item(s) queued.\nType /send to dispatch or /normal to cancel."
        )
        return

    await db.set_session(user_id, mode="bulk", waiting_for=None, waiting_context=None)
    await update.message.reply_text(
        "📦 *Bulk mode ON*\n\nSend items one at a time. I'll queue them quietly.\nType /send when done to dispatch everything.",
        parse_mode="Markdown",
    )


@allowed_users_only
async def normal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context)
    user_id = update.effective_user.id

    await db.clear_bulk_queue(user_id)
    await db.set_session(user_id, mode="normal", waiting_for=None, waiting_context=None)
    await update.message.reply_text("↩️ Back to normal mode. Bulk queue cleared.")


@allowed_users_only
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatches the bulk queue as a consolidated popup."""
    db = get_db(context)
    user_id = update.effective_user.id
    session = await db.get_session(user_id)

    if session.get("mode") != "bulk":
        await update.message.reply_text(
            "You're not in bulk mode. Use the ✅ Send button in the popup, "
            "or type /bulk to enter bulk mode."
        )
        return

    queue = await db.get_bulk_queue(user_id)
    if not queue:
        await update.message.reply_text("Your bulk queue is empty. Send some items first.")
        return

    n = len(queue)
    summary_lines = []
    for item in queue:
        if item.item_type == "link":
            from urllib.parse import urlparse
            domain = urlparse(item.url or "").netloc.removeprefix("www.")
            label = item.title or domain or item.url or "link"
        elif item.item_type == "text":
            label = "Note: " + (item.text_content or "")[:40]
        else:
            label = f"File: {item.file_name or 'asset'}"
        summary_lines.append(f"  • {label}")

    assigned = queue[0].selected_list_name
    list_line = f"\n📂 List: {assigned}" if assigned else ""

    text = (
        f"📦 Ready to send {n} item(s){list_line}\n\n"
        + "\n".join(summary_lines[:10])
        + ("\n  …" if n > 10 else "")
    )
    keyboard = build_bulk_main_keyboard()
    await update.message.reply_text(text, reply_markup=keyboard)


async def register_commands(bot):
    """Register the persistent menu button commands with Telegram."""
    commands = [
        BotCommand("start", "Usage guide"),
        BotCommand("setapi", "Link or update your Karakeep API key"),
        BotCommand("bulk", "Enter bulk mode"),
        BotCommand("normal", "Return to normal mode"),
    ]
    await bot.set_my_commands(commands)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
