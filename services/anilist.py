from __future__ import annotations

import httpx
from typing import List, Optional

from pydantic import TypeAdapter

from models import AniMedia, AniTitle, AniMediaDetails


ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"


SEARCH_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 10) {
    media(type: ANIME, search: $search, sort: [SEARCH_MATCH, POPULARITY_DESC]) {
      id
      title { romaji english native }
      synonyms
    }
  }
}
"""


async def search_titles(client: httpx.AsyncClient, user_input: str) -> List[AniMedia]:
    payload = {"query": SEARCH_QUERY, "variables": {"search": user_input}}
    resp = await client.post(ANILIST_GRAPHQL_URL, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("data", {}).get("Page", {}).get("media", [])

    adapter = TypeAdapter(list[AniMedia])
    return adapter.validate_python([
        {
            "id": m.get("id"),
            "title": m.get("title", {}),
            "synonyms": m.get("synonyms", []) or [],
        }
        for m in raw
    ])


DETAILS_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    description(asHtml: false)
    coverImage { large medium color }
    bannerImage
    siteUrl
    format
    status
    episodes
    duration
    season
    seasonYear
    averageScore
    meanScore
    genres
  }
}
"""


async def fetch_details(client: httpx.AsyncClient, media_id: int) -> Optional[AniMediaDetails]:
    payload = {"query": DETAILS_QUERY, "variables": {"id": media_id}}
    resp = await client.post(ANILIST_GRAPHQL_URL, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data", {}).get("Media")
    if not data:
        return None
    # Pydantic validation to our model
    return AniMediaDetails.model_validate(data)

