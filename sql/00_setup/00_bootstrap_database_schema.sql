-- Bootstrap: create database and RAW / ENHANCED / CURATED schemas.
-- Spec: docs/SCHEMA_MIGRATION.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

SET TARGET_DATABASE = 'BLUESKYDATAENGINEERINGPROJECT';

CREATE DATABASE IF NOT EXISTS IDENTIFIER($TARGET_DATABASE);
USE DATABASE IDENTIFIER($TARGET_DATABASE);

CREATE SCHEMA IF NOT EXISTS RAW
    COMMENT = 'Raw ingestion layer — landing tables, stages, pipes, streams';

CREATE SCHEMA IF NOT EXISTS ENHANCED
    COMMENT = 'Enhanced layer — cleaned posts, enriched features, trend joins';

CREATE SCHEMA IF NOT EXISTS CURATED
    COMMENT = 'Curated layer — ML-ready feature table with labels and train/test split';

USE SCHEMA RAW;
