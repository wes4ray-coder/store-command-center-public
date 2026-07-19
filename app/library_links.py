"""
Library links — drop-a-link add & review system (split out of library.py).

Stores submitted links in the library_links table for later review/approval.
Shares the SQLite connection helper with the web archive via library_db.
"""
from typing import Optional

from library_db import _get_db


def add_link(url: str, title: str = "", description: str = "", category: str = "", tags: str = "") -> dict:
    """Submit a new link to the library for review."""
    conn = _get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO library_links (url, title, description, category, tags) VALUES (?, ?, ?, ?, ?)",
        (url, title, description, category, tags)
    )
    conn.commit()
    link_id = c.lastrowid
    conn.close()
    return {"id": link_id, "url": url, "title": title, "status": "pending"}

def list_links(status: str = "pending") -> list:
    """List links by status (pending | approved | rejected | all)."""
    conn = _get_db()
    c = conn.cursor()
    if status == "all":
        c.execute("SELECT * FROM library_links ORDER BY created_at DESC")
    else:
        c.execute("SELECT * FROM library_links WHERE status = ? ORDER BY created_at DESC", (status,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_link(link_id: int) -> Optional[dict]:
    """Get a single link by ID."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM library_links WHERE id = ?", (link_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def review_link(link_id: int, status: str, page_content: str = None, page_path: str = None) -> dict:
    """Approve or reject a link. If approved, optionally save content to library."""
    conn = _get_db()
    c = conn.cursor()
    from datetime import datetime
    reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if page_content is not None:
        c.execute(
            "UPDATE library_links SET status = ?, page_content = ?, page_path = ?, reviewed_at = ? WHERE id = ?",
            (status, page_content, page_path, reviewed_at, link_id)
        )
    else:
        c.execute(
            "UPDATE library_links SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewed_at, link_id)
        )
    conn.commit()
    conn.close()
    return {"id": link_id, "status": status}

def delete_link(link_id: int) -> bool:
    """Delete a link submission."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("DELETE FROM library_links WHERE id = ?", (link_id,))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted

def update_link(link_id: int, title: str = None, description: str = None, category: str = None, tags: str = None) -> dict:
    """Update metadata on a link submission."""
    conn = _get_db()
    c = conn.cursor()
    fields = []
    vals = []
    for col, val in [("title", title), ("description", description), ("category", category), ("tags", tags)]:
        if val is not None:
            fields.append(f"{col} = ?")
            vals.append(val)
    if fields:
        vals.append(link_id)
        c.execute(f"UPDATE library_links SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
    conn.close()
    return {"id": link_id, "updated": True}
