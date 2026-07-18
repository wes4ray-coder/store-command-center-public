# 🛠️ Pi-hole Hardening Configuration Reference

This document defines the "Gold Standard" configuration for our Pi-hole instance. All manual changes should be aligned with these settings to ensure security, privacy, and performance.

---

## 1. DNS Configuration (`pihole.toml`)

### Upstream DNS
**Recommended:** Use a mix of privacy-focused and reliable providers.
```toml
upstreams = [
  "9.9.9.9",        # Quad9 (Privacy/Malware protection)
  "1.1.1.1",        # Cloudflare (Speed)
  "8.8.8.8"         # Google (Reliability)
]
```

### DNSSEC
**Requirement:** Always enabled to prevent DNS spoofing.
```toml
dnssec = true
```

### Listening Mode
**Requirement:** `LOCAL` (Standard for home networks).
```toml
listeningMode = "LOCAL"
```

### Rate Limiting
**Requirement:** Prevents DNS amplification attacks.
```toml
[dns.rateLimit]
count = 500
interval = 60
```

---

## 2. Blocking & Filtering

### Blocklists
We maintain a diverse set of blocklists via `adlists.list`:
- **OISD-Ads**: High-quality, curated ad list.
- **StevenBlack/Malware**: Protection against known malicious domains.
- **StevenBlack/Phishing**: Protection against credential theft.

### Query Logging
**Requirement:** Enabled for forensic analysis of network traffic.
```toml
queryLogging = true
```

---

## 3. Network & DHCP

### DHCP Server
Pi-hole is configured as the primary DHCP server. 
- **Gateway:** `192.168.1.1`
- **Netmask:** `255.255.255.0`

### Interface Binding
Pi-hole runs in **Host Mode** to ensure proper handling of DHCP broadcasts.

---

## 4. Web Interface & API

### Ports
- **Web Admin:** `8889`
- **API:** `8889`

### Authentication
- **API Pass:** Managed via environment variable `FTLCONF_webserver_api_password`.
- **2FA:** Enabled via `totp_secret` (if required).

---

## 5. Maintenance Tasks

| Task | Frequency | Method |
| :--- | :--- | :--- |
| **Blocklist Update** | Weekly | `pihole -r` (reloadlists) |
| **Security Scan** | Daily | `store/network-security/scripts/pihole-security-scan.sh` |
| **Log Review** | Monthly | Manual review of `pihole.log` |
| **Version Check** | Monthly | `docker exec pihole pihole -v` |
