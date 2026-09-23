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
| **Rogue Drone Telemetry Spoofing** | HIGH | Device authentication via the `x-drone-api-key` header: a per-drone key bound to one drone id and organization, stored as a SHA-256 digest and individually revocable; the shared fleet key can be disabled. Invalid keys rejected with `403 Forbidden`, the reason recorded in the audit log. |
| **API Brute-Force Attacks** | HIGH | `slowapi` IP-based rate limiting (`5/minute` on `/auth/login`, `50/second` on `/telemetry/ingest`). |
| **Clickjacking / UI Redirection** | MEDIUM | Nginx `X-Frame-Options: DENY` header. |
| **MIME Sniffing Attacks** | MEDIUM | Nginx `X-Content-Type-Options: nosniff` header. |
| **Unauthorized Action Repudiation** | HIGH | Append-only `AuditLog` entries recording actor, action, target, timestamp and IP. Enforced at the database, not by convention: a `BEFORE UPDATE OR DELETE` trigger (migration `e5f6a7b8c9d0`) rejects any UPDATE outright and permits DELETE only for a retention pass that sets `swarmguard.audit_maintenance` on its session first. |
| **Container Privilege Escalation** | HIGH | Docker non-root execution (`USER appuser`) and read-only container rootfs where applicable. |
| **Database Injection / Corruption** | HIGH | SQLAlchemy ORM parameterized queries eliminating SQL injection vectors. |
