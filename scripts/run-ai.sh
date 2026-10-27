#!/usr/bin/env bash
# V3 run on AI/ML research: ai-research-kg's catalog is the problem layer (as run-dbms.sh).
# Build the catalog export first: scripts/catalog_from_ai_kg.py (needs an ai-research-kg
# checkout with data/graph.json from `python -m etl.build`). Researchers are seeded from the
# catalog's authors. --catalog-since 2020, not DBMS's 2018: most of the 4,932 cited papers are later.
cd "$(dirname "$0")/.."
# SNAPSHOT_S3_PREFIX is optional and unset by default: the .sgsnap is written under runs/.
# ENV_FILE holds ANTHROPIC_API_KEY and OPENALEX_API_KEY; see the README.
exec uv run research-kit run --preset cs \
  --domain "AI and machine learning research on large models: tokenization, attention, training dynamics and optimization, alignment and preference learning, retrieval and agentic systems, data curation, embeddings, architecture, scaling laws, inference and serving, quantization and compression, parameter-efficient adaptation, long context, mixture of experts, state-space models, reasoning and inference-time compute, reinforcement learning for LLMs, evaluation, interpretability, hallucination and factuality, safety and robustness, privacy and memorization, multimodal, speech, code generation, multilingual models, knowledge editing, distillation, synthetic data, distributed training, hardware and kernels, uncertainty and calibration, diffusion and generative modeling, and world models and planning" \
  --catalog catalogs/ai --catalog-seed 40 --catalog-since 2020 \
  --ground-domain cs \
  --max-seed-works 100 --recent-seed-works 20 --refs-top 400 \
  --citing-seed-papers 4 --citing-per-paper 5 --ideas 60 -j 12 --batch \
  ${SNAPSHOT_S3_PREFIX:+--s3-prefix "$SNAPSHOT_S3_PREFIX"} \
  --graph-version 1.11.0 --out runs/ai --backend api --env-file "${ENV_FILE:-.env}" \
  --mailto "${OPENALEX_MAILTO:?set OPENALEX_MAILTO to your email, as OpenAlex asks}" --keep-running --port 18089 "$@"
