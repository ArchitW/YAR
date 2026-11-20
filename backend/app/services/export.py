"""ExportService for generating portable chat logs with full citation provenance (TKT-012)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session
from ..models.chat import ChatMessage
from ..models.user import Workspace


class ExportService:
    """Service to export workspace conversations to Markdown, JSON, and Text formats."""

    @staticmethod
    def get_workspace_messages(db: Session, workspace_id: int) -> list[ChatMessage]:
        return (
            db.query(ChatMessage)
            .filter(ChatMessage.workspace_id == workspace_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    @classmethod
    def export_markdown(cls, db: Session, workspace_id: int) -> tuple[str, str]:
        """Generate Markdown export string and standard filename."""
        ws = db.get(Workspace, workspace_id)
        ws_name = ws.name if ws else f"Workspace_{workspace_id}"
        messages = cls.get_workspace_messages(db, workspace_id)

        lines = [
            f"# YAR Knowledge Chat Export: {ws_name}",
            f"*Exported on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
            f"*Workspace ID: {workspace_id} | Total Messages: {len(messages)}*",
            "",
            "---",
            "",
        ]

        for idx, msg in enumerate(messages, 1):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if msg.created_at else "Unknown"
            if msg.role == "user":
                lines.append(f"### 👤 User Query ({ts})")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
            else:
                provider_info = f"({msg.provider} / {msg.model})" if msg.provider or msg.model else ""
                lines.append(f"### 🤖 Assistant Answer {provider_info}")
                lines.append("")
                lines.append(msg.content)
                lines.append("")

                if msg.citations:
                    lines.append("#### Sources & Citations:")
                    for c in msg.citations:
                        c_idx = c.get("index", "?")
                        doc_name = c.get("file_name") or "Document"
                        meta_parts = []
                        if c.get("page_number") is not None:
                            meta_parts.append(f"p.{c['page_number']}")
                        if c.get("section"):
                            meta_parts.append(f"§ {c['section']}")
                        if c.get("chunk_index") is not None:
                            meta_parts.append(f"chunk {c['chunk_index']}")
                        if c.get("score") is not None:
                            score_val = f"{c['score']:.3f}" if isinstance(c["score"], float) else str(c["score"])
                            meta_parts.append(f"score {score_val}")

                        meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
                        lines.append(f"- **[{c_idx}] {doc_name}**{meta_str}")
                        snippet = c.get("text") or c.get("chunk_text")
                        if snippet:
                            quoted_snippet = "\n> ".join(snippet.strip().splitlines())
                            lines.append(f"> {quoted_snippet}")
                    lines.append("")

            lines.append("---")
            lines.append("")

        filename = f"chat-export-ws{workspace_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
        return "\n".join(lines), filename

    @classmethod
    def export_json(cls, db: Session, workspace_id: int) -> tuple[str, str]:
        """Generate structured JSON export string and standard filename."""
        ws = db.get(Workspace, workspace_id)
        ws_name = ws.name if ws else f"Workspace_{workspace_id}"
        messages = cls.get_workspace_messages(db, workspace_id)

        payload = {
            "workspace_id": workspace_id,
            "workspace_name": ws_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_messages": len(messages),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "citations": m.citations or [],
                    "provider": m.provider,
                    "model": m.model,
                    "degraded": m.degraded,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }

        filename = f"chat-export-ws{workspace_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        return json.dumps(payload, indent=2, ensure_ascii=False), filename

    @classmethod
    def export_txt(cls, db: Session, workspace_id: int) -> tuple[str, str]:
        """Generate plain text export string and standard filename."""
        ws = db.get(Workspace, workspace_id)
        ws_name = ws.name if ws else f"Workspace_{workspace_id}"
        messages = cls.get_workspace_messages(db, workspace_id)

        lines = [
            f"=== YAR Knowledge Chat Export: {ws_name} ===",
            f"Exported at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Workspace ID: {workspace_id} | Total Messages: {len(messages)}",
            "=" * 60,
            "",
        ]

        for m in messages:
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else ""
            sender = "USER" if m.role == "user" else "ASSISTANT"
            lines.append(f"[{ts}] {sender}:")
            lines.append(m.content)
            if m.citations:
                lines.append("  [Citations]")
                for c in m.citations:
                    doc = c.get("file_name", "Doc")
                    page = f" p.{c['page_number']}" if c.get("page_number") is not None else ""
                    lines.append(f"  - [{c.get('index', '?')}] {doc}{page}")
            lines.append("-" * 40)
            lines.append("")

        filename = f"chat-export-ws{workspace_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.txt"
        return "\n".join(lines), filename
