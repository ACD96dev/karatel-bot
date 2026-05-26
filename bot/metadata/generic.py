import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Optional
from .fetcher import Metadata

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
)


async def fetch_generic(url: str) -> Optional[Metadata]:
    """Fetch OG tags and standard meta tags via plain HTTP — no browser."""
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text

        soup = BeautifulSoup(html, "lxml")

        title = (
            _og(soup, "og:title")
            or _meta(soup, "twitter:title")
            or _tag_text(soup, "title")
        )
        description = (
            _og(soup, "og:description")
            or _meta(soup, "twitter:description")
            or _meta(soup, "description")
        )
        image = _og(soup, "og:image") or _meta(soup, "twitter:image")

        if image and not image.startswith("http"):
            image = urljoin(url, image)

        return Metadata(title=title, description=description, image_url=image, source="generic")

    except Exception:
        return None


def _og(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=prop)
    val = tag.get("content") if tag else None
    return val.strip() if val else None


def _meta(soup: BeautifulSoup, name: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"name": name})
    val = tag.get("content") if tag else None
    return val.strip() if val else None


def _tag_text(soup: BeautifulSoup, tag: str) -> Optional[str]:
    t = soup.find(tag)
    text = t.get_text().strip() if t else None
    return text if text else None
