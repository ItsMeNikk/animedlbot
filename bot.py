from __future__ import annotations
import logging
import os
import traceback
import html
import json
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

import httpx
from dotenv import load_dotenv
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from handlers.search import on_message_search, on_title_selected
from handlers.nyaa_search import on_nyaa_pick
from handlers.download import on_download_request

async def _post_init(app: Application) -> None:
    app.bot_data["http_session"] = httpx.AsyncClient(headers={"User-Agent": "animedlbot/0.1"})

async def _post_shutdown(app: Application) -> None:
    client = app.bot_data.pop("http_session", None)
    if client is not None:
        await client.aclose()

def build_application() -> Application:
    load_dotenv()
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN missing in environment")

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Set higher logging level for third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)

    builder = ApplicationBuilder().token(bot_token)
    try:
        from telegram.ext import AIORateLimiter
        builder = builder.rate_limiter(AIORateLimiter())
    except Exception:
        pass

    app = builder.post_init(_post_init).post_shutdown(_post_shutdown).build()

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_name = escape_markdown(user.first_name, version=2)
        user_username = f"@{escape_markdown(user.username, version=2)}" if user.username else "N/A"
        user_id = user.id
        welcome_text = f"""
*Welcome to the Anime Torrent Bot, {user_name}\\!*

*Your Info:*
 `> User:` {user_username}
 `> ID:  ` {user_id}

*How to Use:*
`1\\.` Send any anime title to start a search
`2\\.` Select the correct series from the results
`3\\.` Choose your preferred release group
`4\\.` Filter by quality and audio type
`5\\.` Get your magnet link\\!

Just type an anime title to get started 📥
        """
        await update.message.reply_text(welcome_text, parse_mode="MarkdownV2")
    
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start_command(update, context)
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message_search))
    app.add_handler(CallbackQueryHandler(on_title_selected, pattern=r"^t::"))
    app.add_handler(CallbackQueryHandler(on_nyaa_pick, pattern=r"^(xs::|rq::|qu::|ra::|rp::|rm::|info|cancel_dl)"))
    app.add_handler(CallbackQueryHandler(on_download_request, pattern=r"^dl::"))

    # --- NEW, MORE ROBUST ERROR HANDLER ---
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and send a detailed message to the developer."""
        
        logger.error("Exception while handling an update:", exc_info=context.error)

        # Extract traceback
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)

        # Format update for logging
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        
        message = (
            f"An exception was raised while handling an update\n"
            f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
            "</pre>\n\n"
            f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
            f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
            f"<pre>{html.escape(tb_string)}</pre>"
        )

        # Try to notify the user
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❗️ *Oops\\! Something went wrong\\.*\n\nPlease try your request again\\.",
                parse_mode="MarkdownV2"
            )

    app.add_error_handler(error_handler)
    
    return app

def main() -> None:
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
