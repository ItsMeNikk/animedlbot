from __future__ import annotations
import re
from typing import List, Dict
import httpx
from lxml import html
from pydantic import BaseModel
from collections import defaultdict

TELEGRAM_FILE_LIMIT_BYTES = 2147483648
_RES_RE = re.compile(r"(?i)(2160p|1440p|1080p|720p|480p)")

class HtmlTorrent(BaseModel):
    title: str
    magnet: str
    size_str: str | None = None
    size_bytes: int | None = None
    resolution: str | None = None
    is_too_large: bool = False
    seeders: int = 0 # New field for seeder count

def _parse_size_to_bytes(s: str) -> int | None:
    s = s.strip().upper()
    try:
        if "KIB" in s: return int(float(s.replace("KIB", "").strip()) * 1024)
        if "MIB" in s: return int(float(s.replace("MIB", "").strip()) * 1024**2)
        if "GIB" in s: return int(float(s.replace("GIB", "").strip()) * 1024**3)
        if "TIB" in s: return int(float(s.replace("TIB", "").strip()) * 1024**4)
    except (ValueError, TypeError): return None
    return None

def _extract_resolution(title: str) -> str | None:
    match = _RES_RE.search(title)
    return match.group(1) if match else None

def is_likely_bundle(title: str) -> bool:
    lower_title = title.lower()
    if any(keyword in lower_title for keyword in ["batch", "season", "complete", "s0", "episodes"]):
        return True
    if re.search(r'\d{1,4}\s*[-~]\s*\d{1,4}', lower_title):
        return True
    if "movie" in lower_title:
        return False
    return False

async def search_nyaa_html(
    client: httpx.AsyncClient, query: str, category: str = "1_2",
    filters: str = "2", page: int = 1
) -> List[HtmlTorrent]:
    params = {"q": query, "c": category, "f": filters, "p": page}
    headers = {"User-Agent": "animedlbot/1.0"}
    
    resp = await client.get("https://nyaa.si/", params=params, timeout=20, headers=headers)
    resp.raise_for_status()

    doc = html.fromstring(resp.text)
    results: List[HtmlTorrent] = []

    for tr in doc.xpath("//table[contains(@class,'torrent-list')]//tbody//tr"):
        title_links = tr.xpath(".//td[2]//a[not(contains(@class,'comments'))]")
        if not title_links: continue
        title_text = title_links[-1].text_content().strip()

        magnet_link = tr.xpath(".//a[starts-with(@href,'magnet:')]/@href")
        if not magnet_link: continue
        
        size_str = tr.xpath(".//td[4]/text()")[0].strip() if tr.xpath(".//td[4]/text()") else "Unknown"
        
        # Scrape seeder count
        seeders_text = tr.xpath(".//td[6]/text()")
        seeders = int(seeders_text[0].strip()) if seeders_text else 0

        size_bytes = _parse_size_to_bytes(size_str)
        is_too_large = (size_bytes is None) or (size_bytes > TELEGRAM_FILE_LIMIT_BYTES)

        if is_too_large and not is_likely_bundle(title_text):
            continue

        results.append(
            HtmlTorrent(
                title=title_text, magnet=magnet_link[0], size_str=size_str,
                size_bytes=size_bytes, resolution=_extract_resolution(title_text),
                is_too_large=is_too_large, seeders=seeders
            )
        )
    return results

def group_by_resolution(torrents: list[HtmlTorrent]) -> Dict[str, list[HtmlTorrent]]:
    groups: Dict[str, list[HtmlTorrent]] = defaultdict(list)
    for r in torrents:
        groups[r.resolution or "unknown"].append(r)
    return dict(sorted(groups.items()))