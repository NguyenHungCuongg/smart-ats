# Embeddings live in PostgreSQL via pgvector, not a separate vector database

CV Document and Job embeddings are stored in `vector(1536)` columns with HNSW indexes. Rediscovery therefore runs under the same RLS policies as every other query, and no second store has to be kept consistent or isolated per Tenant. We rejected Pinecone because it duplicates tenant isolation outside the database and adds a paid external dependency.

## Consequences

- `text-embedding-3-large` is called with `dimensions=1536`. pgvector's HNSW index supports at most 2,000 dimensions for `vector`, and the model's native 3,072 dimensions exceed that.
- Changing the embedding model means re-embedding the whole Talent Pool. The model name and dimension are stored alongside each vector.
