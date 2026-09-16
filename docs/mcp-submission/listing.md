# Cafe Postcode — submission copy

Status: prepared copy; publisher identity, support and legal URLs deferred by owner. Do not submit while those fields or live reviewer acceptance remain incomplete.

## Listing

Name: Cafe Postcode

Short description: Restaurant sales, products, expenses and cash reports from your Cafe Postcode account.

Long description: Connect your Cafe Postcode restaurant account to ask about sales, view sales charts, find top products, and inspect expenses, staff sales activity, table activity, payment methods and cash shifts. Reports use the restaurants and permissions available to your account. Ask in Uzbek, Russian or English. The connection reads reports; it cannot change orders, issue refunds or manage inventory. An existing Cafe Postcode account with report access is required.

Uzbek description: Shahobcha hisoboti: savdo, mahsulotlar, xarajatlar, xodimlar, stollar va kassa.

Suggested category: Business / Productivity (choose the closest category offered by the portal).

Website: https://cafe-postcode.uz

Logo asset: `../../apps/analytics_mcp/assets/admin-logo.webp` (existing 512 × 512 brand asset). Upload to the listing's logo field; the server icon alone does not update the ChatGPT listing.

MCP URL: https://mcp.cafe-postcode.uz/mcp

Authentication: OAuth 2 authorization code, S256 PKCE, confidential client; scope `analytics:read`. Register the exact redirect URI issued for the submission; do not reuse the development callback blindly. Never paste credentials into this repository.

Widget origin: https://mcp.cafe-postcode.uz (unique to this plugin).

Widget CSP: `connectDomains: []`, `resourceDomains: []`. The chart is self-contained and receives data over the host bridge. No remote fonts, external scripts, embedded frames, direct network requests or external navigation are used. Empty allowlists are intentional; no wildcard should be added just to suppress a UI warning.

## Starter prompts

- Bugungi savdo statistikasini ko‘rsat.
- So‘nggi 7 kunlik savdo grafigini ko‘rsat.
- Bu hafta eng ko‘p sotilgan 5 ta mahsulot qaysi?
- Kechagi xarajatlarni kategoriyalar bo‘yicha ko‘rsat.

## Tool annotation justification

All 11 tools: `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false`, `idempotentHint=true`.

Tools read authorized records from the connected Cafe Postcode account only. They do not mutate business records, contact outside services or publish content. `get_sales_timeseries` creates a short-lived internal chart snapshot; repeated calls can create different report IDs, while leaving business state unchanged. `render_sales_chart` reads the authorized snapshot and provides a view. The remaining tools return aggregates or restaurant scope. There are no inventory tools.

## Data disclosure for the policy author

Returned fields include authorized restaurant names/IDs, date ranges, UZS totals, counts, product names, expense categories, employee display names/IDs for staff reports, table labels and cash-shift IDs. Customer contacts, payment-card numbers, employee contacts, passwords and free-text payment notes are not returned. Identifiers bind scope, drill-down and reports; do not describe all results as anonymous.

OAuth connection and consent records support access control and revocation. Chart snapshots expire after 900 seconds, become inaccessible after expiry/revocation, and are cleaned by an hourly job. Expiry does not imply immediate physical deletion. Operational audit logs contain tool name, user/connection/restaurant IDs, period, outcome and duration; log retention and backup retention need a publisher-approved policy. ChatGPT receives requested tool results and handles them under the user's OpenAI settings/policies. Disconnecting prevents future access but does not erase previous chat messages or the restaurant's source records.

## Release notes

Initial restaurant analytics submission. OAuth-scoped read-only reports, sales chart, domain verification endpoint, deterministic synthetic review fixture and reviewer test cases. Inventory excluded.

## Deferred owner fields

Verified publisher identity, public support contact, final privacy and terms URLs, countries of availability, policy attestations and portal-generated domain verification token. These have deliberately not been fabricated or published.

Official references checked 2026-09-16:

- https://developers.openai.com/plugins/deploy/submission
- https://developers.openai.com/plugins/deploy/app-review
- https://developers.openai.com/plugins/reference
