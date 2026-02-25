#!/bin/bash

# ============================================
# AlgoMirror PostgreSQL Installation Script
# Installs PostgreSQL 17 and creates the
# algomirror database and user
# ============================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════╗"
echo "║     AlgoMirror - PostgreSQL Setup                     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Logging
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}"
}

# ============================================
# ROOT CHECK
# ============================================
if [ "$EUID" -ne 0 ]; then
    log_message "Please run as root (sudo bash install-postgres.sh)" "$RED"
    exit 1
fi

# ============================================
# DETECT EXISTING POSTGRESQL
# ============================================
PG_ALREADY_INSTALLED=false

if command -v psql &>/dev/null; then
    PG_VERSION=$(psql --version 2>/dev/null | grep -oP '\d+' | head -1)
    log_message "PostgreSQL detected: version $PG_VERSION" "$YELLOW"
    PG_ALREADY_INSTALLED=true

    if [ "$PG_VERSION" -ge 17 ]; then
        log_message "PostgreSQL 17+ already installed. Skipping installation." "$GREEN"
    else
        log_message "PostgreSQL $PG_VERSION found. Will install PostgreSQL 17 alongside." "$YELLOW"
        PG_ALREADY_INSTALLED=false
    fi
fi

# ============================================
# INSTALL POSTGRESQL 17
# ============================================
if [ "$PG_ALREADY_INSTALLED" = false ]; then
    log_message "\nInstalling PostgreSQL 17 from official repository..." "$BLUE"

    # Install prerequisites
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates gnupg lsb-release >/dev/null 2>&1

    # Add official PostgreSQL APT repository
    # Remove any stale key/list first
    rm -f /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
    rm -f /etc/apt/sources.list.d/pgdg.list
    install -d /usr/share/postgresql-common/pgdg

    # Download and dearmor the GPG key (force overwrite)
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/pgdg.asc
    gpg --batch --yes --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc /tmp/pgdg.asc
    rm -f /tmp/pgdg.asc

    # If gpg --dearmor fails, try direct download of binary key
    if [ ! -s /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc ]; then
        log_message "GPG dearmor failed, trying direct key import..." "$YELLOW"
        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | \
            tee /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc > /dev/null
    fi

    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

    # Install PostgreSQL 17
    apt-get update
    apt-get install -y postgresql-17 postgresql-client-17
    if [ $? -ne 0 ]; then
        log_message "Failed to install PostgreSQL 17" "$RED"
        exit 1
    fi

    # Enable and start
    systemctl enable postgresql
    systemctl start postgresql

    log_message "PostgreSQL 17 installed successfully" "$GREEN"
fi

# Verify PostgreSQL is running
if ! systemctl is-active --quiet postgresql; then
    log_message "Starting PostgreSQL..." "$YELLOW"
    systemctl start postgresql
fi

log_message "PostgreSQL is running" "$GREEN"

# ============================================
# GENERATE SECURE PASSWORD
# ============================================
DB_USER="algomirror"
DB_NAME="algomirror"
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

# ============================================
# CREATE DATABASE USER (idempotent)
# ============================================
log_message "\nConfiguring database user..." "$BLUE"

USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null)
if [ "$USER_EXISTS" = "1" ]; then
    log_message "User '$DB_USER' already exists. Updating password..." "$YELLOW"
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null 2>&1
else
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        log_message "Failed to create user '$DB_USER'" "$RED"
        exit 1
    fi
    log_message "Created user '$DB_USER'" "$GREEN"
fi

# ============================================
# CREATE DATABASE (idempotent)
# ============================================
log_message "Configuring database..." "$BLUE"

DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null)
if [ "$DB_EXISTS" = "1" ]; then
    log_message "Database '$DB_NAME' already exists" "$YELLOW"
else
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        log_message "Failed to create database '$DB_NAME'" "$RED"
        exit 1
    fi
    log_message "Created database '$DB_NAME'" "$GREEN"
fi

# Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >/dev/null 2>&1
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;" >/dev/null 2>&1

# ============================================
# CONFIGURE pg_hba.conf
# ============================================
log_message "\nConfiguring authentication..." "$BLUE"

PG_HBA=$(sudo -u postgres psql -tAc "SHOW hba_file" 2>/dev/null | tr -d ' ')

if [ -f "$PG_HBA" ]; then
    # Check if algomirror entry already exists
    if grep -q "algomirror" "$PG_HBA"; then
        log_message "pg_hba.conf already configured for algomirror" "$YELLOW"
    else
        # Add entries before the default "local all all" line
        # Create a temp file with the new entries
        TEMP_HBA=$(mktemp)
        cat > "$TEMP_HBA" << 'HBAEOF'
# AlgoMirror database access
local   algomirror   algomirror                              md5
host    algomirror   algomirror   127.0.0.1/32              md5
host    algomirror   algomirror   ::1/128                   md5
HBAEOF

        # Insert before the first uncommented "local" line
        sed -i "/^local.*all.*all/i\\
# AlgoMirror database access\\
local   algomirror   algomirror                              md5\\
host    algomirror   algomirror   127.0.0.1/32              md5\\
host    algomirror   algomirror   ::1/128                   md5" "$PG_HBA"

        rm -f "$TEMP_HBA"

        # Reload PostgreSQL to apply changes
        systemctl reload postgresql
        log_message "pg_hba.conf configured for algomirror" "$GREEN"
    fi
else
    log_message "Warning: Could not find pg_hba.conf at $PG_HBA" "$YELLOW"
    log_message "You may need to manually add authentication rules" "$YELLOW"
fi

# ============================================
# VERIFY CONNECTIVITY
# ============================================
log_message "\nVerifying database connectivity..." "$BLUE"

PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" -d "$DB_NAME" -h 127.0.0.1 -c "SELECT 'AlgoMirror PostgreSQL connection OK' AS status;" >/dev/null 2>&1
if [ $? -eq 0 ]; then
    log_message "Database connectivity verified" "$GREEN"
else
    log_message "Warning: Could not connect via TCP. Trying local socket..." "$YELLOW"
    PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        log_message "Database connectivity verified (local socket)" "$GREEN"
    else
        log_message "Could not verify database connectivity" "$RED"
        log_message "You may need to reload PostgreSQL: systemctl reload postgresql" "$YELLOW"
    fi
fi

# ============================================
# BUILD DATABASE_URL
# ============================================
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"

# Save for migration script
echo "$DATABASE_URL" > /tmp/algomirror_pg_url.tmp
chmod 600 /tmp/algomirror_pg_url.tmp

# ============================================
# SUMMARY
# ============================================
echo ""
log_message "============================================" "$GREEN"
log_message "  PostgreSQL Setup Complete" "$GREEN"
log_message "============================================" "$GREEN"
echo ""
log_message "Database User:  $DB_USER" "$NC"
log_message "Database Name:  $DB_NAME" "$NC"
log_message "Password:       $DB_PASSWORD" "$NC"
echo ""
log_message "Add this to your .env file:" "$YELLOW"
echo ""
echo "  DATABASE_URL=$DATABASE_URL"
echo ""
log_message "Or run the migration script to do it automatically:" "$YELLOW"
echo "  sudo bash install/migrate-to-postgres.sh"
echo ""
log_message "The DATABASE_URL has been saved to /tmp/algomirror_pg_url.tmp" "$NC"
log_message "for the migration script to use." "$NC"
log_message "============================================" "$GREEN"
