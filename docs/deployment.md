# Deployment

## Now: local only (R0)

Everything runs on the owner's computer inside WSL2: the application (`uv run …`), PostgreSQL in Docker Compose, and tests. CI runs on GitHub Actions within the free allowance. Pilot users in P9 see demos or run the project themselves.

## What production will need (decided at the Phase 9 gate)

| Need | Typical options | Introduces cost? |
| --- | --- | --- |
| Hosting the container | A container platform or a small virtual server | Yes (monthly) |
| Managed PostgreSQL with backups | Provider-managed database, or self-managed with tested backups | Yes |
| Source document storage | Object storage | Yes (small) |
| Domain name and TLS | Registrar; TLS is usually free | Yes (yearly, small) |
| Email for account and alert messages | Transactional email service | Possibly |
| Monitoring and error tracking | Free tiers exist; check limits | Possibly |
| Payments | Paystack or similar (fees per transaction) | Yes (per transaction) |
| Legal and registrations | Attorney, information officer registration | Yes (once-off) |

Prices are not recorded here because they change. They are researched with current quotes for the Phase 9 decision. **Nothing here may be bought or signed up for without the owner's approval.**

## Production principles (for later)

- Same container image in every environment; configuration by environment variables.
- Migrations run as a separate step with a separate database role.
- Backups are only real once a restore has been tested.
- Hosting in South Africa is preferred, or POPIA s72 cross-border rules apply.
