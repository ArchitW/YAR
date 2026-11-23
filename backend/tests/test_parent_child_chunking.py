"""Tests for Parent-Child Hierarchical Chunking and Table Markdown Extraction (TKT-019)."""

import pytest
from app.services.chunking import hierarchical_chunk
from app.services.extraction import rows_to_markdown_table, extract_text
from app.services.chat import build_context


class TestTableMarkdownExtraction:
    def test_rows_to_markdown_table_normal(self):
        headers = ["Product", "Price", "Qty"]
        rows = [
            ["Apple", "$1.50", "10"],
            ["Banana", "$0.75", "25"],
        ]
        table = rows_to_markdown_table(headers, rows)
        assert "| Product | Price | Qty |" in table
        assert "| --- | --- | --- |" in table
        assert "| Apple | $1.50 | 10 |" in table
        assert "| Banana | $0.75 | 25 |" in table

    def test_rows_to_markdown_table_empty(self):
        assert rows_to_markdown_table([], []) == ""

    def test_csv_extraction_formats_markdown(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Year,Revenue,Profit\n2024,$10M,$2M\n2025,$15M,$4M\n", encoding="utf-8")
        extracted = extract_text(str(csv_file))
        assert "| Year | Revenue | Profit |" in extracted
        assert "| 2024 | $10M | $2M |" in extracted
        assert "| 2025 | $15M | $4M |" in extracted


class TestHierarchicalChunking:
    def test_empty_or_whitespace_input(self):
        assert hierarchical_chunk("") == []
        assert hierarchical_chunk("   \n\n  ") == []

    def test_markdown_header_hierarchy(self):
        doc = (
            "# Section 1: Overview\n\n"
            "This is the first overview paragraph with some descriptive context.\n\n"
            "## Section 2: Architecture\n\n"
            "This is the architecture paragraph describing system components and connectors in detail.\n\n"
            "# Section 3: Conclusion\n\n"
            "Wrap up thoughts and future directions."
        )
        chunks = hierarchical_chunk(doc, parent_target=50, child_target=10, child_overlap=2)
        assert len(chunks) > 0

        # Verify attributes exist on each item
        for item in chunks:
            assert "child_text" in item
            assert "child_index" in item
            assert "parent_id" in item
            assert "parent_index" in item
            assert "parent_text" in item
            assert item["parent_text"].strip() != ""

        # Verify sections are captured
        section_names = {c.get("section") for c in chunks if c.get("section")}
        assert any("Overview" in s for s in section_names)
        assert any("Architecture" in s for s in section_names)

    def test_plain_text_paragraph_hierarchy(self):
        paras = [
            f"Paragraph {i} contains plenty of meaningful sentences to simulate standard textual body content."
            for i in range(12)
        ]
        doc = "\n\n".join(paras)
        chunks = hierarchical_chunk(doc, parent_target=50, child_target=15, child_overlap=3)
        assert len(chunks) >= 2

        # Check parent IDs grouping
        parent_ids = {c["parent_id"] for c in chunks}
        assert len(parent_ids) > 1


class TestBuildContextHierarchicalDeduplication:
    def test_deduplicates_same_parent_id(self):
        hits = [
            {
                "id": "hit-1",
                "file_name": "report.md",
                "parent_id": "doc_123_parent_0",
                "parent_text": "Full parent section describing fiscal revenue for Q1 through Q4.",
                "text": "fiscal revenue for Q1",
                "section": "Financials",
            },
            {
                "id": "hit-2",
                "file_name": "report.md",
                "parent_id": "doc_123_parent_0",
                "parent_text": "Full parent section describing fiscal revenue for Q1 through Q4.",
                "text": "fiscal revenue for Q4",
                "section": "Financials",
            },
            {
                "id": "hit-3",
                "file_name": "report.md",
                "parent_id": "doc_123_parent_1",
                "parent_text": "Second parent section covering market competition.",
                "text": "market competition",
                "section": "Market",
            },
        ]
        context_str, citations = build_context(hits)

        # There are 3 hits, but hit-1 and hit-2 share parent_id, so only 2 blocks should be created
        assert len(citations) == 2
        assert "[1] report.md (section Financials)\nFull parent section describing fiscal revenue for Q1 through Q4." in context_str
        assert "[2] report.md (section Market)\nSecond parent section covering market competition." in context_str
        assert citations[0]["index"] == 1
        assert citations[1]["index"] == 2

    def test_fallback_for_legacy_hits_without_parent(self):
        hits = [
            {
                "id": "hit-legacy-1",
                "file_name": "notes.txt",
                "text": "Legacy standalone chunk without parent context.",
            },
            {
                "id": "hit-legacy-2",
                "file_name": "notes.txt",
                "text": "Another legacy chunk.",
            },
        ]
        context_str, citations = build_context(hits)
        assert len(citations) == 2
        assert "[1] notes.txt\nLegacy standalone chunk without parent context." in context_str
        assert "[2] notes.txt\nAnother legacy chunk." in context_str
