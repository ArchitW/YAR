"""Tests for Visual PDF Bounding-Box Grounding & Canvas Viewer (TKT-017)."""

import io
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.config import UPLOAD_DIR
from app.models.user import User, Workspace
from app.models.document import Document
from app.services.extraction import extract_pdf_boxes, find_chunk_bbox
from app.services.retrieval import retrieve
from app.services.chat import build_context
from app.main import app

# Minimal 1-page valid PDF stream for testing
MINIMAL_PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 55 >>
stream
BT
/F1 12 Tf
72 700 Td
(Hello PDF World Grounding Test) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000350 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
424
%%EOF"""


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestPdfExtractionGrounding:
    def test_extract_pdf_boxes_synthetic(self, tmp_path):
        pdf_file = tmp_path / "test_grounding.pdf"
        pdf_file.write_bytes(MINIMAL_PDF_BYTES)

        blocks = extract_pdf_boxes(str(pdf_file))
        assert len(blocks) == 1
        block = blocks[0]
        assert block["page"] == 1
        assert block["page_width"] == 612.0
        assert block["page_height"] == 792.0
        assert "Grounding Test" in block["text"]
        assert len(block["bbox"]) == 4
        assert block["bbox"][0] == pytest.approx(72.0, abs=1.0)
        assert block["bbox"][1] == pytest.approx(700.0, abs=1.0)
        assert len(block["runs"]) >= 1

    def test_extract_pdf_boxes_nonexistent(self):
        blocks = extract_pdf_boxes("/nonexistent/file/path.pdf")
        assert blocks == []

    def test_find_chunk_bbox_matching_run(self):
        pdf_blocks = [
            {
                "page": 1,
                "text": "Hello PDF World Grounding Test",
                "bbox": [72.0, 700.0, 270.0, 712.0],
                "page_width": 612.0,
                "page_height": 792.0,
                "runs": [
                    {"text": "Hello PDF", "x0": 72.0, "y0": 700.0, "x1": 130.0, "y1": 712.0},
                    {"text": "Grounding Test", "x0": 135.0, "y0": 700.0, "x1": 270.0, "y1": 712.0},
                ],
            }
        ]
        # Match specific run
        match = find_chunk_bbox("Grounding Test", page_number=1, pdf_blocks=pdf_blocks)
        assert match is not None
        assert match["page"] == 1
        assert match["bbox"][0] == 135.0
        assert match["bbox"][2] == 270.0
        assert match["page_width"] == 612.0

    def test_find_chunk_bbox_fallback_to_block(self):
        pdf_blocks = [
            {
                "page": 2,
                "text": "Executive summary of quarterly earnings",
                "bbox": [50.0, 600.0, 450.0, 620.0],
                "page_width": 612.0,
                "page_height": 792.0,
                "runs": [],
            }
        ]
        match = find_chunk_bbox("quarterly earnings summary", page_number=2, pdf_blocks=pdf_blocks)
        assert match is not None
        assert match["page"] == 2
        assert match["bbox"] == [50.0, 600.0, 450.0, 620.0]

    def test_find_chunk_bbox_empty(self):
        assert find_chunk_bbox("Any text", 1, []) is None
        assert find_chunk_bbox("", 1, [{"page": 1}]) is None


class TestDocumentFileEndpoint:
    def test_get_document_file_success(self, client, db_session):
        ws = Workspace(name="PDF Test WS")
        db_session.add(ws)
        db_session.commit()
        db_session.refresh(ws)

        filename = "test_invoice_view.pdf"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(MINIMAL_PDF_BYTES)

        try:
            doc = Document(
                workspace_id=ws.id,
                name=filename,
                file_type="application/pdf",
                status="indexed",
                size_bytes=len(MINIMAL_PDF_BYTES),
                content="Hello PDF World Grounding Test",
            )
            db_session.add(doc)
            db_session.commit()
            db_session.refresh(doc)

            res = client.get(f"/documents/{doc.id}/file")
            assert res.status_code == 200
            assert "application/pdf" in res.headers.get("content-type", "")
            assert res.content == MINIMAL_PDF_BYTES
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_get_document_file_not_found(self, client):
        res = client.get("/documents/99999/file")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_get_document_file_disk_missing(self, client, db_session):
        ws = Workspace(name="Missing Disk File WS")
        db_session.add(ws)
        db_session.commit()
        db_session.refresh(ws)

        doc = Document(
            workspace_id=ws.id,
            name="missing_from_disk_never_saved.pdf",
            file_type="application/pdf",
            status="indexed",
            size_bytes=100,
            content="Some text",
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        res = client.get(f"/documents/{doc.id}/file")
        assert res.status_code == 404
        assert "not found on disk" in res.json()["detail"].lower()


class TestRetrievalAndContextGrounding:
    def test_build_context_propagates_bbox_to_citation(self):
        hits = [
            {
                "id": "point-1",
                "document_id": 42,
                "file_name": "annual_report.pdf",
                "text": "Revenue surged 45% in Q3 due to cloud adoption.",
                "chunk_index": 0,
                "page_number": 3,
                "section": "Financial Highlights",
                "bbox": [72.0, 500.0, 400.0, 520.0],
                "page_width": 612.0,
                "page_height": 792.0,
            }
        ]
        context, citations = build_context(hits)
        assert len(citations) == 1
        c = citations[0]
        assert c["bbox"] == [72.0, 500.0, 400.0, 520.0]
        assert c["page_width"] == 612.0
        assert c["page_height"] == 792.0
        assert c["page_number"] == 3
        assert "annual_report.pdf" in context
