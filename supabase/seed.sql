-- Local development seed. Contains no genetic data: Strata never seeds personal genotypes.
-- Reference data (populations, coordinates) is served from data/derived artefacts, not SQL.
-- Knowledge chunks are loaded by `python -m strata.agent.rag` style tooling when embeddings
-- are configured; nothing to seed here beyond verifying extensions exist.
select extname from pg_extension where extname in ('pgcrypto', 'vector');
