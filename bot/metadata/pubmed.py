import re
import httpx
from typing import Optional
from .fetcher import Metadata

_NCBI_SUMMARY = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=pubmed&id={pmid}&retmode=json"
)
_NCBI_ABSTRACT = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    "?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
)


async def fetch_pubmed(url: str) -> Optional[Metadata]:
    """Fetch PubMed article metadata via NCBI E-utilities (free, no key needed)."""
    pmid_match = re.search(r"/(?:pubmed/)?(\d{4,})", url)
    if not pmid_match:
        return None
    pmid = pmid_match.group(1)

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(_NCBI_SUMMARY.format(pmid=pmid))
            r.raise_for_status()
            data = r.json()

        result = data.get("result", {}).get(pmid, {})
        title = (result.get("title") or "").strip().rstrip(".")

        authors = result.get("authors", [])
        names = [a.get("name", "") for a in authors[:3]]
        if len(authors) > 3:
            names.append("et al.")
        author_str = ", ".join(n for n in names if n)

        journal = result.get("source", "")
        pub_date = result.get("pubdate", "")

        parts = [p for p in [author_str, journal, pub_date] if p]
        description = " · ".join(parts) or None

        # Try to pull the abstract for a richer note
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                ab = await client.get(_NCBI_ABSTRACT.format(pmid=pmid))
                if ab.status_code == 200:
                    text = ab.text.strip()
                    # The plain-text abstract contains the abstract after its label
                    match = re.search(r"Abstract\s*\n+([\s\S]+)", text, re.IGNORECASE)
                    if match:
                        abstract = match.group(1).strip()[:700]
                        description = abstract if abstract else description
        except Exception:
            pass

        return Metadata(title=title or None, description=description, image_url=None, source="pubmed")

    except Exception:
        return None
