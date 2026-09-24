/**
 * Kobo, as a person reads naira. Never through a float.
 *
 * The API sends whole kobo as integers, and this formats them by cutting the
 * digit string — the last two digits are kobo — so there is no division
 * anywhere for binary floating point to get wrong. The sign is never dropped
 * silently: a balance is said in words ("owes", "in credit") because a minus
 * sign on a phone screen is the character most easily missed, and a family in
 * credit being chased for money is the mistake this page must not make.
 */

/** "₦1,500,050.00" for 150005000 kobo. The magnitude only; see `signed()`. */
export function naira(kobo) {
  const digits = String(kobo).replace(/^-/, "").padStart(3, "0");
  const whole = digits.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `₦${whole}.${digits.slice(-2)}`;
}

/** An entry's amount with its direction: "+" raises what is owed, "−" lowers it. */
export function signed(kobo) {
  return `${Number(kobo) < 0 ? "−" : "+"}${naira(kobo)}`;
}

/** What an account stands at, in words. */
export function balanceWords(kobo) {
  const n = Number(kobo);
  if (n > 0) return { tone: "owes", text: `Owes ${naira(n)}` };
  if (n < 0) return { tone: "credit", text: `In credit ${naira(n)}` };
  return { tone: "settled", text: "Nothing owed" };
}
