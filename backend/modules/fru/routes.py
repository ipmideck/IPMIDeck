"""FRU (Field Replaceable Unit) routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.core.i18n import get_lang, t
from backend.modules import get_ctx

router = APIRouter()


@router.get("/{server_id}")
async def get_fru(server_id: str):
    """Get cached FRU data for a server."""
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)

    rows = await ctx.db.fetchall(
        "SELECT section, field, value, fetched_at FROM fru_cache WHERE server_id = ? ORDER BY section, field",
        (server_id,),
    )

    if not rows:
        # Auto-fetch if no cache exists
        result = await refresh_fru(server_id)
        if not result.get("success", False):
            return result
        rows = await ctx.db.fetchall(
            "SELECT section, field, value, fetched_at FROM fru_cache WHERE server_id = ? ORDER BY section, field",
            (server_id,),
        )

    # Group by section
    sections: dict[str, list[dict]] = {}
    fetched_at = None
    for row in rows:
        section = row["section"]
        if section not in sections:
            sections[section] = []
        sections[section].append({"field": row["field"], "value": row["value"]})
        fetched_at = row["fetched_at"]

    return {"server_id": server_id, "sections": sections, "fetched_at": fetched_at}


@router.post("/{server_id}/refresh")
async def refresh_fru(server_id: str, lang: str = Depends(get_lang)):
    """Fetch FRU data from BMC and update cache."""
    from backend.core.crypto import decrypt
    from backend.main import auth  # AuthManager not in ModuleContext — kept (Decision J)

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    try:
        entries = await ctx.ipmi.get_fru(
            server["host"], decrypt(server["username_enc"], key), decrypt(server["password_enc"], key)
        )

        # Clear old cache
        await ctx.db.execute("DELETE FROM fru_cache WHERE server_id = ?", (server_id,))

        # Insert new data
        for entry in entries:
            await ctx.db.execute(
                "INSERT INTO fru_cache (server_id, section, field, value) VALUES (?, ?, ?, ?)",
                (server_id, entry["section"], entry["field"], entry["value"]),
            )
        await ctx.db.commit()

        return {"success": True, "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e)}
