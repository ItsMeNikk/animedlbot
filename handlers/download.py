from __future__ import annotations
import asyncio
import os
import logging
import html
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from services import aria
from services.nyaa_html import HtmlTorrent

DOWNLOADS_DIR = Path("downloads")
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov"}
TELEGRAM_FILE_LIMIT_BYTES = 2147483648

async def on_download_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data:
        return
    await q.answer()

    prefix, token = q.data.split("::", 1)
    
    it_dict = context.chat_data.get("nyaa_items", {}).get(token)
    if not it_dict:
        await q.edit_message_text("❓ Download selection has expired. Please search again.")
        return

    torrent = HtmlTorrent.model_validate(it_dict)
    download = aria.add_magnet(torrent.magnet)
    if not download:
        await q.edit_message_text("❗️ Failed to send download to aria2c. Is the daemon running?")
        return
    
    initial_text = f"✅ **Download queued:**\n<code>{html.escape(torrent.title)}</code>"
    status_msg = await q.edit_message_text(initial_text, parse_mode="HTML")
    
    job_context = {
        "chat_id": update.effective_chat.id,
        "message_id": status_msg.message_id,
        "gid": download.gid,
        "torrent_name": torrent.title
    }
    
    context.job_queue.run_once(_monitor_download, 5, data=job_context, name=f"monitor_{download.gid}")

async def _monitor_download(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_context = context.job.data
    chat_id = job_context["chat_id"]
    message_id = job_context["message_id"]
    gid = job_context["gid"]
    torrent_name = job_context["torrent_name"]

    download = aria.get_download(gid)

    if not download:
        await context.bot.edit_message_text("❓ Download not found in aria2c queue.", chat_id=chat_id, message_id=message_id)
        return

    # --- If download is NOT complete, show detailed stats and reschedule ---
    if not download.is_complete:
        name_escaped = html.escape(torrent_name)
        status_text = (
            f"⏳ <b>Downloading:</b> <code>{name_escaped}</code>\n\n"
            f"├─ <b>Progress:</b> <code>{download.progress_string}</code>\n"
            f"├─ <b>Speed:</b> <code>{download.download_speed}</code>\n"
            f"├─ <b>Peers:</b> <code>{download.num_seeders} seeders</code>\n"
            f"└─ <b>ETA:</b> <code>{download.eta}</code>"
        )
        try:
            await context.bot.edit_message_text(status_text, chat_id=chat_id, message_id=message_id, parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" not in str(e):
                logging.warning(f"Error updating status for GID {gid}: {e}")
        
        context.job_queue.run_once(_monitor_download, 5, data=job_context, name=f"monitor_{gid}")
        return

    # --- If download IS complete, proceed with upload ---
    await context.bot.edit_message_text(
        f"✅ <b>Download complete!</b>\n<code>{html.escape(torrent_name)}</code>\n\nFinalizing files, please wait...",
        chat_id=chat_id, message_id=message_id, parse_mode="HTML"
    )
    await asyncio.sleep(5) # Wait for filesystem
    
    download.update()

    files_to_upload = sorted(
        [f for f in download.files if Path(f.path).suffix.lower() in VIDEO_EXTENSIONS and Path(f.path).exists() and Path(f.path).stat().st_size > 0],
        key=lambda x: x.path
    )

    if not files_to_upload:
        await context.bot.send_message(chat_id, "❗️ No video files (.mkv, .mp4) were found in the completed download.")
        download.remove(clean=True)
        return

    # Delete the main status message as we will now send per-file updates
    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)

    # --- Per-File Uploading Logic ---
    for i, file in enumerate(files_to_upload):
        file_path = Path(file.path)
        
        # Omit check `if not file_path.exists():` because it is already in list comprehension
        
        if file.length > TELEGRAM_FILE_LIMIT_BYTES:
            await context.bot.send_message(chat_id, f"⚠️ **Skipping file:** `{file_path.name}`\nReason: Exceeds Telegram's 2 GB limit.", parse_mode="Markdown")
            continue

        size_mb = file.length / 1024**2
        upload_msg = await context.bot.send_message(
            chat_id,
            f"📤 <b>Uploading file {i+1}/{len(files_to_upload)}:</b>\n"
            f"<code>{html.escape(file_path.name)}</code>\n"
            f"<b>Size:</b> {size_mb:.2f} MB",
            parse_mode="HTML"
        )

        try:
            with open(file_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id, document=f, filename=file_path.name,
                    read_timeout=120, write_timeout=120, connect_timeout=30
                )
            await upload_msg.delete() # Remove the "Uploading..." message
        except Exception as e:
            error_text = html.escape(str(e))
            await upload_msg.edit_text(
                f"❗️ <b>Failed to upload:</b>\n<code>{html.escape(file_path.name)}</code>\n"
                f"<b>Error:</b> <code>{error_text}</code>",
                parse_mode="HTML"
            )
            logging.error(f"Failed to upload {file_path.name}: {e}")

    # --- Cleanup Logic ---
    cleanup_msg = await context.bot.send_message(chat_id, "🧹 Cleaning up downloaded files from the server...")
    try:
        download.remove(clean=True)
        await cleanup_msg.edit_text("✅ Cleanup complete.")
    except Exception as e:
        await cleanup_msg.edit_text(f"❗️ Could not clean up files automatically. Error: {e}")
