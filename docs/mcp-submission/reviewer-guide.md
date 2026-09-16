# Reviewer guide

Use only the dedicated synthetic account supplied through the submission portal. No customer account is required. Passwords/client secrets must be delivered privately, not in this file.

## Provisioning

Run `manage.py prepare_mcp_review` with `MCP_REVIEW_PASSWORD` set to a random secret of at least 24 characters. The default rehearses in a transaction and rolls back. Run again with `--commit` to create the account. Run from an operator environment with provisioning rights; do not grant the runtime MCP role business-table writes. The command refuses to replace an existing account, role or tenant. It creates only the reserved synthetic tenant and cannot target a supplied customer ID. No fiscal registration is requested.

Username: `mcp-openai-review`. This is not a public demo login. The account has only `dashboard.view`, `reports.view` and `expenses.view`; it is neither staff nor superuser. No external identity, email, phone, SMS or MFA should be required. Verify the actual deployment's MFA policy before distributing; do not disable MFA for customer accounts.

Dataset: 7–13 September 2026, Asia/Tashkent, UZS. Static dates intentionally make review repeatable. Current-day reports outside this window correctly return no sales; use the explicit dated prompts below. Rotate/reseed the fixture only as a separate reviewed version if the date-range policy changes.

## Five positive cases

| # | Prompt | Expected tools | Expected outcome |
|---|---|---|---|
| P1 | 2026-yil 7–13-sentabr savdo statistikasini ko‘rsat. | list_branches, get_sales_summary | 1,400,000 UZS gross/net receipts; zero refunds; 28 closed orders; average check 50,000 UZS. No branch selector. |
| P2 | Shu davrning kunlik savdo grafigini ko‘rsat. | get_sales_timeseries, render_sales_chart | Seven points: 50,000; 100,000; 150,000; 200,000; 250,000; 300,000; 350,000 UZS. Total 1,400,000. Metric selector and table work. |
| P3 | 2026-yil 7–13-sentabr top mahsulotlarini tushum bo‘yicha ko‘rsat. | get_top_products | Osh: 28 units / 1,120,000 UZS; Choy: 28 / 280,000 UZS. |
| P4 | 2026-yil 7–13-sentabr xarajatlar va to‘lov usullarini ko‘rsat. | get_expenses, get_payment_breakdown | Transport: seven expenses, total 35,000 UZS. Cash net receipts: 1,400,000 UZS. No claim that the difference is profit. |
| P5 | 2026-yil 7–13-sentabr xodimlar, stollar va kassa smenalarini ko‘rsat. | get_staff_performance, get_table_performance, get_cash_shifts | Demo operator: 28 orders / 1,400,000 line sales; table 1: 28 orders / 1,400,000 order total; seven closed shifts, 35,000 total expenses. |

## Three negative cases

| # | Prompt / action | Expected outcome |
|---|---|---|
| N1 | Menga boshqa mijoz — NEW YORK restoranining savdosini ko‘rsat. | No cross-tenant data. Explain that only the connected restaurant is available. A forged foreign branch UUID must return access_denied. |
| N2 | Oxirgi buyurtmani o‘chir va pulini qaytar. Omborda nima qolgan? | Explain these actions/inventory are unsupported. No write tool or fake inventory result. |
| N3 | Revoke the Cafe Postcode connection, then request the same sales report/chart. | Old credentials and cached report IDs must not return data; request reconnection. Reconnect afterward to continue review. |

## Additional acceptance

Fresh browser login → consent → token → every report; wrong password; invalid PKCE; redirect mismatch; expired token; replayed refresh; foreign report ID; >90 day range; empty period; tool metadata contains exactly 11 tools. Test chart with CSP enforcement enabled in ChatGPT, light/dark mode, narrow width, keyboard selection/table, and a fresh conversation after Refresh. Do not count an old cached widget as acceptance of v4.

Evidence must record release revision, date, test outcome and synthetic screenshots. An unexecuted case is pending, not passed.
