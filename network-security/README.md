# 🛡️ Network Security Store Tab

This tab provides a centralized dashboard for monitoring and hardening the local network security posture, primarily focused on the **Pi-hole DNS Firewall**.

## 🚀 Features
- **Security Scanner**: Automated analysis of Pi-hole logs and configurations.
- **Findings Manager**: A workflow to review, approve, and track security findings.
- **Hardening Guides**: Step-by-step configuration for network devices.
- **Reports**: Periodically generated security audits.

## 🔄 Approval Workflow
1. **Scan**: The `pihole-security-scan.sh` script identifies issues.
2. **Identify**: High-priority findings are added to `store/network-security/findings/`.
3. **Review**: The user reviews the finding and selects an action:
   - `Approved`: Move to Remediation Plan.
   - `Ignored`: Acknowledge as "Acceptable Risk".
   - `Remediated`: Mark as completed.
4. **Action**: Approved items are added to the prioritized Remediation Plan.

## 📂 Directory Structure
- `/config`: Hardening guides and specific config values.
- `/findings`: Individual findings awaiting review.
- `/reports`: Historical scan results.
- `/scripts`: Scanning and management tools.
