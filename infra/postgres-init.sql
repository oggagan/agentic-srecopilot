-- Runs once on first Postgres start (against the srecopilot database).
CREATE EXTENSION IF NOT EXISTS vector;
-- Separate database for Langfuse self hosted.
CREATE DATABASE langfuse;
