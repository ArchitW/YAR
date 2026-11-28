"""Celery background tasks for ingestion, connector syncing, dreaming, and retention (TKT-006)."""

import logging
from typing import Any
from .core.celery_app import celery_app
from .core.database import SessionLocal
from .models.connector import Connector
from .models.document import Document
from .services.audit import AuditService
from .services.connectors.filesystem import FilesystemConnectorService
from .services.connectors.searxng import SearXNGConnectorService
from .services.dreaming.nrem import NREMConsolidator
from .services.dreaming.rem import REMDreamer

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.cleanup_old_audit_logs_task", bind=True)
def cleanup_old_audit_logs_task(self, retention_days: int = 7) -> dict[str, Any]:
    """Background task to purge audit logs older than the retention threshold."""
    db = SessionLocal()
    try:
        pruned = AuditService.prune_retention(db=db, retention_days=retention_days)
        return {"status": "success", "pruned_count": pruned, "retention_days": retention_days}
    except Exception as ex:
        logger.exception("Failed to run cleanup_old_audit_logs_task: %s", ex)
        raise self.retry(exc=ex, countdown=30, max_retries=3)
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_connector_task", bind=True)
def sync_connector_task(self, connector_id: int, workspace_id: int) -> dict[str, Any]:
    """Background task to synchronize a connector's data source."""
    db = SessionLocal()
    try:
        conn = db.get(Connector, connector_id)
        if not conn:
            return {"status": "error", "message": f"Connector {connector_id} not found"}

        if conn.type == "filesystem":
            return FilesystemConnectorService.sync_connector(db, conn)
        elif conn.type == "searxng":
            return SearXNGConnectorService.sync_connector(db, conn)
        return {"status": "error", "message": f"Unsupported connector type {conn.type}"}
    except Exception as ex:
        logger.exception("Failed to run sync_connector_task for %d: %s", connector_id, ex)
        raise self.retry(exc=ex, countdown=60, max_retries=2)
    finally:
        db.close()


@celery_app.task(name="app.tasks.index_document_task", bind=True)
def index_document_task(
    self,
    document_id: int,
    file_path: str,
    content_type: str | None = None,
    index_to_master: bool = False,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Background task to extract, chunk, embed, and index an uploaded document."""
    db = SessionLocal()
    try:
        from .routers.documents import index_document_file

        doc = db.get(Document, document_id)
        if not doc:
            return {"status": "error", "message": f"Document {document_id} not found"}
        total_chunks = index_document_file(
            db=db,
            doc=doc,
            file_path=file_path,
            content_type=content_type,
            index_to_master=index_to_master,
            trace_id=trace_id,
        )
        return {"status": doc.status, "document_id": document_id, "total_chunks": total_chunks}
    except Exception as ex:
        logger.exception("Failed to run index_document_task for %d: %s", document_id, ex)
        raise self.retry(exc=ex, countdown=30, max_retries=2)
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_dream_cycle_task", bind=True)
def run_dream_cycle_task(
    self,
    workspace_id: int,
    run_nrem: bool = True,
    run_rem: bool = True,
    max_dreams: int = 3,
) -> dict[str, Any]:
    """Background task to run NREM pruning and REM associative dreaming."""
    db = SessionLocal()
    try:
        nrem_stats = {}
        rem_stats = {}
        if run_nrem:
            nrem_stats = NREMConsolidator.consolidate(db, workspace_id)
        if run_rem:
            rem_stats = REMDreamer.run_dream_cycle(db, workspace_id, max_dreams=max_dreams)
        db.commit()
        return {
            "status": "success",
            "workspace_id": workspace_id,
            "nrem": nrem_stats,
            "rem": rem_stats,
        }
    except Exception as ex:
        logger.exception("Failed to run dream cycle task for workspace %d: %s", workspace_id, ex)
        raise self.retry(exc=ex, countdown=60, max_retries=2)
    finally:
        db.close()
