import mimetypes
import httpx
from dataclasses import dataclass
from typing import Optional


@dataclass
class KarakeepList:
    id: str
    name: str
    parent_id: Optional[str] = None


@dataclass
class KarakeepBookmark:
    id: str
    title: str
    url: Optional[str] = None


class KarakeepClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._auth = {"Authorization": f"Bearer {api_key}"}
        self._json_headers = {**self._auth, "Content-Type": "application/json"}

    # ── Lists ─────────────────────────────────────────────────────────────────

    async def get_lists(self) -> list:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/api/v1/lists", headers=self._auth)
            r.raise_for_status()
            return [
                KarakeepList(id=lst["id"], name=lst["name"], parent_id=lst.get("parentId"))
                for lst in r.json().get("lists", [])
            ]

    # ── Bookmarks ─────────────────────────────────────────────────────────────

    async def create_link_bookmark(self, url: str) -> KarakeepBookmark:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/api/v1/bookmarks",
                headers=self._json_headers,
                json={"type": "link", "url": url},
            )
            r.raise_for_status()
            data = r.json()
            return KarakeepBookmark(id=data["id"], title=data.get("title", ""), url=data.get("url"))

    async def create_text_bookmark(self, text: str) -> KarakeepBookmark:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/api/v1/bookmarks",
                headers=self._json_headers,
                json={"type": "text", "text": text},
            )
            r.raise_for_status()
            data = r.json()
            return KarakeepBookmark(id=data["id"], title=data.get("title", ""))

    async def create_asset_bookmark(self, asset_id: str, content_type: str = "") -> KarakeepBookmark:
        # Karakeep requires assetType: "image" or "pdf"
        if content_type.startswith("image/"):
            asset_type = "image"
        elif content_type == "application/pdf":
            asset_type = "pdf"
        else:
            asset_type = "image"  # fallback — Karakeep only accepts image|pdf
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/api/v1/bookmarks",
                headers=self._json_headers,
                json={"type": "asset", "assetId": asset_id, "assetType": asset_type},
            )
            r.raise_for_status()
            data = r.json()
            return KarakeepBookmark(id=data["id"], title=data.get("title", ""))

    async def patch_bookmark(
        self,
        bookmark_id: str,
        title: Optional[str] = None,
        note: Optional[str] = None,
    ):
        payload = {}
        if title is not None:
            payload["title"] = title
        if note is not None:
            payload["note"] = note
        if not payload:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.patch(
                f"{self.base_url}/api/v1/bookmarks/{bookmark_id}",
                headers=self._json_headers,
                json=payload,
            )
            r.raise_for_status()

    # ── Assets ────────────────────────────────────────────────────────────────

    async def upload_asset(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload a file, return assetId."""
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self.base_url}/api/v1/assets",
                headers=self._auth,
                files={"file": (filename, file_bytes, content_type)},
            )
            r.raise_for_status()
            return r.json()["assetId"]

    async def attach_banner_image(self, bookmark_id: str, image_url: str):
        """Download image from URL and attach as banner. Best-effort — never raises."""
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                img = await client.get(image_url)
                img.raise_for_status()
                image_bytes = img.content
                content_type = img.headers.get("content-type", "image/jpeg").split(";")[0]

            filename = image_url.split("/")[-1].split("?")[0] or "banner"
            if "." not in filename:
                ext = content_type.split("/")[-1] or "jpg"
                filename = f"banner.{ext}"

            asset_id = await self.upload_asset(image_bytes, filename, content_type)

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.base_url}/api/v1/bookmarks/{bookmark_id}/assets",
                    headers=self._json_headers,
                    json={"assetId": asset_id, "assetType": "bannerImage"},
                )
                r.raise_for_status()
        except Exception:
            pass  # Banner is best-effort; never fail the whole save for it

    # ── Lists / Bookmarks ─────────────────────────────────────────────────────

    async def add_to_list(self, list_id: str, bookmark_id: str):
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.put(
                f"{self.base_url}/api/v1/lists/{list_id}/bookmarks/{bookmark_id}",
                headers=self._auth,
            )
            r.raise_for_status()


async def send_item_to_karakeep(item, user, bot, config) -> str:
    """
    Dispatch a PendingItem to Karakeep. Returns the bookmark ID.
    Raises on failure so callers can surface the error.
    """
    import asyncio
    client = KarakeepClient(config.karakeep_internal_url, user.karakeep_api_key)

    if item.item_type == "link":
        bookmark = await client.create_link_bookmark(item.url)
        if item.title or item.description:
            await client.patch_bookmark(bookmark.id, title=item.title, note=item.description)
        if item.image_url:
            # Fire-and-forget — don't block the response on image upload
            asyncio.create_task(client.attach_banner_image(bookmark.id, item.image_url))

    elif item.item_type == "text":
        text = item.text_content or ""
        bookmark = await client.create_text_bookmark(text)
        if item.title:
            await client.patch_bookmark(bookmark.id, title=item.title)

    elif item.item_type == "asset":
        tg_file = await bot.get_file(item.file_id)
        file_bytes = await tg_file.download_as_bytearray()

        # .md files: Karakeep only accepts image/pdf as asset types.
        # Read content and save as a text bookmark instead (matches web UI drag-drop behaviour).
        if item.file_name and item.file_name.lower().endswith(".md"):
            text_content = bytes(file_bytes).decode("utf-8", errors="replace")
            bookmark = await client.create_text_bookmark(text_content)
            title = item.title or item.file_name
            await client.patch_bookmark(bookmark.id, title=title)
        else:
            ct = "application/octet-stream"
            if item.file_name:
                guessed, _ = mimetypes.guess_type(item.file_name)
                if guessed:
                    ct = guessed
            asset_id = await client.upload_asset(bytes(file_bytes), item.file_name or "file", ct)
            bookmark = await client.create_asset_bookmark(asset_id, ct)
            if item.title or item.description:
                await client.patch_bookmark(bookmark.id, title=item.title, note=item.description)

    else:
        raise ValueError(f"Unknown item_type: {item.item_type}")

    if item.selected_list_id:
        await client.add_to_list(item.selected_list_id, bookmark.id)

    return bookmark.id
