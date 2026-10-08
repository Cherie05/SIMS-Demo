-- Runs once, when the MySQL volume is first created.
-- Separate databases for the automated tests (backend/tests): the suite's schema, and a scratch
-- database where the migration test upgrades/downgrades the full migration chain.
CREATE DATABASE IF NOT EXISTS sims_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS sims_migrations CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON sims_test.* TO 'sims'@'%';
GRANT ALL PRIVILEGES ON sims_migrations.* TO 'sims'@'%';
FLUSH PRIVILEGES;
