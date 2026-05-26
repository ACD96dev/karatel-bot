import httpx
from typing import Optional
from .fetcher import Metadata


async def fetch_youtube(url: str) -> Optional[Metadata]:
    """Fetch YouTube video metadata via the oEmbed API — no auth required."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(oembed_url)
            r.raise_for_status()
            data = r.json()

        title = data.get("title")
        author = data.get("author_name")
        thumbnail = data.get("thumbnail_url")
        description = f"by {author}" if author else None

        return Metadata(title=title, description=description, image_url=thumbnail, source="youtube")

    except Exception:
        return None
