import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)
from .config import load_config
from .db.database import Database
from .handlers.commands import (
    start_command, setapi_command, bulk_command, normal_command,
    send_command, register_commands,
)
from .handlers.messages import handle_message
from .handlers.callbacks import handle_callback

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

log = logging.getLogger("karabot")


async def post_init(application: Application) -> None:
    db: Database = application.bot_data["db"]
    await db.init()
    log.info("Database initialised at %s", db.path)
    await register_commands(application.bot)
    log.info("Bot commands registered with Telegram")


def main():
    config = load_config()
    db = Database(config.database_path)

    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    app.bot_data["config"] = config
    app.bot_data["db"] = db

    # Commands
    app.add_handler(CommandHandler("start",   start_command))
    app.add_handler(CommandHandler("setapi", setapi_command))
    app.add_handler(CommandHandler("bulk",    bulk_command))
    app.add_handler(CommandHandler("normal",  normal_command))
    app.add_handler(CommandHandler("send",    send_command))

    # All incoming messages (text, photo, document)
    app.add_handler(
        MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, handle_message)
    )

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info(
        "KaraBot starting — %d allowed user(s), enrichment=%s",
        len(config.allowed_user_ids),
        config.metadata_enrichment,
    )
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
