# Technical Design Document

## 1. Architecture overview

```
                    ┌─────────────────┐
                    │   File Upload   │
                    │  (POST /ingest) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Format Detector │  extension + OOXML signature check
                    │   (router.py)   │
                    └────────┬────────┘
                             │
          ┌──────┬──────┬───┴───┬──────┬──────┐
          ▼      ▼      ▼       ▼      ▼      ▼
        PDF    DOCX   PPTX    XLSX    CSV    TXT
       (page) (section)(slide)(sheet)(rows)(block)
          │      │      │       │      │      │
          └──────┴──────┴───┬───┴──────┴──────┘
                             │  RawSegment[] (text + location metadata)
                    ┌────────▼────────┐
                    │ Structure-Aware │
                    │     Chunker     │  never splits across a RawSegment
                    │  (chunking.py)  │
                    └────────┬────────┘
                             │  Chunk[] (text + location + chunk_id)
                    ┌────────▼────────┐
                    │  Local Embedder │  intfloat/multilingual-e5-base
                    │ (embeddings.py) │
                    └────────┬────────┘
                             │  Chunk + vector(768)
                    ┌────────▼────────┐
                    │ Postgres+pgvector│
                    │ (vectorstore.py) │
                    └─────────────────┘
                             ▲
                             │  similarity_search(query_vec, top_k)
                    ┌────────┴────────┐
                    │   Query embed   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  POST /query    │
                    └────────┬────────┘
                             │  top-k chunks, labeled [S1]..[Sk]
                    ┌────────▼────────┐
                    │   Groq LLM      │  llama-3.3-70b-versatile
                    │ (rag_pipeline)  │  forced inline citation labels
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Answer + full  │  source list always grounded in
                    │  source list    │  real retrieved metadata, regardless
                    └─────────────────┘  of what the LLM says in free text
```

## 2. Why extraction and chunking are separate layers

Each extractor's only job is to turn a file into a list of `RawSegment` objects — the smallest *structurally meaningful* unit for that format: a PDF page, a DOCX section (paragraphs grouped under a heading), a PPTX slide, an XLSX sheet row-block, a CSV row-block. Extractors know nothing about chunk size limits or embedding models.

The chunker's only job is to take those segments and produce appropriately-sized `Chunk` objects for embedding — but **it never merges text across two different RawSegments**, and it never splits a segment across page/slide/sheet boundaries it doesn't own.

This separation exists because the two concerns have genuinely different failure modes. If extraction logic and chunk-sizing logic are tangled together, a bug in "how big should a chunk be" can corrupt "which page did this text come from" — and citation correctness is the single most heavily weighted requirement here. Keeping them separate means a chunking change can never silently break a citation, because the chunker physically cannot see across a segment boundary.

## 3. Chunking strategy in detail

- **If a segment is short enough** (≤ 1200 characters — `MAX_CHUNK_CHARS`), it becomes one chunk, unmodified. Most slides, table segments, and sheet row-blocks fall here already.
- **If a segment is long** (typical for dense PDF/DOCX pages), it's split on paragraph boundaries and paragraphs are greedily packed into chunks up to the max size, carrying 150 characters of trailing overlap (`CHUNK_OVERLAP_CHARS`) into the next chunk so a sentence at a chunk boundary isn't orphaned from its context.
- **Fragments under 40 characters** (`MIN_CHUNK_CHARS`) are dropped — these are typically stray headers or page-number artifacts with no retrievable value.

**Why not fixed-size sliding-window chunking (the more common default)?** A fixed window would frequently cut a chunk mid-procedure-step in an SOP document (e.g. splitting "Step 3: Check operator certifications..." away from the consequence clause that follows it), and it would need separate logic to track "what page does character offset N belong to," since it doesn't respect any existing boundary. The trade-off is more code and a chunker that has to understand structure (headings, table boundaries) rather than blindly slicing by character count — but for documents where citation precision is the deliverable, that trade-off is worth it.

**Why not semantic chunking (splitting by embedding-similarity shifts between sentences)?** It's the more sophisticated option and would likely produce marginally better topic-coherent chunks. It was not used here because: (a) it requires an extra embedding pass just to find split points, doubling embedding cost at ingestion time; (b) on structured documents like SOPs (which already have explicit headings/steps), the heading structure is a strong, free signal that semantic chunking would mostly just rediscover; (c) it adds a tunable similarity-threshold parameter that's hard to validate without a labeled chunking-quality eval set, which is out of scope here. It's the natural Phase 2 upgrade if structure-aware chunking proves insufficient on real, messier client documents.

## 4. Embedding model choice

**`intfloat/multilingual-e5-base`**, run locally via `sentence-transformers`.

- **Multilingual**: internal SOPs and regulatory documents in this kind of deployment context very plausibly mix Indonesian and English — regulatory or legal language often stays in the original language even when surrounding documentation is in English. An English-only model (e.g. `all-MiniLM-L6-v2`) would degrade badly on that mix; E5's multilingual variant is trained for exactly this.
- **768-dimensional, CPU-friendly**: runs comfortably without a GPU at this corpus scale, which matters for both local demos and cost-sensitive early deployment.
- **No external API dependency for embeddings**: avoids per-document embedding cost and rate limits while iterating on chunking — which is the part of this system most worth iterating on.
- E5 models require a `"query: "` / `"passage: "` text prefix convention from training; this is implemented in `embeddings.py` (`embed_query` vs `embed_passages`) since skipping it measurably hurts E5 retrieval quality specifically.

**Trade-off**: a hosted embedding API (OpenAI `text-embedding-3-large`, Cohere `embed-multilingual-v3`) would likely retrieve marginally better on hard semantic-similarity cases. That quality delta is not the bottleneck in this system — chunking quality and citation correctness are — so the simpler, free, reproducible local option was chosen.

## 5. LLM choice

**Groq, `llama-3.3-70b-versatile`**, temperature 0.1.

- Fast inference (Groq's core value proposition) matters for a Q&A interface where users expect near-instant responses.
- Low temperature (0.1, not 0) keeps answers near-deterministic while leaving a small amount of room for natural phrasing — appropriate for a system whose answers are meant to be trustworthy and reproducible.
- 70B parameter class gives meaningfully better instruction-following for the "cite every claim with a label" constraint than a smaller model would, which matters more here than raw knowledge breadth, since the model is only meant to reason over the provided excerpts.

## 6. Citation strategy — the core design decision

The system does **not** trust the LLM to faithfully report its sources in free text. LLMs paraphrase, conflate, and occasionally hallucinate citations even when explicitly instructed not to.

Instead:
1. Retrieval happens first, against the vector store — by the time the LLM sees anything, every candidate chunk already has **exact, database-verified metadata** (file name, page/slide/sheet/row-range), not LLM-derived metadata.
2. Each chunk is labeled `[S1]`, `[S2]`, ... in the prompt, and the system prompt instructs the model to cite inline using these labels.
3. The API response **always** returns the full, real source list — regardless of which labels the model chose to mention in its answer text. Worst case, the model's inline citations in prose are imperfect, but the structured `sources` field returned to the caller is always grounded in real retrieval results, never in anything the LLM asserts about itself.

This means citation correctness is a property of the *retrieval and metadata pipeline*, not of LLM faithfulness — which is a meaningfully stronger guarantee for a system whose entire value proposition is traceability.

## 7. Database schema and indexing

A single `chunks` table in Postgres, with pgvector's `vector` type for the embedding column. Citation metadata (`source_file`, `location_type`, `location_value`) is stored as **flat columns**, not nested in a JSON blob — this lets metadata-scoped queries (e.g. "search only within file X," exposed via the `source_file` parameter on `/query`) use ordinary indexed SQL predicates instead of JSON path expressions. The one genuinely variable-shape field (`extra` — column headers for tabular data, table flags for DOCX tables) is kept as JSONB, since flattening it would mean a different schema per format.

**Indexing**: HNSW (`vector_cosine_ops`) rather than IVFFlat. IVFFlat requires the index to be built (or rebuilt) after a representative amount of data is already loaded, since it clusters based on existing vectors — awkward for a system that ingests incrementally via `/ingest`. HNSW builds incrementally and is immediately query-ready, at the cost of somewhat higher memory use and slower inserts at very large scale (low millions of vectors) — not a concern at this corpus size.

## 8. Trade-offs and what was deliberately left out

| Decision | Trade-off accepted |
|---|---|
| Local embeddings over hosted API | Slightly lower retrieval quality ceiling, in exchange for zero cost/rate-limit risk during iteration |
| Structure-aware chunking over fixed-window | More extractor/chunker code, in exchange for citations that never span two pages/slides |
| No OCR fallback for scanned/image PDFs | PyMuPDF text extraction only handles born-digital PDFs; a scanned SOP would extract as empty. Acceptable for this corpus (all born-digital); a real deployment serving scanned legacy documents would need a Tesseract/EasyOCR fallback path triggered when `page.get_text()` returns empty for a non-trivial fraction of pages |
| Citation grounded in retrieval metadata, not LLM self-report | Slightly more plumbing (label-matching in the prompt) in exchange for citations that can't be broken by LLM hallucination |
| Local-only deployment via Docker Compose | No public URL to demo without local setup, in exchange for a fully reproducible, dependency-free-of-cloud-uptime demo — see deployment plan below |
| No semantic/embedding-based chunking | Lower chunking sophistication on documents *without* clear heading structure (e.g. unstructured plain TXT notes), in exchange for zero extra embedding cost at ingest time and simpler, more auditable chunk boundaries |

## 9. Deployment plan (not deployed for this submission)

The system runs fully locally via `docker compose up --build` (Postgres+pgvector and the FastAPI app, both containerized). A cloud deployment would look like:

1. **Database**: managed Postgres with the pgvector extension enabled — Neon, Supabase, or a self-managed Postgres on Render/Railway with the extension manually enabled via `CREATE EXTENSION vector;` (already handled idempotently in `vectorstore.init_schema()`).
2. **API**: containerized deploy of the existing Dockerfile to Railway, Render, or Fly.io — no code changes needed, since configuration is already environment-variable driven (`app/config.py`).
3. **Embedding model caching**: the Dockerfile already pre-downloads the embedding model at build time (not at first request), so cold-start latency on a cloud platform would be limited to container boot, not model download.
4. **Observability**: Langfuse tracing is already wired into `rag_pipeline.py` — every `/query` call produces a root span covering the full request, a child span for retrieval (logging which chunks were retrieved and from where), and a generation span for the Groq call (logging the prompt and response). It's enabled automatically when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in `.env`; with no keys set, tracing is a complete no-op and the pipeline behaves identically. For a cloud deployment, point `LANGFUSE_HOST` at the appropriate region (EU/US/self-hosted) and the existing tracing carries over with no code changes.

   **Verification status**: the activation logic was directly verified — with valid Langfuse credentials configured, the tracing flag correctly activates and a real Langfuse client constructs successfully against the configured host. A live end-to-end trace (an actual `/query` call producing a visible trace in the Langfuse dashboard) was not captured in the final testing session due to an unrelated Docker Desktop/WSL2 networking issue on the local development machine, which intermittently blocked the Windows host from reaching the containerized API even though the containers themselves were confirmed healthy and the API was reachable from inside its own container. The integration is in place; the gap is a local-environment networking issue at testing time, not a defect in the tracing logic.
5. **Known risk to plan around**: free-tier managed Postgres services often pause after a period of inactivity, which would need a keep-alive ping (e.g. a scheduled health-check hitting `/health`) if a free tier is used for a long-lived demo URL.

## 10. What I would build next with more time

- OCR fallback for scanned PDFs (Tesseract, triggered on empty-text pages)
- An evaluation harness with a labeled question set + expected source file/location, to measure retrieval precision@k and citation accuracy automatically rather than only via the qualitative example Q&A in the README — Langfuse's dataset/experiment features (already wired in for tracing) would be a natural fit for this
- Hybrid search (BM25 keyword + vector similarity) for queries with exact document-number or form-code lookups (e.g. "QA-FORM-09"), where dense embeddings alone tend to underperform exact-match keyword search
- Re-ranking the top-k retrieved chunks with a cross-encoder before passing to the LLM, to improve precision when top_k is set high to compensate for an imperfect first-pass retrieval
