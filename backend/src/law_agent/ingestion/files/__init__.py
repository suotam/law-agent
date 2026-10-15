"""Ingestion of arbitrary documents (PDF, DOCX, ...) via docling-serve.

Parsing happens in the container; chunking, identity and payload stay here, so
that docling-serve remains a replaceable parser with no knowledge of RAG.
"""

from law_agent.ingestion.files.chunker import FileChunker
from law_agent.ingestion.files.client import DoclingClient, DoclingError
from law_agent.ingestion.files.models import NAMESPACE, FileChunk

__all__ = ["NAMESPACE", "DoclingClient", "DoclingError", "FileChunk", "FileChunker"]
