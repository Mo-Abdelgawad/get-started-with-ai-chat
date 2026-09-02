# QARAR document ingestion architecture

## Goal
Keep the system scalable and maintainable by using one generic ingestion pipeline for PDFs, Word, Excel, CSV, and Markdown files, while tagging each document with a standard metadata schema.

## Core principle
Use one shared vector index and filter by metadata instead of creating a separate index for every sector.

## Standard metadata schema
Every ingested document should include these fields:

- document_id
- title
- source_file
- sector
- region
- document_type
- language
- source_owner
- publish_date
- tags
- confidential_level
- page_count
- ingestion_status
- ingestion_timestamp

Recommended sector values:
- healthcare
- education
- finance
- driving_licensing
- energy
- retail
- public_sector

Recommended region values:
- Aleppo
- Damascus
- Latakia
- national
- regional

## Ingestion flow
1. Intake
   - Accept PDFs, Word docs, Excel files, Markdown, CSV, and other text sources.
2. Normalization
   - Convert each file into a consistent text structure.
   - PDF: extract text and page metadata.
   - DOCX: extract paragraphs and tables.
   - XLSX: convert rows to structured text or JSON.
   - Markdown/CSV/TXT: keep as text with preserved sections.
3. Chunking
   - Split content into chunks by section, page, or token size.
   - Keep source metadata attached to each chunk.
4. Embedding and indexing
   - Embed every chunk.
   - Store text plus metadata fields in Azure AI Search.
5. Retrieval
   - Query embeddings with optional filters like sector, region, and document_type.
   - Return grounded answers with source citations.

## Suggested filter pattern
One index with metadata filters is usually enough:

- sector = healthcare
- region = Aleppo
- document_type = pdf

This keeps the system easy to scale without many custom pipelines.

Create separate indexes only when:
- the data has different security requirements,
- different embedding models are needed,
- or strict isolation is required.

## Example metadata record
```json
{
  "document_id": "doc-0001",
  "title": "Driving licensing procedures",
  "source_file": "driver_license_policy.pdf",
  "sector": "driving_licensing",
  "region": "national",
  "document_type": "pdf",
  "language": "ar",
  "source_owner": "Ministry of Transport",
  "publish_date": "2026-01-15",
  "tags": ["driver license", "renewal", "permit rules"],
  "confidential_level": "internal",
  "page_count": 8,
  "ingestion_status": "processed"
}
```

## Implementation guidance
- Keep one generic ingestion pipeline for all document types.
- Specialize only the extraction step per file type.
- Use metadata filters instead of new indexes for most workloads.
- Add validation checks so every document is normalized before indexing.
