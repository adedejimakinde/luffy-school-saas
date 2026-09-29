# Paystack: fees paid online, straight to each school

**Test mode only.** `fees/paystack.py` refuses any secret key that does not start
`sk_test_`, before it makes a call. Nothing in this build has been sent to
Paystack's real servers: every test mocks `urllib.request.urlopen`, and the
endpoints below are **from memory of Paystack's public API, unverified** (its
documentation was not reachable when this was written).

## The rule

**Classnode never holds a school's money.** A payment is split at Paystack to the
school's own *subaccount*, 100% of it, and Paystack settles that to the school's
own bank account. The platform takes no share and the **school bears Paystack's
fees**. Where those two facts are set:

- the subaccount is created with `percentage_charge: 0` (the platform's share);
- a *split* is created giving that subaccount `share: 100` with
  `bearer_type: "subaccount"`.

The split matters more than it looks. A subaccount alone leaves the fee bearer
at Paystack's default, the main account, which is Classnode: with a 0% share the
fee would be charged to the platform. `tests/test_bank` pins both payloads.

## Configuration (environment, never in the repository)

| variable | |
| --- | --- |
| `PAYSTACK_SECRET_KEY` | `sk_test_…`. A secret: `secrets.env`, not `production.env`. |
| `PAYSTACK_WEBHOOK_SECRET` | Optional. Paystack signs webhooks with the secret key, so this defaults to it. Used by PR 2's webhook. |
| `PAYSTACK_BASE_URL` | Default `https://api.paystack.co`. |
| `PAYSTACK_TIMEOUT` | Seconds, default 15. |

The key is read per call and is never put in an exception, a log line or a page.

## PR 1: a school's bank connection (step 1)

Bursar and administrator only (`fees.authority.may_write`); the principal and vice
principal read it, with the account number as its last four digits. Screen:
`/bank/` ("Bank" under Office). API: `/api/fees/bank/`.

1. Choose the bank (Paystack's list, `GET /bank`) and type the ten-digit number.
2. `POST resolve/` asks Paystack's `GET /bank/resolve` for the **name the bank
   holds**, and shows it. Nothing is written.
3. The person confirms it. `POST /` **resolves again** and compares before it
   writes; a name that differs (typed, or the bank changed it) is a 409 and
   nothing is created at Paystack or saved.
4. It creates the subaccount and the split, and saves a `fees.SchoolBank` row
   holding **Paystack's** name (never the typed one), both codes and who did it.

`SchoolBank` is per school (tenant schema) and **never edited or deleted** (model
and trigger, like the ledger). Changing bank `PUT`s the same subaccount to the new
account and adds a row; the latest is current. The school's row is locked across
the Paystack calls, so two people pressing Connect together make one subaccount.
If the subaccount is made and the split then fails, the subaccount is an orphan
at Paystack (nothing points at it); the next attempt makes another.

Paystack absent (no key, a live key, unreachable, a bad key, a 5xx, an unreadable
reply) is a 503 with one sentence and none of Paystack's words.

## Not built yet (PR 2)

Steps 2 and 3: a dedicated virtual account per student created against the
school's subaccount (it will need the stored `split_code` so the fee bearer holds
for it too), shown on the fees, parent, reminder and receipt pages; and the
webhook (`x-paystack-signature` HMAC-SHA512, re-verify the transaction with
Paystack, `record_payment()` once per reference, an "unmatched payments" list).
