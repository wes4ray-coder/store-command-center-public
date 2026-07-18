#!/bin/bash

# Pi-hole Security Scanner Script v2
# Audits the Pi-hole instance and generates a structured security report.
# Compatible with Pi-hole v6 API (session-based auth).

set -euo pipefail

# Paths relative to workspace root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="$SCRIPT_DIR/../reports/SECURITY-REPORT.md"
# Config — overridable via env (set by the Store from config.py / .env)
DOCKER_COMPOSE_DIR="${PIHOLE_DOCKER_DIR:-/home/user/Docker/Pihole}"
PIHOLE_CONTAINER="${PIHOLE_CONTAINER:-pihole}"
API_PORT="${PIHOLE_API_PORT:-8889}"
API_PASS="${PIHOLE_API_PASS:-}"   # set PIHOLE_API_PASS in the environment; never hardcode

 mkdir -p "$(dirname "$REPORT_FILE")"

echo "Starting Pi-hole Security Scan..."

# ─────────────────────────────────────────────
# Authenticate with Pi-hole v6 API (session-based)
# ─────────────────────────────────────────────
echo "Authenticating with Pi-hole API..."

AUTH_RESPONSE=$(curl -sf -X POST "http://localhost:${API_PORT}/api/auth" \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"${API_PASS}\"}" 2>/dev/null || echo '{"session":{"valid":false}}')

SID=$(echo "$AUTH_RESPONSE" | jq -r '.session.sid // empty')

if [ -z "$SID" ]; then
    echo "WARNING: Could not authenticate with Pi-hole API. API-dependent checks will be skipped."
    echo "Auth response: $AUTH_RESPONSE"
    API_OK=false
else
    echo "API authentication successful."
    API_OK=true
fi

# Helper: API GET request
api_get() {
    local endpoint="$1"
    if [ "$API_OK" = true ]; then
        curl -sf "http://localhost:${API_PORT}${endpoint}" \
            -H "X-FTL-SID: $SID" 2>/dev/null || echo "null"
    else
        echo "null"
    fi
}

# ─────────────────────────────────────────────
# 1. Configuration Hardening Audit
# ─────────────────────────────────────────────
echo "Checking configuration hardening..."

DNSSEC=$(docker exec "$PIHOLE_CONTAINER" grep -c "dnssec = true" /etc/pihole/pihole.toml 2>/dev/null || echo 0)
RATE_LIMIT=$(docker exec "$PIHOLE_CONTAINER" sed -n '/\[dns.rateLimit\]/,/^\[/p' /etc/pihole/pihole.toml 2>/dev/null | grep 'count =' | grep -oE '[0-9]+' | head -1 || echo "0")
BLOCKING_MODE=$(docker exec "$PIHOLE_CONTAINER" grep "blockingmode =" /etc/pihole/pihole.toml 2>/dev/null | grep -oE '"[A-Z_]+"' | tr -d '"' || echo "NULL")
LISTENING_MODE=$(docker exec "$PIHOLE_CONTAINER" grep "listeningMode =" /etc/pihole/pihole.toml 2>/dev/null | grep -oE '"[A-Z_]+"' | tr -d '"' || echo "LOCAL")
API_ENABLED=$(docker exec "$PIHOLE_CONTAINER" grep -c "api = true" /etc/pihole/pihole.toml 2>/dev/null || echo 0)

# ─────────────────────────────────────────────
# 2. Blocklist Coverage
# ─────────────────────────────────────────────
echo "Checking blocklist coverage..."

ADLISTS_FILE="/home/user/Docker/Pihole/etc-pihole/adlists.list"
LIST_COUNT=0
UNIQUE_LISTS=0
if [ -f "$ADLISTS_FILE" ]; then
    LIST_COUNT=$(grep -c "https://" "$ADLISTS_FILE" 2>/dev/null || echo 0)
    UNIQUE_LISTS=$(grep "https://" "$ADLISTS_FILE" 2>/dev/null | sort -u | wc -l || echo 0)
fi

# Get total blocked domains from API
TOTAL_BLOCKED="unknown"
if [ "$API_OK" = true ]; then
    STATS=$(api_get "/api/stats/summary")
    TOTAL_BLOCKED=$(echo "$STATS" | jq -r '.domains_being_blocked // "unknown"' 2>/dev/null || echo "unknown")
fi

# ─────────────────────────────────────────────
# 3. Query Analysis
# ─────────────────────────────────────────────
echo "Analyzing query patterns..."

TOP_DOMAINS="[]"
TOP_CLIENTS="[]"
TOP_BLOCKED="[]"
SUMMARY="{}"
TOTAL_QUERIES="unknown"
BLOCKED_QUERIES="unknown"
PERCENT_BLOCKED="unknown"

if [ "$API_OK" = true ]; then
    TOP_DOMAINS=$(api_get "/api/stats/top_domains" | jq '.domains // []' 2>/dev/null || echo "[]")
    TOP_CLIENTS=$(api_get "/api/stats/top_clients" | jq '.clients // []' 2>/dev/null || echo "[]")
    TOP_BLOCKED=$(api_get "/api/stats/top_domains?blocked=true" | jq '.domains // []' 2>/dev/null || echo "[]")
    SUMMARY=$(api_get "/api/stats/summary")
    TOTAL_QUERIES=$(echo "$SUMMARY" | jq -r '.queries.total // "unknown"' 2>/dev/null || echo "unknown")
    BLOCKED_QUERIES=$(echo "$SUMMARY" | jq -r '.queries.blocked // "unknown"' 2>/dev/null || echo "unknown")
    if [ "$TOTAL_QUERIES" != "unknown" ] && [ "$TOTAL_QUERIES" -gt 0 ] && [ "$BLOCKED_QUERIES" != "unknown" ]; then
        PERCENT_BLOCKED=$(echo "scale=1; $BLOCKED_QUERIES * 100 / $TOTAL_QUERIES" | bc 2>/dev/null || echo "unknown")
    fi
fi

# ─────────────────────────────────────────────
# 4. Suspicious Traffic Detection
# ─────────────────────────────────────────────
echo "Checking for suspicious traffic patterns..."

SUSPICIOUS_DOMAINS=(
    "telemetry.microsoft.com"
    "google-analytics.com"
    "tracking.facebook.com"
    "adsystem.microsoft.com"
    "doubleclick.net"
    "scorecardresearch.com"
    "adservice.google.com"
    "data.microsoft.com"
    "vortex.data.microsoft.com"
    "settings-win.data.microsoft.com"
)
FOUND_SUSPICIOUS=()
for domain in "${SUSPICIOUS_DOMAINS[@]}"; do
    if docker exec "$PIHOLE_CONTAINER" tail -n 5000 /var/log/pihole/pihole.log 2>/dev/null | grep -q "$domain"; then
        FOUND_SUSPICIOUS+=("$domain")
    fi
done

# Check for excessive queries from single client (potential compromised device)
HIGH_TRAFFIC_CLIENTS="[]"
if [ "$API_OK" = true ]; then
    HIGH_TRAFFIC_CLIENTS=$(echo "$TOP_CLIENTS" | jq '[.[] | select(.count > 5000)]' 2>/dev/null || echo "[]")
fi

# ─────────────────────────────────────────────
# 5. Upstream DNS Diversification Check
# ─────────────────────────────────────────────
echo "Checking upstream DNS configuration..."

UPSTREAMS=$(docker exec "$PIHOLE_CONTAINER" grep -A20 "upstreams = \[" /etc/pihole/pihole.toml 2>/dev/null | grep -E '^\s+"' | sed 's/^[[:space:]]*"//; s/"[,[:space:]]*$//' | head -20 || echo "")
UPSTREAM_COUNT=$(echo "$UPSTREAMS" | grep -c . 2>/dev/null || echo 0)

# ─────────────────────────────────────────────
# Generate Report
# ─────────────────────────────────────────────
echo "Generating security report..."

cat > "$REPORT_FILE" << REPORT_EOF
# Pi-hole Security Report

**Generated:** $(date)
**Pi-hole Version:** $(docker exec "$PIHOLE_CONTAINER" pihole -v 2>/dev/null | tr '\n' ' | ' || echo "unknown")
**Scanner:** v2 (v6 API compatible)

---

## 1. Configuration Audit

### DNSSEC
$([ "$DNSSEC" -gt 0 ] && echo "- [x] DNSSEC is **enabled** ✅" || echo "- [ ] DNSSEC is **disabled** ❌ — Recommendation: Enable in pihole.toml under [dns] section")

### Rate Limiting
$([ -n "$RATE_LIMIT" ] && [ "$RATE_LIMIT" -gt 0 ] && echo "- [x] Rate limiting **enabled** (Count: $RATE_LIMIT per 60s) ✅" || echo "- [ ] Rate limiting **not configured** ❌")

### Blocking Mode
- Mode: **$BLOCKING_MODE** $([ "$BLOCKING_MODE" = "NULL" ] && echo "✅ (recommended)" || echo "⚠️ (NULL is recommended)")

### DNS Listening Mode
- Mode: **$LISTENING_MODE** $([ "$LISTENING_MODE" = "LOCAL" ] && echo "✅ (recommended for host network)" || echo "⚠️")

### API Status
$([ "$API_ENABLED" -gt 0 ] && echo "- [x] API is **enabled** ✅" || echo "- [ ] API is **disabled** ❌")
$([ "$API_OK" = true ] && echo "- [x] API authentication **working** ✅" || echo "- [ ] API authentication **failed** ❌")

---

## 2. Blocklist Coverage

- **Total blocklist entries:** $LIST_COUNT
- **Unique blocklists:** $UNIQUE_LISTS
$([ "$LIST_COUNT" != "$UNIQUE_LISTS" ] && echo "- ⚠️ **Duplicate entries detected** — $((LIST_COUNT - UNIQUE_LISTS)) duplicates found, should be cleaned up" || echo "- No duplicate entries ✅")
- **Total domains blocked:** $TOTAL_BLOCKED

### Current Blocklists:
$(grep "https://" "$ADLISTS_FILE" 2>/dev/null | sort -u || echo "No blocklists configured")

$([ "$UNIQUE_LISTS" -lt 3 ] && echo "### ⚠️ Recommendation: Add more blocklists\nOnly $UNIQUE_LISTS unique blocklists. Consider adding:\n- OISD blocklists (ads, NSFW)\n- HaGeZi blocklists (threats, trackers)\n- AdGuard DNS filter list" || echo "### Blocklist diversity: Good ✅")

---

## 3. Query Analysis (24h)

- **Total queries:** $TOTAL_QUERIES
- **Blocked queries:** $BLOCKED_QUERIES
- **Block rate:** ${PERCENT_BLOCKED}%

### Top Domains
$(echo "$TOP_DOMAINS" | jq -r '.[:10] | .[] | "- \(.domain): \(.count) queries"' 2>/dev/null || echo "API data unavailable")

### Top Clients
$(echo "$TOP_CLIENTS" | jq -r '.[:10] | .[] | "- \(.name // .ip): \(.count) queries"' 2>/dev/null || echo "API data unavailable")

### Top Blocked Domains
$(echo "$TOP_BLOCKED" | jq -r '.[:10] | .[] | "- \(.domain): \(.count) blocks"' 2>/dev/null || echo "API data unavailable")

---

## 4. Suspicious Traffic Detection

$([ ${#FOUND_SUSPICIOUS[@]} -eq 0 ] && echo "### ✅ No common telemetry/tracking domains found in recent logs." || echo "### ⚠️ Suspicious domains detected:")

$(for d in "${FOUND_SUSPICIOUS[@]}"; do echo "- [!] $d"; done)

### High-Traffic Clients (>5000 queries)
$(if [ "$HIGH_TRAFFIC_CLIENTS" = "[]" ] || [ -z "$HIGH_TRAFFIC_CLIENTS" ]; then
    echo "No clients with excessive query volume ✅"
else
    echo "$HIGH_TRAFFIC_CLIENTS" | jq -r '.[] | "- \(.name // .ip): \(.count) queries"' 2>/dev/null || echo "Analysis unavailable"
fi)

---

## 5. Upstream DNS Configuration

- **Total upstreams:** $UPSTREAM_COUNT
$([ "$UPSTREAM_COUNT" -gt 5 ] && echo "- ⚠️ **Too many upstreams** — $UPSTREAM_COUNT configured. Recommend 2-3 for reliability without overloading." || echo "- Upstream count is reasonable ✅")

### Configured Upstreams:
$(echo "$UPSTREAMS" | sed 's/^/- /' || echo "No upstreams configured")

---

## 6. Summary & Verdict

$([ ${#FOUND_SUSPICIOUS[@]} -eq 0 ] && [ "$DNSSEC" -gt 0 ] && [ "$API_OK" = true ] && [ "$UNIQUE_LISTS" -ge 3 ] && echo "### Verdict: ✅ **HEALTHY**" || echo "### Verdict: ⚠️ **NEEDS ATTENTION**")

**Issues found:**
$([ "$DNSSEC" -eq 0 ] && echo "- DNSSEC is disabled")
$([ ${#FOUND_SUSPICIOUS[@]} -gt 0 ] && echo "- Suspicious telemetry domains detected: ${FOUND_SUSPICIOUS[*]}")
$([ "$API_OK" = false ] && echo "- API authentication failed or API disabled")
$([ "$UNIQUE_LISTS" -lt 3 ] && echo "- Insufficient blocklist diversity ($UNIQUE_LISTS unique lists, recommend 3+)")
$([ "$LIST_COUNT" != "$UNIQUE_LISTS" ] && echo "- Duplicate blocklist entries ($((LIST_COUNT - UNIQUE_LISTS)) duplicates)")
$([ "$UPSTREAM_COUNT" -gt 5 ] && echo "- Excessive upstream DNS servers ($UPSTREAM_COUNT, recommend 2-3)")

---

## 7. Remediation Plan

| Priority | Issue | Action |
|----------|-------|--------|
$([ "$DNSSEC" -eq 0 ] && echo "| High | DNSSEC disabled | Enable DNSSEC in pihole.toml: set dnssec = true under [dns] section |")
$([ "$UNIQUE_LISTS" -lt 3 ] && echo "| High | Insufficient blocklists | Add OISD, HaGeZi, and AdGuard blocklists via adlists.list |")
$([ "$LIST_COUNT" != "$UNIQUE_LISTS" ] && echo "| Low | Duplicate blocklist entries | Remove duplicates from adlists.list |")
$([ "$UPSTREAM_COUNT" -gt 5 ] && echo "| Medium | Too many upstreams | Reduce to 2-3 providers (e.g., 1.1.1.1, 8.8.8.8, 9.9.9.9) |")
$([ "$API_OK" = false ] && echo "| Medium | API not accessible | Verify api = true in pihole.toml and restart container |")
$([ ${#FOUND_SUSPICIOUS[@]} -gt 0 ] && echo "| Medium | Telemetry traffic detected | Add telemetry-specific blocklists, check client devices |")
$([ "$BLOCKING_MODE" != "NULL" ] && echo "| Low | Suboptimal blocking mode | Set blockingmode = \"NULL\" in pihole.toml |")

---

*Report generated by pihole-security-scan.sh v2*
REPORT_EOF

echo ""
echo "============================================"
echo "Security scan complete!"
echo "Report saved to: $REPORT_FILE"
echo "============================================"

# Logout from API session
if [ "$API_OK" = true ]; then
    curl -sf -X DELETE "http://localhost:${API_PORT}/api/auth" \
        -H "X-FTL-SID: $SID" > /dev/null 2>&1 || true
    echo "API session closed."
fi
