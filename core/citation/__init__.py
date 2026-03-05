"""Citation and reference lookup module."""

from core.citation.database import (
    get_connection,
    init_db,
    get_paper_by_paper_id,
    get_paper_by_corpus_id,
)
from core.citation.lookup import (
    corpus_id_to_paper_id,
    paper_id_to_corpus_id,
    get_citations,
    get_references,
    count_citations,
    count_references,
)

__all__ = [
    "get_connection",
    "init_db",
    "get_paper_by_paper_id",
    "get_paper_by_corpus_id",
    "corpus_id_to_paper_id",
    "paper_id_to_corpus_id",
    "get_citations",
    "get_references",
    "count_citations",
    "count_references",
]
