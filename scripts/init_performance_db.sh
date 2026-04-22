#!/bin/bash
#
# Script to initialize the Performance database.
# This creates the required user and database for the Performance Collector and Web Server.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Admin connection settings
DB_HOST="${PERFORMANCE_DB_HOST:-localhost}"
DB_PORT="${PERFORMANCE_DB_PORT:-5432}"
ADMIN_USER="${PERFORMANCE_DB_ADMIN_USER:-postgres}"
ADMIN_PASSWORD="${PERFORMANCE_DB_ADMIN_PASSWORD}"

# New user/database settings
DB_NAME="${PERFORMANCE_DB_NAME:-performance}"
DB_USER="${PERFORMANCE_DB_USER}"
DB_PASSWORD="${PERFORMANCE_DB_PASSWORD}"

# Validate required variables
if [ -z "$ADMIN_PASSWORD" ]; then
    log_error "PERFORMANCE_DB_ADMIN_PASSWORD is required"
    exit 1
fi
if [ -z "$DB_USER" ]; then
    log_error "PERFORMANCE_DB_USER is required"
    exit 1
fi
if [ -z "$DB_PASSWORD" ]; then
    log_error "PERFORMANCE_DB_PASSWORD is required"
    exit 1
fi

log_info "Connecting to PostgreSQL at ${DB_HOST}:${DB_PORT} as ${ADMIN_USER}"

# Export password for psql
export PGPASSWORD="$ADMIN_PASSWORD"

# Function to run SQL command
run_sql() {
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d template1 -tAc "$1"
}

# Check if user exists
user_exists() {
    local result
    result=$(run_sql "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null)
    [ "$result" = "1" ]
}

# Check if database exists
db_exists() {
    local result
    result=$(run_sql "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null)
    [ "$result" = "1" ]
}

# Create user if not exists
if user_exists; then
    log_warn "User '$DB_USER' already exists, skipping creation"
else
    log_info "Creating user '$DB_USER'..."
    run_sql "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD'"
    log_info "User $DB_USER created successfully"
fi

# Create database if not exists
if db_exists; then
    log_warn "Database '$DB_NAME' already exists, skipping creation"
else
    log_info "Creating database '$DB_NAME' with owner '$DB_USER'..."
    run_sql "CREATE DATABASE $DB_NAME OWNER $DB_USER"
    log_info "Database $DB_NAME created successfully"
fi

# Grant privileges
log_info "Granting privileges..."
run_sql "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER"

# Connect to the new database and grant schema privileges
psql -h "$DB_HOST" -p "$DB_PORT" -U "$ADMIN_USER" -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER"

log_info "Database initialization completed successfully!"
log_info ""
log_info "Connection details:"
log_info "  Host:     $DB_HOST"
log_info "  Port:     $DB_PORT"
log_info "  Database: $DB_NAME"
log_info "  User:     $DB_USER"
