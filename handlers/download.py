from __future__ import annotations
import asyncio
import os
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from services import aria
from services.nyaa_html import HtmlTorrent

DOWNLOADS_DIR = Path("downloads")
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov"}

async def on_download_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data:
        return
    await q.answer()

    prefix, token = q.data.split("::", 1)
    
    it_dict = context.chat_data.get("nyaa_items", {}).get(token)
    if not it_dict:
        await q.edit_message_text("? Download selection has expired. Please search again.")
        return

    torrent = HtmlTorrent.model_validate(it_dict)
    download = aria.add_magnet(torrent.magnet)
    if not download:
        await q.edit_message_text("? Failed to send download to aria2c. Is the daemon running?")
        return
    
    status_msg = await q.edit_message_text(f"? Download added to queue: *{download.name}*", parse_mode="Markdown")
    
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
        await context.bot.edit_message_text("? Download not found.", chat_id=chat_id, message_id=message_id)
        return

    # --- NEW ROBUST CHECK ---
    # We check both aria2's status AND if the real video file is actually on the disk.
    is_physically_downloaded = False
    if download.is_complete:
        # Check if the file(s) actually exist on disk and are not temporary.
        video_files_on_disk = [
            f for f in download.files 
            if Path(f.path).suffix.lower() in VIDEO_EXTENSIONS and Path(f.path).exists()
        ]
        if video_files_on_disk:
            is_physically_downloaded = True

    if not is_physically_downloaded:
        progress = download.progress_string
        eta = download._download.eta_string()
        status_text = (
            f"? Downloading *{torrent_name}*...\n\n"
            f"`{progress}`\n"
            f"`ETA: {eta}`"
        )
        try:
            await context.bot.edit_message_text(status_text, chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
        except Exception as e:
            if "Message is not modified" not in str(e):
                print(f"Error updating status: {e}")
        
        context.job_queue.run_once(_monitor_download, 10, data=job_context, name=f"monitor_{gid}")
        return

    # --- Proceed with Upload ---
    await context.bot.edit_message_text(f"? Download complete for *{torrent_name}*! Preparing to upload...", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
    
    files_to_upload = sorted(
        [f for f in download.files if Path(f.path).suffix.lower() in VIDEO_EXTENSIONS], 
        key=lambda x: x.path
    )

    if not files_to_upload:
        await context.bot.send_message(chat_id, "? No video files (.mkv, .mp4) were found in the completed download.")
        download.remove(clean=True)
        return

    TELEGRAM_FILE_LIMIT_BYTES = 2147483648
    for i, file in enumerate(files_to_upload):
        file_path = Path(file.path)
        if not file_path.exists():
            await context.bot.send_message(chat_id, f"? An error occurred: Final file path not found for `{file_path.name}`.", parse_mode="Markdown")
            continue
        
        if file.length > TELEGRAM_FILE_LIMIT_BYTES:
            await context.bot.send_message(chat_id, f"?? Skipping `{file_path.name}` because it exceeds Telegram's 2 GB limit.", parse_mode="Markdown")
            continue

        await context.bot.send_message(chat_id, f"?? Uploading file {i+1}/{len(files_to_upload)}: `{file_path.name}`", parse_mode="Markdown")
        
        try:
            with open(file_path, 'rb') as f:
                await context.bot.send_document(chat_id, document=f, filename=file_path.name)
        except Exception as e:
            await context.bot.send_message(chat_id, f"? Failed to upload `{file_path.name}`. Error: {e}", parse_mode="Markdown")

    cleanup_msg = await context.bot.send_message(chat_id, "?? Cleaning up downloaded files from the server...")
    try:
        download.remove(clean=True)
        await cleanup_msg.edit_text("? Cleanup complete.")
    except Exception as e:
        await cleanup_msg.edit_text("? Could not clean up files automatically.")