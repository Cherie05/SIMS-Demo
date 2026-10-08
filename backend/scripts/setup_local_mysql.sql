-- One-time setup of an installed MySQL server (8.0 or later) for running SIMS without Docker.
-- Run it as an administrator from the backend folder (works in PowerShell, cmd and bash):
--     mysql -u root -p -e "source scripts/setup_local_mysql.sql"
-- The account matches DATABASE_URL in .env.example; choose another password for anything but a
-- local development machine. Docker users don't need this: docker-compose.yml does the same.

CREATE DATABASE IF NOT EXISTS sims CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- Used only by the automated tests (backend/tests).
CREATE DATABASE IF NOT EXISTS sims_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS sims_migrations CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'sims'@'localhost' IDENTIFIED BY 'sims_password';
GRANT ALL PRIVILEGES ON sims.* TO 'sims'@'localhost';
GRANT ALL PRIVILEGES ON sims_test.* TO 'sims'@'localhost';
GRANT ALL PRIVILEGES ON sims_migrations.* TO 'sims'@'localhost';

-- The migrations create triggers that keep the audit log append-only. With binary logging on
-- (MySQL's default), an account without the SUPER privilege may create triggers only when this
-- is enabled. PERSIST keeps the setting across server restarts.
SET PERSIST log_bin_trust_function_creators = ON;
