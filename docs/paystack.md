# Paystack: fees paid online, straight to each school

**Test mode only.** `fees/paystack.py` refuses any secret key that does not start
`sk_test_`, before it makes a call. Nothing in this build has been sent to
Paystack's real servers: every test mocks `urllib.request.urlopen`. Paystack's
documentation was not reachable when this was written; the review of #217 checked
the subaccount calls (the bank field is `bank_code`, on create and update), the
split's fields and `percentage_charge: 0` against the current docs, and a second
review the bank list (`perPage` at most 100, paged by cursor) and the account resolve.
None of it has been called against the real service.

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
| `PAYSTACK_SECRET_KEY` | `sk_test_…`. A secret: `secrets.env`, not `production.env`. **It is also what verifies webhooks:** Paystack signs them with the account's secret key. |
| `PAYSTACK_BASE_URL` | Default `https://api.paystack.co`. |
| `PAYSTACK_TIMEOUT` | Seconds, default 15. |

The key is read per call and is never put in an exception, a log line or a page.

**There is no separate webhook secret.** Paystack signs webhooks with the
account's secret key, so `PAYSTACK_SECRET_KEY` is the webhook's secret too, and the
webhook code reads that one setting. (An earlier draft had a
`PAYSTACK_WEBHOOK_SECRET` that defaulted to it; it was dropped so the two cannot
drift apart.) A key that is not `sk_test_` refuses every webhook as well as every
call.

## PR 1: a school's bank connection (step 1)

Bursar and administrator only (`fees.authority.may_write`); the principal and vice
principal read it, with the account number as its last four digits. Screen:
`/bank/` ("Bank" under Office). API: `/api/fees/bank/`.

1. Choose the bank (Paystack's list, `GET /bank`, every page: `perPage` 100 with `use_cursor=true`, following `meta.next` until there is none) and type the ten-digit number.
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

## PR 2: an account for each child (step 2)

`POST /api/fees/virtual/students/{id}/` (bursar and administrator; a principal is
told they may not; everybody else gets the flat 404) makes, or returns, **one
dedicated virtual account per child**. It needs the school's bank first (a 409
says so). It creates a Paystack customer, then a dedicated account **settling
through the school's split** (`split_code` from PR 1, which carries the
subaccount, its 100% share and the school as fee bearer), and saves a
`fees.VirtualAccount` (per school, never edited or deleted, unique per child and
per number). A public `schools.PaystackRoute` row, written in the same
transaction, says which school an account number belongs to, because a webhook
arrives on the portal with nothing else to go on.

Where it is shown: the bursar's account page for the child (with the button to
make it), the parent's page (`GET /api/fees/virtual/mine/`, the caller's own
children only, through the same family scope as the card index), and the text of
**fee reminders and receipts**: ` Pay into: Wema Bank 1234567890, Ada Bello.`
(`virtual.pay_into_sentence()`), and nothing extra for a child with no account.

Settings: `PAYSTACK_DVA_BANK` (default `wema-bank`; Paystack's test mode is
believed to want `test-bank`, so set it for a test deploy: unverified) and
`PAYSTACK_CUSTOMER_EMAIL_DOMAIN` (a Paystack customer needs an email and a child
rarely has one, so it is `<school>-<child id>@<domain>`).

## PR 2: the webhook (step 3)

`POST /api/paystack/webhook/`, on the **portal host only**, exempt from CSRF and
authenticated by signature alone. `fees/webhook.py` says it in order:

1. **Signature.** `x-paystack-signature` is the HMAC-SHA512 of the raw body under
   **`PAYSTACK_SECRET_KEY`** (Paystack signs with the account's secret key; there is
   no separate secret), compared in constant time. A bad, missing or unconfigured
   signature, or a key that is not `sk_test_`, is a 401 before anything is parsed
   or asked of Paystack.
2. **Paystack itself.** `GET /transaction/verify/:reference` must agree: success,
   the same reference, the same amount in kobo, NGN. Everything after reads the
   **verified** record, not the webhook's words. Paystack unreachable is a 503 (it
   sends again); a transaction that does not verify is a 200 that records nothing.
3. **Whose.** The account number (`authorization.receiver_bank_account_number`) is
   looked up in `schools.PaystackRoute`, then in that school's `VirtualAccount`, and
   the customer code (`customer.customer_code`) must be the one the account was made
   for. Both are read from the verified record; **a field the verify reply does not
   carry is taken from the same field of the signed event** (the signature already
   proves it came from Paystack), each field on its own, and the verify reply wins
   wherever it has one.
4. **Once.** `record_payment_once()` with a form key derived from the reference
   (`uuid5`), method `bank_transfer`, the reference in the entry: a replay, or two
   at once, is one entry, because the unique index is the mechanism.

**Never guessed.** A payment that cannot be placed is listed and touches no
child's books: an account no school owns goes to `schools.UnroutedPayment` (the
platform's to look into); a route with no account, a different customer, a child
who is not a student here, or a school with no current term go to that school's
`fees.UnmatchedPayment`, shown to the bursar under "Payments we could not match"
on the bank page (`GET /api/fees/virtual/unmatched/`). An unmatched reference
stays unmatched if it arrives again; putting the money on a child is a person's
decision (next section), and a replay of a payment that has been placed answers
`duplicate`.

Only `charge.success` is acted on; an amount that is not a positive whole number
of kobo is ignored.

## Placing an unmatched payment, and the platform's unrouted list

**The bursar puts an unmatched payment on a child** (`POST
/api/fees/virtual/unmatched/{id}/placement/`; bursar and administrator, the
principal is told they may not, everyone else gets the flat 404). On `/bank/`, under
"Payments we could not match": "Place on a child", pick the class and the child,
read back the amount and reference, confirm. `fees/placing.py` says the rules:

- It posts through **`record_payment_once()` with the Paystack reference**, the same
  derived form key the webhook uses, so the money is in the ledger at most once
  whichever of the two got there first. If the ledger already holds that key, the
  money is already in somebody's account and the placement is refused (409).
- **The server posts its own amount.** The person *confirms* the amount (whole
  kobo) and the reference; a confirmation that is not what the payment says is a 409
  and writes nothing.
- **Once, at the database:** `fees.UnmatchedPlacement` is one-to-one with the payment
  and with the entry it made, never edited or deleted (model and trigger), and the
  payment row is locked so two people pressing at once place it once. Placing it again
  on the same child is the placement that is there (200); on another, a 409 saying
  where it went.
- **It records who:** the entry's `recorded_by` is the person (so the receipt names
  them), and the placement freezes their name and the child's.
- It posts to the **current term**, and with none says so (422) and posts nothing.
- A mistaken placement is undone as any payment is, by a reversal on the child's
  account; the payment cannot be placed again.

**Platform staff** see payments no school owns (`schools.UnroutedPayment`) on the
platform page (`GET /api/platform/unrouted/`, platform staff only, portal host only,
read only). Nobody can place these: an account no school owns has no school's books
to put money in.

## Still unverified (both PRs)

The dedicated-account and transaction-verify calls are from memory of Paystack's
API and have not been called against the real service. Where the receiving account
number and the customer code sit (`authorization.receiver_bank_account_number`,
`customer.customer_code`) is why matching falls back to the signed event's own
fields when the verify reply lacks them; if Paystack puts them in neither place
under those names, a payment is listed as unmatched or unrouted, never guessed.
