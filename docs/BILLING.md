# Plans and billing

Prices are the whitepaper's **launch hypotheses** (EUR per month, excluding VAT). Defaults live in `domain/accounts/plans.py`;
override any value in `configs/plans.yaml` without a code change.

| Plan | Price | Runs / mo | Scanning | Inference allowance | Projects | Seats | Retention | Max run |
|---|---|---|---|---|---|---|---|---|
| Developer | €0 | 100 | 0.1 GB | – | 1 | 1 | 7 days | 10 MB |
| Starter | €39 | 1,000 | 5 GB | €3 | 1 | 3 | 30 days | 25 MB |
| Team | €149 | 10,000 | 50 GB | €15 | 5 | 15 | 90 days | 50 MB |
| Business | €499 | 50,000 | 250 GB | €50 | 20 | 60 | 365 days | 100 MB |
| Enterprise | quoted (€12–30k / yr + €3–8k onboarding) | custom | custom | custom | custom | custom | custom | custom |

Features: the API is in every plan. **Starter** adds model-assisted review, custom profiles/policies and policy test suites. **Team** adds signed
webhooks, review roles, schedules, object-store delivery and Prometheus metrics export. **Business** adds audit export, configurable retention and priority
support. **Enterprise** adds SSO and private deployment.

## Rules
* One billable run is metered **once** per run when the policy decision is committed; retries and restarts never bill twice
  (idempotent per run and meter).
* Scan volume counts at least 1,024 bytes per run; 1 GB = 10⁹ bytes.
* When an allowance is exhausted, new runs are **held** (HTTP 402) unless auto-overage is on (off by default) or credit was topped up.
* Past-due subscriptions keep their plan for a 7-day grace period, then fall back to Developer. Cancelling takes effect at period end.
* Enterprise is set by an operator only: `python -m AIDAP admin set-plan --tenant T --plan enterprise`.

## Providers
`AIDAP_BILLING_PROVIDER=stripe` (hosted Checkout + customer portal + webhooks, idempotent per Stripe event id),
`sandbox` (simulated checkout inside the app; no money moves; refused in production) or `none` (self-serve disabled).
