from __future__ import annotations
import hashlib
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.anilist import search_titles, fetch_details
from fuzzywuzzy import process
from utils.text import normalize_query, escape_html, sanitize_description

# The load_index function is now defined here to fix the import error
def load_index(csv_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(csv_path, header=1)
        df.set_index(df.columns[0], inplace=True)
        return df
    except FileNotFoundError:
        return pd.DataFrame({'Title': [], 'Alternate Title': []})

async def on_message_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return

    query = normalize_query(update.message.text)
    if not query.startswith('/') and query:
        client = context.application.bot_data.get("http_session")
        results = await search_titles(client, query)

        if not results:
            try:
                df = load_index("nyaabag/index_seadex.csv")
                all_titles = pd.concat([df['Title'], df['Alternate Title']]).dropna().tolist()
                suggestion, score = process.extractOne(query, all_titles)
                
                if score > 80:
                    button = InlineKeyboardButton(
                        text=f"Search for: {suggestion}",
                        switch_inline_query_current_chat=suggestion
                    )
                    await update.message.reply_text(
                        "No results found. Did you mean:",
                        reply_markup=InlineKeyboardMarkup([[button]])
                    )
                else:
                    await update.message.reply_text("No results found.")
            except (FileNotFoundError, ValueError):
                 await update.message.reply_text("No results found.")
            return

        items = []
        for m in results:
            display = m.title.english or m.title.romaji or m.title.native or str(m.id)
            candidates = list(filter(None, [m.title.english, m.title.romaji, m.title.native] + (m.synonyms or [])))
            items.append((display, candidates))

        titles = [d for d, _ in items]
        choice, _ = process.extractOne(query, titles, score_cutoff=60) or (None, 0)

        if choice and choice in titles:
            idx = titles.index(choice)
            items.insert(0, items.pop(idx))

        store = context.chat_data.setdefault("title_tokens", {})
        buttons = []
        for display, candidates in items[:10]:
            token = hashlib.sha1(display.encode("utf-8")).hexdigest()[:12]
            store[token] = {"display": display, "queries": candidates}
            buttons.append([InlineKeyboardButton(text=display, callback_data=f"t::{token}")])
        
        await update.message.reply_text("Select a title:", reply_markup=InlineKeyboardMarkup(buttons))


async def on_title_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("t::"): return

    token = data.split("::", 1)[1]
    token_entry = context.chat_data.get("title_tokens", {}).get(token)
    if not token_entry:
        await query.edit_message_text("Selection expired. Please send the title again.")
        return
        
    display_title = token_entry.get("display", "")
    candidate_queries = token_entry.get("queries") or [display_title]

    await query.edit_message_text(f"Fetching details for: {display_title}…")
    client = context.application.bot_data.get("http_session")
    ani = await search_titles(client, display_title)
    media = ani[0] if ani else None
    if not media:
        await query.edit_message_text("Could not fetch details. Please try another title.")
        return

    details = await fetch_details(client, media.id)
    if not details:
        await query.edit_message_text("No details found.")
        return

    name = escape_html(details.title.english or details.title.romaji or details.title.native or str(details.id))
    desc = sanitize_description(details.description)
    genres = ", ".join(details.genres or [])
    
    info_lines = [
        f"🎬 <b>{name}</b>",
        f"🗂️ Format: {escape_html(details.format or 'N/A')} | 📺 Status: {escape_html(details.status or 'N/A')}",
        f"🎞️ Episodes: {details.episodes or 'N/A'} | ⏱️ Duration: {details.duration or 'N/A'} min",
        f"📅 Season: {escape_html(details.season or 'N/A')} {details.seasonYear or ''}",
        f"⭐ Score: {details.averageScore or details.meanScore or 'N/A'}",
        f"🏷️ Genres: {escape_html(genres)}" if genres else "",
        f"📝 {escape_html(desc)}" if desc else "",
        f"🔗 More: {escape_html(details.siteUrl)}" if details.siteUrl else "",
    ]
    text = "\n".join(filter(None, info_lines))

    cover = details.coverImage.large if details.coverImage else None
    
    qtokens = context.chat_data.setdefault("nyaa_query_tokens", {})
    qtok = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    qtokens[qtok] = candidate_queries
    buttons = [[InlineKeyboardButton(text="📥 Show downloading options", callback_data=f"xs::{qtok}")]]
    
    if cover:
        await query.message.reply_photo(photo=cover, caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))