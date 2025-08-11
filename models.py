from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class AniTitle(BaseModel):
    romaji: Optional[str] = None
    english: Optional[str] = None
    native: Optional[str] = None


class AniMedia(BaseModel):
    id: int
    title: AniTitle
    synonyms: List[str] = []

class AniCoverImage(BaseModel):
    large: Optional[str] = None
    medium: Optional[str] = None
    color: Optional[str] = None


class AniMediaDetails(BaseModel):
    id: int
    title: AniTitle
    description: Optional[str] = None
    coverImage: Optional[AniCoverImage] = None
    bannerImage: Optional[str] = None
    siteUrl: Optional[str] = None
    format: Optional[str] = None
    status: Optional[str] = None
    episodes: Optional[int] = None
    duration: Optional[int] = None
    season: Optional[str] = None
    seasonYear: Optional[int] = None
    averageScore: Optional[int] = None
    meanScore: Optional[int] = None
    genres: List[str] = []

# Torrent models removed (using nyaabag methods instead)

