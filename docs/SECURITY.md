# SwarmGuard AI — Security Architecture & Threat Mitigations

**Security Framework:** Defense-in-Depth  
**Compliance Standards:** OWASP Top 10, NIST Cybersecurity Framework Alignment

---

## 1. Authentication & Role-Based Access Control (RBAC)

SwarmGuard AI enforces a 4-tier Role-Based Access Control matrix to enforce principle of least privilege across command operations.

### RBAC Privilege Matrix

| Operation / Feature | Admin | Commander | Analyst | Observer |
|:---|:---:|:---:|:---:|:---:|
| View C2 Map & Telemetry | ✅ | ✅ | ✅ | ✅ |
| View Incident Reports | ✅ | ✅ | ✅ | ✅ |
| Export Incident Reports (CSV) | ✅ | ✅ | ✅ | ❌ |
| Update Incident Status | ✅ | ✅ | ✅ | ❌ |
| Issue Tactical Drone Commands | ✅ | ✅ | ❌ | ❌ |
| Configure Geofence Zones | ✅ | ✅ | ❌ | ❌ |
| Manage System Users & Settings | ✅ | ❌ | ❌ | ❌ |
| View System Audit Trail | ✅ | ❌ | ❌ | ❌ |

---

## 2. Threat Mitigation Matrix

| Identified Threat Vector | Risk Level | Applied Defense-in-Depth Control |
|:---|:---:|:---|
| **Rogue Drone Telemetry Spoofing** | HIGH | Device Authentication via `x-drone-api-key` header verification. Invalid keys rejected with `403 Forbidden`. |
| **API Brute-Force Attacks** | HIGH | `slowapi` IP-based rate limiting (`5/minute` on `/auth/login`, `50/second` on `/telemetry/ingest`). |
| **Clickjacking / UI Redirection** | MEDIUM | Nginx `X-Frame-Options: DENY` header. |
| **MIME Sniffing Attacks** | MEDIUM | Nginx `X-Content-Type-Options: nosniff` header. |
| **Unauthorized Action Repudiation** | HIGH | Immutable `AuditLog` database entries recording user, action, target, timestamp, and IP address. |
| **Container Privilege Escalation** | HIGH | Docker non-root execution (`USER appuser`) and read-only container rootfs where applicable. |
| **Database Injection / Corruption** | HIGH | SQLAlchemy ORM parameterized queries eliminating SQL injection vectors. |
