#!/bin/bash
# PostgreSQL Performance Tuning for AlgoMirror
# Run as root: sudo bash install/tune-postgres.sh
#
# Key optimization: synchronous_commit=off eliminates ~5-10ms fsync per commit
# Data is still WAL-protected (crash-safe), only last ~600ms of commits could be lost
# on an OS crash - acceptable for a trading journal app where orders are recoverable
# from the broker.

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}PostgreSQL Performance Tuning for AlgoMirror${NC}"
echo "============================================="

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash $0${NC}"
    exit 1
fi

# Detect PostgreSQL version and config file
PG_VERSION=$(psql --version 2>/dev/null | grep -oP '\d+' | head -1)
if [ -z "$PG_VERSION" ]; then
    echo -e "${RED}PostgreSQL not found. Install it first.${NC}"
    exit 1
fi

echo -e "Detected PostgreSQL version: ${GREEN}${PG_VERSION}${NC}"

# Find postgresql.conf
PG_CONF=""
POSSIBLE_PATHS=(
    "/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
    "/var/lib/pgsql/${PG_VERSION}/data/postgresql.conf"
    "/var/lib/postgresql/${PG_VERSION}/main/postgresql.conf"
)

for path in "${POSSIBLE_PATHS[@]}"; do
    if [ -f "$path" ]; then
        PG_CONF="$path"
        break
    fi
done

if [ -z "$PG_CONF" ]; then
    echo -e "${RED}Could not find postgresql.conf. Searched:${NC}"
    for path in "${POSSIBLE_PATHS[@]}"; do
        echo "  - $path"
    done
    echo ""
    echo "Please provide the path manually:"
    read -r PG_CONF
    if [ ! -f "$PG_CONF" ]; then
        echo -e "${RED}File not found: ${PG_CONF}${NC}"
        exit 1
    fi
fi

echo -e "Config file: ${GREEN}${PG_CONF}${NC}"

# Backup current config
BACKUP="${PG_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$PG_CONF" "$BACKUP"
echo -e "Backup saved: ${GREEN}${BACKUP}${NC}"

# Get total system memory in MB
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_MEM_MB=$((TOTAL_MEM_KB / 1024))
echo -e "System memory: ${GREEN}${TOTAL_MEM_MB}MB${NC}"

# Calculate settings based on available memory
# shared_buffers: 25% of RAM (capped at 512MB for small servers)
SHARED_BUFFERS_MB=$((TOTAL_MEM_MB / 4))
if [ "$SHARED_BUFFERS_MB" -gt 512 ]; then
    SHARED_BUFFERS_MB=512
fi
if [ "$SHARED_BUFFERS_MB" -lt 128 ]; then
    SHARED_BUFFERS_MB=128
fi

# effective_cache_size: 50% of RAM
EFFECTIVE_CACHE_MB=$((TOTAL_MEM_MB / 2))

# work_mem: 8MB for single-user app (safe)
WORK_MEM_MB=8

# maintenance_work_mem: 64MB
MAINT_WORK_MEM_MB=64

echo ""
echo "Applying performance settings:"
echo "  shared_buffers = ${SHARED_BUFFERS_MB}MB"
echo "  effective_cache_size = ${EFFECTIVE_CACHE_MB}MB"
echo "  work_mem = ${WORK_MEM_MB}MB"
echo "  maintenance_work_mem = ${MAINT_WORK_MEM_MB}MB"
echo "  synchronous_commit = off"
echo "  random_page_cost = 1.1 (SSD optimized)"
echo ""

# Function to set a PostgreSQL parameter
set_param() {
    local param="$1"
    local value="$2"
    local conf="$3"

    # Remove existing uncommented setting
    sed -i "s/^${param} = .*/#&/" "$conf"
    # Remove existing commented-out setting if we already added one
    sed -i "/^# AlgoMirror tuning: ${param}/d" "$conf"
    sed -i "/^${param} = .*# algomirror-tuned/d" "$conf"

    # Append new setting
    echo "${param} = ${value} # algomirror-tuned" >> "$conf"
}

# Apply settings
set_param "shared_buffers" "${SHARED_BUFFERS_MB}MB" "$PG_CONF"
set_param "effective_cache_size" "${EFFECTIVE_CACHE_MB}MB" "$PG_CONF"
set_param "work_mem" "${WORK_MEM_MB}MB" "$PG_CONF"
set_param "maintenance_work_mem" "${MAINT_WORK_MEM_MB}MB" "$PG_CONF"

# Biggest win: disable synchronous commit (saves ~5-10ms per commit)
# Data is still WAL-protected - only risk is losing last ~600ms of
# commits on an OS crash (NOT a PostgreSQL crash)
set_param "synchronous_commit" "off" "$PG_CONF"

# SSD optimization: reduce random page cost (default is 4.0 for HDDs)
set_param "random_page_cost" "1.1" "$PG_CONF"

# WAL settings for better write performance
set_param "wal_buffers" "16MB" "$PG_CONF"
set_param "checkpoint_completion_target" "0.9" "$PG_CONF"

# Connection settings
set_param "max_connections" "50" "$PG_CONF"

echo -e "${GREEN}Settings applied successfully.${NC}"
echo ""

# Restart PostgreSQL
echo -e "${YELLOW}Restarting PostgreSQL...${NC}"
if systemctl restart postgresql 2>/dev/null; then
    echo -e "${GREEN}PostgreSQL restarted successfully.${NC}"
elif systemctl restart "postgresql-${PG_VERSION}" 2>/dev/null; then
    echo -e "${GREEN}PostgreSQL ${PG_VERSION} restarted successfully.${NC}"
else
    echo -e "${RED}Could not restart PostgreSQL automatically.${NC}"
    echo "Please restart manually: sudo systemctl restart postgresql"
fi

# Verify settings
echo ""
echo -e "${GREEN}Verifying applied settings:${NC}"
sudo -u postgres psql -c "
SELECT name, setting, unit
FROM pg_settings
WHERE name IN (
    'shared_buffers', 'effective_cache_size', 'work_mem',
    'maintenance_work_mem', 'synchronous_commit', 'random_page_cost',
    'wal_buffers', 'checkpoint_completion_target', 'max_connections'
)
ORDER BY name;
" 2>/dev/null || echo "(Run 'sudo -u postgres psql' to verify manually)"

echo ""
echo -e "${GREEN}Done! PostgreSQL is tuned for AlgoMirror.${NC}"
echo -e "Backup config: ${BACKUP}"
