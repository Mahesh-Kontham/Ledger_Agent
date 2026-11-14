# DECISIONS.md — ambiguities resolved during the build

1. **Extra `settings` table.** PRD §15 requires the mode in "a settings row", but §7 has no settings table. Added `settings(key, value)`; all §7 tables are created exactly as specified.
2. **Extra modules.** `core/pipeline.py` holds `process_bill` + review actions; `core/ui.py` holds the shared sidebar and bill card. No new features, just placement.
3. **Phase 4 "Done when" vs. the rules.** With Transport = ₹150 the Rapido expense line is ₹125 (the ₹5 card fee goes to `Expense:Bank Charges`), so spent = 83% → **BUDGET_WARNING**, not BREACH. Rules kept exact. Use a ₹100 limit to demo BREACH (`tests/test_budgets.py` covers both).
4. **Budget checks also run when budgets are saved** in Settings (as well as after every posting), so setting a limit after bills are posted still raises the alert. The usual per-period dedupe still applies.
5. **Books per mode.** Bills keep the mode they were created in. Ledger views default to the current mode's books, with an "All modes" switch. Budget `spent` counts only that mode's bills. Re-verification uses the bill's stored mode.
6. **Duplicate originals.** Rows with status REJECTED or DUPLICATE are never treated as the "original", so `duplicate_of` always points to the first real bill. A bill never matches itself when it is re-verified.
7. **Duplicates skip cross-verification**, so they never consume or misreport a bank transaction. Fraud is still scored, for the audit trail.
8. **Merchant alias for matching.** "Prefer candidates whose description contains the bill's merchant alias": uses the matched alias, else the lowercased normalized name.
9. **Ties** in smallest |variance| are broken by the lowest transaction id.
10. **MATCHED with a non-zero variance within tolerance** (e.g. ₹1): the difference posts to `Expense:Bank Charges` (debit if positive, credit if negative) with the note "Difference within tolerance". Without this the entry could not balance.
11. **Approved VARIANCE_UNEXPLAINED bills** post as unmatched (credit side follows payment_mode, amount = invoice). The transaction is NOT linked and the reason "Posted without bank match" is added. The same happens if the candidate transaction was matched by another bill before approval.
12. **Unknown currency** (not in the sample FX table): `total_amount_inr` stays null and the bill goes to MISSING_DATA with "Missing: fx_rate (...)". No rate is invented.
13. **Format validation in extraction:** a non-ISO date, non-numeric amount, non-ISO currency or out-of-enum payment_mode becomes null and is listed in `low_confidence_fields`. It is never repaired.
14. **API/auth errors** go straight to "Extraction failed" (no retry). The single retry is reserved for JSON parse failures, as specified.
15. **entry_id** = `JE-<bill id, 6 digits>`, matching the PRD example (bill #2 → JE-000002).
16. **Manual entries** get fraud score 0 with "Manual entry - no document". Duplicate rule 1 (hash) is skipped because there is no file.
17. **Info notes and match details** are stored in `status_reasons_json` (prefixed "Note:") because §7 has no separate column. They never change the status.
18. **Bank CSV import** skips rows identical to existing ones (same date/description/amount/currency/type/account), so "Load sample bank statement" can be clicked twice safely. Rows in a currency outside the FX table are rejected.
19. **MCP fraud checker:** sends a JSON-RPC `tools/call` for tool `score_receipt` with the base64 file and expects `{score, signals}`. It is not verified against a real server (PRD §17). Any failure falls back to the mock and adds "MCP unavailable - mock used".
20. **Mock EXIF check** also reads the PNG text chunk `Software`, besides EXIF tag 0x0131.
21. **Gmail IMAP** reads up to the 20 most recent UNSEEN messages in INBOX.
22. **ANOMALY dedupe** is on (bill_id, message). Budget alert dedupe is on (type, category, period_key), as specified.
23. **LLM provider changed to Google Gemini** (team decision, overrides PRD §3's Anthropic SDK). Uses the `google-genai` SDK; model from `GEMINI_MODEL` (default `gemini-3.5-flash`). The PRD §6 system prompt is sent verbatim as `system_instruction`, with `response_mime_type=application/json` and temperature 0. All post-processing rules (confidence < 0.85 → null, one retry on bad JSON, never compute totals) are unchanged.

## Roles & UI redesign (PRD Section 18)

24. **Scoping mechanism.** The logged-in user lives in a `contextvars.ContextVar` that `app.py` sets on every run. It is per thread and per run, so concurrent Streamlit sessions never share it. With no user set, every data query raises `PermissionError` (fail closed).
25. **Minimal core edits.** `verify.check_duplicate` and `budgets.category_spent` had raw SQL. That SQL moved into user-scoped `db.find_duplicate_id` / `db.expense_spent`. Their logic is unchanged. `Bill` gained a persisted `user_id` field. `fmt_inr` now uses Indian digit grouping, which only changes output for amounts of ₹1,00,000 and above.
26. **Duplicates, bank matching, budgets and alerts are per user.** If two users upload the same file, it is not a duplicate. A bill only ever matches the uploader's own bank statement.
27. **`users.is_active` added** (not in the brief's column list) so admins can deactivate users. Deactivated users can't log in and are signed out on their next page load. Their data is kept.
28. **"Last active"** = the user's latest `audit_log` entry, so no extra column is needed.
29. **Reset database → "Clear my data".** It deletes only the logged-in user's rows. A global reset is not exposed in the UI (`db.reset_db` remains for tooling).
30. **Migration.** `ALTER TABLE ... ADD COLUMN user_id` on the existing tables. `budgets` is rebuilt to change its UNIQUE key. Rows with NULL `user_id` go to `business@demo` once it exists (`db.assign_orphans`, run on every start). Legacy bills keep their stored mode.
31. **Business-mode sample results.** BUSINESS requires `invoice_number` and `tax_amount`, plus GSTIN when tax > 0. Most sample receipts therefore land in MISSING_DATA for the business user, and Amazon goes there before the fraud rule because rule order is fixed (missing data beats fraud). This is correct per PRD 9.5. That is why AT-1 to AT-8 are demonstrated as the individual user.
32. **Pipeline animation.** `ui.components.process_with_progress` runs `extract_fields` first, which is the slow, live step. It then calls the unchanged `process_bill` with that result and writes each step's outcome. No pipeline code changed.
33. **Toasts.** At most one toast per page load. INDIVIDUAL users get at most one budget toast per session ("per visit"). Every alert still appears in the calm alerts list.
34. **Plain language.** INDIVIDUAL reasons are rewritten from the stored check results (`ui.components.plain_reasons`). BUSINESS users see the exact pipeline reasons. The DB keeps the original reason text either way.
35. **Admin privacy.** `db.admin_bill_stats` returns only status, fraud score, match status, timestamps and role. No images, file paths, merchants or amounts.
36. **Navigation folder** is `app_pages/`, not `pages/`, so Streamlit's legacy auto-discovery can't expose pages outside the role-based `st.navigation`.
37. **Demo passwords** live only in `.env`, which is gitignored. The login helper lists the seeded emails, never passwords.

## Section 19 changes

38. **Mandatory fields reduced** to merchant, bill_date, invoice_number, total_amount for both modes, at the product owner's request. This overrides CLAUDE.md rule 2 / PRD §8 for this constant only; all other thresholds are unchanged.
39. **Currency is requested when missing.** If a total is printed without a currency, `currency` is asked for, because converting to INR without it would be a guess. A total in a currency outside the sample FX table still routes to MISSING_DATA ("fx_rate").
40. **GSTIN rule removed.** A bill with tax but no GSTIN posts gross to expense (no Input GST split). The Business dashboard shows it as "GST at risk".
41. **Bank-match fallback tightened** (see PRD 19.3). This was the root cause of "budgets not syncing": unrelated nearby debits trapped bills in review. All 6 sample bills match by merchant alias, so AT-1 to AT-10 are unaffected.
42. **Toast policy.** One per page load, most severe first. This replaces "max one budget toast per visit", which hid later limit breaches. Persistent alerts now live in the notification centre (unread tracking in `settings` key `alerts_seen:<user_id>`).
43. **Notification and review counts render after `page.run()`** (in a `finally`, so they still render when a page calls `st.stop()`). This keeps them consistent with alerts and bills created during the same run.
44. **Gmail sign-in uses the installed-app OAuth flow** (`run_local_server`). Google opens the sign-in page in a browser on the machine running Streamlit, which suits this local demo; a hosted deployment would need a web OAuth redirect. The token is stored in `mail_accounts.token_json` inside `data/` (gitignored) and never leaves `core/db.py` / `core/mail.py`.
45. **Incremental email sync** tracks Gmail message ids in `mail_seen`. A message is marked seen only after its attachments have been processed.
46. **Tax summing** adds only printed amounts. A printed total wins over its components; a model value equal to a single component is replaced by the sum. Tax lines are kept in `line_items_json` for display, so no new column is needed.
47. **Rate-limit retry** happens in `_call_llm` (one retry after Google's `retryDelay`, max 65 s). It is separate from the PRD's retry-once-on-bad-JSON rule.
