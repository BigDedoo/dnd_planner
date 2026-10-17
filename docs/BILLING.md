# PRO memberships (Stripe)

DnD Planner has two plans. **Free** accounts can own up to
`FREE_OWNED_GROUP_LIMIT` groups (default 2) and join any number of groups.
**PRO** removes the owned-group limit. Players never need to pay to join or use
a group. Nothing changes until `BILLING_ENABLED=true`: while it is false the
limit is not enforced, the billing endpoints return 404 and the Account page
hides the Membership section.

## How it works

- `POST /api/billing/checkout` (`{"interval": "month" | "year"}`) creates the
  user's Stripe customer once, then returns a Stripe Checkout URL.
- `POST /api/billing/portal` returns a Stripe Customer Portal URL, where
  members change plan, update their card, download invoices or cancel.
- `POST /api/billing/webhook` receives Stripe events. It verifies the
  `Stripe-Signature` header, then re-reads the subscription from Stripe and
  stores its current state in `billing_subscriptions`. Repeated or
  out-of-order events therefore converge on the same row. A failure returns
  500 so Stripe retries the delivery.
- `GET /api/me/membership` returns the plan, owned-group count and limit.
- A user is PRO while one of their subscriptions is `active`, `trialing` or
  `past_due` (Stripe is still retrying a failed payment). `canceled`,
  `unpaid`, `incomplete` and `paused` are Free.
- The limit applies only when creating a group. Owners already above the
  limit, or who receive groups by ownership transfer, keep them.
- Downgrading never deletes data: an owner above the limit just cannot create
  another group until they are back under it or PRO again.

## Before turning billing on

1. **Legal**: fill in the operator details (see
   [LEGAL_COMPLIANCE_PREVIEW.md](LEGAL_COMPLIANCE_PREVIEW.md)), add terms of
   sale (price, renewal, cancellation, the EU 14-day withdrawal right), update
   the Terms ("a free service" in `backend/terms.json`) and list Stripe as a
   payment processor in the Privacy Policy. Decide whether you charge VAT:
   under the French *franchise en base* you don't; otherwise turn on Stripe
   Tax and set `STRIPE_AUTOMATIC_TAX=true`.
2. **Stripe account**: activate payments for your business, then in the
   Dashboard (do it in test mode first):
   - Create a product "DnD Planner PRO" with a monthly (€3.90) and a yearly
     (€39) recurring EUR price. Copy the two `price_...` IDs.
   - Configure and save the Customer Portal (Settings > Billing > Customer
     portal): allow cancelling, updating payment methods, viewing invoices and
     switching between the two prices.
   - Add a webhook endpoint `https://dnd-planner.dedoo.fr/api/billing/webhook`
     with the events `checkout.session.completed`,
     `customer.subscription.created`, `customer.subscription.updated`,
     `customer.subscription.deleted`, `customer.subscription.paused` and
     `customer.subscription.resumed`. Copy its signing secret (`whsec_...`).
3. **VPS** `runtime.env` (backend only, mode 0600):

   ```
   BILLING_ENABLED=true
   APP_PUBLIC_URL=https://dnd-planner.dedoo.fr
   STRIPE_SECRET_KEY=sk_live_...   # or a restricted key
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_PRO_MONTHLY=price_...
   STRIPE_PRICE_PRO_YEARLY=price_...
   STRIPE_AUTOMATIC_TAX=false
   ```

   The backend refuses to start if billing is enabled with a missing value.
   A restricted key needs write access to Customers, Checkout Sessions and
   Customer Portal sessions, and read access to Subscriptions.
4. Deploy (migration `0015_billing_subscriptions` adds the two tables), then
   run one test-mode purchase with card `4242 4242 4242 4242`, check the
   Account page shows PRO, cancel it from Manage billing and check it returns
   to Free at the end of the period.

## Local testing

Use test keys and the Stripe CLI to forward events:

```
stripe listen --forward-to localhost:8000/billing/webhook
```

and put the `whsec_...` it prints in `STRIPE_WEBHOOK_SECRET`.

## Account deletion and export

The personal data export includes the Stripe customer ID and subscription
history. Operator account deletion is blocked while a subscription is still
PRO; cancel it in Stripe first. Deletion then removes the local billing rows,
while Stripe keeps the invoices for accounting.
