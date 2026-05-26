from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


@dataclass
class Metadata:
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    source: str = "generic"


async def fetch_metadata(url: str, enrichment_enabled: bool = True) -> Metadata:
    """
    Dispatch to the appropriate domain-specific fetcher, falling back to
    generic OG scraping. Always returns a Metadata object (never raises).
    """
    if not enrichment_enabled:
        return Metadata()

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().removeprefix("www.")

        if "reddit.com" in domain:
            from .reddit import fetch_reddit
            result = await fetch_reddit(url)
            if result:
                return result

        elif "youtube.com" in domain or "youtu.be" in domain:
            from .youtube import fetch_youtube
            result = await fetch_youtube(url)
            if result:
                return result

        elif "ncbi.nlm.nih.gov" in domain or "pubmed.ncbi.nlm.nih.gov" in domain:
            from .pubmed import fetch_pubmed
            result = await fetch_pubmed(url)
            if result:
                return result

        # Generic OG fallback for everything else
        from .generic import fetch_generic
        result = await fetch_generic(url)
        return result or Metadata()

    except Exception:
        return Metadata()
