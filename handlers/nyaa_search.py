from __future__ import annotations
import hashlib
import math
import re
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.nyaa_html import search_nyaa_html, HtmlTorrent

PAGE_SIZE = 10

def _get_release_group(title: str) -> str:
    match = re.search(r'\[([^\]]+)\]', title)
    return match.group(1).strip() if match else "Unknown"

def _is_dub(title: str) -> bool:
    return any(keyword in title.lower() for keyword in ["dub", "dubbed", "dual audio"])

def _format_torrent_label(item: HtmlTorrent) -> str:
    title = re.sub(r'\[[^\]]+\]', '', item.title).strip()
    prefix = "📦 " if item.is_too_large else ""
    return f"{prefix}{title} | {item.size_str or 'Unknown'}"

def _extract_episode_num(title: str) -> int:
    lower_title = title.lower()
    batch_match = re.search(r'(\d{1,4})\s*[-~]\s*\d{1,4}', lower_title)
    if batch_match: return int(batch_match.group(1))
    ep_match = re.search(r'(?i)(?:e|ep|episode\s?|\s-\s)(\d{1,4})', lower_title)
    if ep_match: return int(ep_match.group(1))
    return 9999

def _sort_torrents(items: list[HtmlTorrent]) -> list[HtmlTorrent]:
    return sorted(items, key=lambda item: _extract_episode_num(item.title))

def _deduplicate_torrents(torrents: list[HtmlTorrent]) -> list[HtmlTorrent]:
    def get_dedupe_key(title: str) -> tuple:
        normalized = title.lower()
        normalized = re.sub(r'\[[^\]]+\]', '', normalized)
        normalized = re.sub(r'\(.*?\)|v\d', '', normalized)
        normalized = re.sub(r'\.\w+$', '', normalized).strip()
        episode = _extract_episode_num(title)
        return (normalized, episode)

    grouped = defaultdict(list)
    for torrent in torrents:
        key = get_dedupe_key(torrent.title)
        grouped[key].append(torrent)
    
    deduplicated_list = [max(group, key=lambda x: x.seeders) for group in grouped.values()]
    return deduplicated_list

def _render_magnets_keyboard(context: ContextTypes.DEFAULT_TYPE, items: list[HtmlTorrent], page_token: str, page: int) -> InlineKeyboardMarkup:
    sorted_items = _sort_torrents(items)
    start, end = page * PAGE_SIZE, (page + 1) * PAGE_SIZE
    slice_items = sorted_items[start:end]
    store = context.chat_data.setdefault("nyaa_items", {})
    buttons = []
    for it in slice_items:
        key = hashlib.sha1(it.magnet.encode()).hexdigest()[:12]
        store[key] = it.model_dump()
        buttons.append([InlineKeyboardButton(text=_format_torrent_label(it), callback_data=f"rm::{key}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("« Prev", callback_data=f"rp::{page_token}::{page-1}"))
    if end < len(sorted_items): nav.append(InlineKeyboardButton("Next »", callback_data=f"rp::{page_token}::{page+1}"))
    if nav: buttons.append(nav)

    return InlineKeyboardMarkup(buttons)

async def on_nyaa_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query_list: list[str]) -> None:
    message = update.effective_message
    if not message: return
    search_msg = await message.reply_text("🔍 Searching for torrents...")
    client = context.application.bot_data.get("http_session")

    results = []
    for query in query_list:
        try:
            current_results = await search_nyaa_html(client, query)
            if current_results: results.extend(current_results)
        except Exception: continue
    
    seen_magnets = set()
    unique_results = [res for res in results if res.magnet not in seen_magnets and not seen_magnets.add(res.magnet)]
    results = _deduplicate_torrents(unique_results)

    if not results:
        await search_msg.edit_text("❌ No torrents found. Try a different anime or check the spelling.")
        return

    grouped_by_release = defaultdict(list)
    for torrent in results:
        grouped_by_release[_get_release_group(torrent.title)].append(torrent)

    gstore = context.chat_data.setdefault("nyaa_groups", {})
    buttons = []
    sorted_groups = sorted(grouped_by_release.items(), key=lambda x: len(x[1]), reverse=True)

    for group_name, group_items in sorted_groups:
        token = hashlib.sha1(f"{query_list[0]}|{group_name}".encode()).hexdigest()[:12]
        gstore[token] = [item.model_dump() for item in group_items]
        oversized_count = sum(1 for item in group_items if item.is_too_large)
        label = f"📁 {group_name} ({len(group_items)} results"
        if oversized_count > 0: label += f", {oversized_count} bundled"
        label += ")"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"rq::{token}")])

    await search_msg.edit_text("🎬 Select a release group:", reply_markup=InlineKeyboardMarkup(buttons))

def _validate_torrent_items(items_dict: list) -> list[HtmlTorrent]:
    items = []
    if not isinstance(items_dict, list): return []
    for d in items_dict:
        try:
            if isinstance(d, dict): items.append(HtmlTorrent.model_validate(d))
        except Exception as e:
            print(f"Skipping invalid item: {d} - Error: {e}")
            continue
    return items

async def on_nyaa_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data: return
    await q.answer()
    data = q.data
    
    prefix, *parts = data.split("::")

    if prefix == "info":
        await q.answer("This icon indicates the torrent is an oversized bundle.", show_alert=True)
        return
        
    if prefix == "xs":
        token = parts[0]
        query_list = context.chat_data.get("nyaa_query_tokens", {}).get(token)
        if not query_list:
            await q.edit_message_text("Selection expired. Please search again.")
            return
        await on_nyaa_search(update, context, query_list)
        return
        
    if prefix == "cancel_dl":
        await q.edit_message_text(" Canceled.")
        return

    storage_key = {"rq": "nyaa_groups", "qu": "nyaa_quality_choice", "ra": "nyaa_audio_choice", "rp": "nyaa_pages", "rm": "nyaa_items"}.get(prefix)
    if not storage_key: return

    token = parts[0]
    
    if prefix == "rm":
        it_dict = context.chat_data.get(storage_key, {}).get(token)
        items = _validate_torrent_items([it_dict] if it_dict else [])
    else:
        items_dict = context.chat_data.get(storage_key, {}).get(token, [])
        items = _validate_torrent_items(items_dict)
    
    if not items and prefix != "rp":
        await q.edit_message_text("Selection expired or data is invalid.")
        return

    if prefix == "rq":
        quality_groups = defaultdict(list)
        for item in items: quality_groups[item.resolution or "Unknown"].append(item)
        
        qstore = context.chat_data.setdefault("nyaa_quality_choice", {})
        buttons = []
        for quality, quality_items in sorted(quality_groups.items(), key=lambda x: x[0], reverse=True):
            token_q = hashlib.sha1(f"{token}|{quality}".encode()).hexdigest()[:12]
            qstore[token_q] = [item.model_dump() for item in quality_items]
            oversized_count = sum(1 for item in quality_items if item.is_too_large)
            label = f"💿 {quality} ({len(quality_items)} results"
            if oversized_count > 0: label += f", {oversized_count} bundled"
            label += ")"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"qu::{token_q}")])
        await q.edit_message_text("✨ Select video quality:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if prefix == "qu" or prefix == "ra":
        has_sub = any(not _is_dub(item.title) for item in items)
        has_dub = any(_is_dub(item.title) for item in items)
        if prefix == "qu" and has_sub and has_dub:
            sub_token = hashlib.sha1(f"{token}|sub".encode()).hexdigest()[:12]
            dub_token = hashlib.sha1(f"{token}|dub".encode()).hexdigest()[:12]
            astore = context.chat_data.setdefault("nyaa_audio_choice", {})
            original_items_dict = context.chat_data.get("nyaa_quality_choice", {}).get(token, [])
            astore[sub_token] = [d for d in original_items_dict if not _is_dub(d['title'])]
            astore[dub_token] = [d for d in original_items_dict if _is_dub(d['title'])]
            buttons = [InlineKeyboardButton("Sub", callback_data=f"ra::{sub_token}"), InlineKeyboardButton("Dub", callback_data=f"ra::{dub_token}")]
            await q.edit_message_text("🎤 Select audio type:", reply_markup=InlineKeyboardMarkup([buttons]))
        else:
            page_token = hashlib.sha1(f"{token}|p".encode()).hexdigest()[:12]
            original_items_dict = context.chat_data.get(storage_key, {}).get(token, [])
            context.chat_data.setdefault("nyaa_pages", {})[page_token] = original_items_dict
            await q.edit_message_text(f"🔍 Found {len(items)} torrents:", reply_markup=_render_magnets_keyboard(context, items, page_token, 0))
        return

    if prefix == "rp":
        page_s = parts[1]
        page = int(page_s) if page_s.isdigit() else 0
        await q.edit_message_reply_markup(reply_markup=_render_magnets_keyboard(context, items, token, max(0, page)))
        return

    if prefix == "rm":
        it = items[0]
        # Show a confirmation message with Yes/No buttons
        confirm_button = InlineKeyboardButton("✅ Yes", callback_data=f"dl::{token}")
        cancel_button = InlineKeyboardButton("❌ No", callback_data="cancel_dl")

        text = f"❓ Are you sure you want to download this?\n\n`{it.title}`"
        await q.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[confirm_button, cancel_button]])
        )