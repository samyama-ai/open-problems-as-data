#!/usr/bin/env bash
# V3 run on database systems: dbms-research-kg's catalog is the problem layer (issue #2).
# Build the catalog export first: scripts/catalog_from_dbms_kg.py (needs a dbms-research-kg
# checkout with build/source_catalog.json). Researchers are seeded from the catalog's authors.
cd "$(dirname "$0")/.."
# SNAPSHOT_S3_PREFIX is optional and unset by default: the .sgsnap is written under runs/.
# ENV_FILE holds ANTHROPIC_API_KEY and OPENALEX_API_KEY; see the README.
exec uv run research-kit run --preset cs \
  --domain "database systems research: relational theory, query optimization and processing, transactions and concurrency, recovery, storage and indexing, distributed and NewSQL databases, replication and consensus, streaming, data integration and cleaning, provenance, temporal, spatial and graph databases, privacy and encrypted databases, learned database components, vector similarity search, hardware-conscious and cloud databases, benchmarking, and autonomous databases" \
  --catalog catalogs/dbms --catalog-seed 40 --catalog-since 2018 \
  --ground-domain cs \
  --max-seed-works 100 --recent-seed-works 20 --refs-top 400 \
  --citing-seed-papers 4 --citing-per-paper 5 --ideas 60 -j 12 --batch \
  ${SNAPSHOT_S3_PREFIX:+--s3-prefix "$SNAPSHOT_S3_PREFIX"} \
  --graph-version 1.11.0 --out runs/dbms --backend api --env-file "${ENV_FILE:-.env}" \
  --mailto "${OPENALEX_MAILTO:?set OPENALEX_MAILTO to your email, as OpenAlex asks}" --keep-running --port 18088 "$@"
