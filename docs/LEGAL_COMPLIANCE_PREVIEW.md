# Legal/compliance implementation and release caveats

This describes the engineering implementation, not final legal validation.
The publisher section of the Legal Notice is intentionally incomplete until
the operator supplies and reviews the applicable information for professional
publication as a French entrepreneur individuel / micro-entrepreneur.

## Implementation

- Public `/terms`, `/privacy`, `/legal`, `/cookies` and `/support`, with shared
  legal navigation in public, onboarding and authenticated surfaces.
- `backend/terms.json` is the shared Terms text and authoritative version:
  `2026-09-25`. For a material future change, update the text and version together
  and release frontend/backend together. Accounts with older versions must agree again.
- Account fields: nullable `terms_version` and timezone-aware
  `terms_accepted_at`. Exactly one additive migration,
  `0014_account_terms_acceptance`, follows `0013_group_availability_override`.
  There is no default or acceptance backfill. Downgrade removes the fields and
  their paired-value constraint, and therefore loses acceptance metadata.
- Authenticated GET/PUT `/api/me/terms` (and existing proxy-style `/me/terms`
  aliases). PUT accepts the current version only, rejects client timestamps and
  unknown fields, generates the timestamp server-side, locks the Account and
  preserves the timestamp for repeated acceptance of the same version.
- Normal planner dependencies return a structured 403
  `terms_acceptance_required`. Onboarding profile creation is also gated.
  Account information, onboarding status, Terms endpoints, export, notification
  preferences, public legal information and support remain accessible.
- New users have the existing display-name form plus an unchecked Terms-only
  checkbox. Linked users see Terms renewal without creating a second profile.
  Privacy is informational, not a required consent. Safe internal return paths
  are retained. Stale tabs use Next router navigation when the API requires renewal.
- Export schema version 5 includes acceptance metadata. No separate Privacy
  consent, age policy, marketing feature, paid-service framework or cookie banner.
- Support includes technical/account questions, privacy rights, deletion and
  private illegal/abusive-content reporting. Ownership resolution through Support
  remains possible when a user declines updated Terms.

## Clerk and browser storage

Root `ClerkProvider telemetry={false}` and
`NEXT_PUBLIC_CLERK_TELEMETRY_DISABLED: "1"` disable Clerk's optional SDK usage
telemetry through supported configuration. Authentication and security storage
remain necessary. No advertising or behavioral analytics integration was
identified in this application, and no cookie-consent banner was added. The
public Cookies page describes stable categories rather than transient SDK
storage keys. This does not claim to audit every external identity-provider
page or every third-party request.

## Migration and development verification

`0014_account_terms_acceptance` follows `0013_group_availability_override`.
Existing rows receive NULL acceptance fields, with no default or silent
acceptance. Development testing exercised the explicit Terms flow and verified
the server timestamp and Account / Data visibility. PostgreSQL tests use guarded,
disposable test databases; production data was not used for validation.

## Validation

| Check | Result |
| --- | --- |
| `uv run pytest -q --ignore=backend/tests/postgres --tb=short` | 241 passed |
| `pytest -q backend/tests/postgres --tb=short`, guarded local admin URL and `REQUIRE_POSTGRES_TESTS=1` | 105 passed, no skips |
| `uv run ruff check backend` | Passed |
| `uv run ruff format --check --config "format.line-ending='auto'" backend` | 67 files already formatted |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed |
| `npm run test` | 68 passed across 16 files |
| `npm run build` | Passed, including all legal routes and standalone output |
| Follow-up affected-file ESLint and seven legal tests | Passed |
| `git diff --check` | Passed |

The line-ending-aware Ruff format check avoids rewriting unrelated CRLF files.
The public Terms page imports `backend/terms.json`: `turbopack.root` includes
the repository during development, and the frontend Docker builder copies
that public JSON into its build context. The legal routes and navigation were
reviewed at 1440, 1024 and 375 CSS pixels without horizontal overflow.
The explicit acceptance flow and stale-version behavior have automated coverage.
The tests above describe the completed local preview; release CI must run again.

## Deferred operator information and final legal review

The operator intends professional publication as a French entrepreneur
individuel / micro-entrepreneur. The present Legal Notice does not claim that
status or invent the associated identity. Confirm and configure as applicable:

1. `LEGAL_OPERATOR_NAME`: actual operator/data-controller name.
2. `LEGAL_OPERATOR_STATUS`: actual legal status.
3. `LEGAL_OPERATOR_ADDRESS`: appropriate legal postal address.
4. `LEGAL_OPERATOR_PHONE`: applicable published contact telephone.
5. `LEGAL_OPERATOR_CONTACT`: valid `mailto:` or HTTPS contact; may fall back to support.
6. `LEGAL_PUBLICATION_DIRECTOR`: actual publication director.
7. `SUPPORT_CONTACT_URL`: verify the public support/rights/reporting destination
   in the production runtime environment. A local development setting does not
   establish its production value.

Hosting details are now stated from OVHcloud's published legal notice: OVH SAS,
SAS with €50,000,000 capital, RCS Lille Métropole 424 761 419 00045,
2 rue Kellermann, 59100 Roubaix, France. The public page links to OVHcloud's
official contact page. A hosting telephone is omitted: the available general
support number was not verified as the right number for this legal disclosure.

Also review identification requirements applicable to the operator's real status
(registration/VAT details only if applicable); actual SMTP provider, processors,
agreements, processing locations and transfer safeguards; log/support/delivery
retention and separate deployment-backup retention; practical deletion/restore
procedures; legal bases, moderation/restrictions, liability, applicable law and
trademark wording. The 14-day VPS and 90-day off-site periods are verified against
repository backup scripts/docs, not a fresh production inspection.

These incomplete disclosures deliberately remain visible. Human/legal review is
needed before final publication; passing tests is not legal certification.
The current deployment script's frontend runtime environment allowlist does
not accept the new `LEGAL_*` settings. That must be addressed when the final
operator details are supplied, but absent values safely render the explicit
incomplete state and do not block this engineering release.

## Complete changed-file inventory

Paths below are repository-relative. No existing files were deleted.

### Backend implementation — modified

- `backend/account_data.py`: export acceptance metadata, schema 5.
- `backend/auth.py`: current-Terms planner gate; separate rights/account dependency.
- `backend/main.py`: Terms status/acceptance API, onboarding gate and response fields.
- `backend/models.py`: nullable Account acceptance fields and paired-value constraint.
- `pyproject.toml`: register the explicit unaccepted-Terms test marker; no dependency change.

### Backend implementation/tests — new

- `backend/terms.json`: authoritative public Terms text/version.
- `backend/terms.py`: shared version/status/acceptance contract.
- `backend/migrations/versions/0014_account_terms_acceptance.py`: additive migration.
- `backend/tests/test_terms.py`: rights access, gates, versions, timestamps, renewal/idempotence.
- `backend/tests/postgres/test_terms_migration.py`: existing rows, constraint, timestamp and downgrade.

### Existing backend tests — modified

- `backend/tests/postgres/test_account_data.py`: expected head.
- `backend/tests/postgres/test_import_legacy_sqlite.py`: expected head/reset path.
- `backend/tests/postgres/test_migrations.py`: current migration head expectations.
- `backend/tests/postgres/test_runtime_security.py`: current migration head.
- `backend/tests/test_account_data.py`: export schema.
- `backend/tests/test_auth.py`: explicit Terms agreement before planner access.
- `backend/tests/test_availability_modes.py`: accepted synthetic domain fixtures.
- `backend/tests/test_phase_2b_auth.py`: accepted fixtures, explicit unaccepted opt-out and response fields.
- `backend/tests/test_session_event_emails.py`: synthetic agreement and export schema.

### Frontend configuration — modified

- `frontend/.env.example`: blank operator/support runtime configuration contract;
  verified hosting details do not need operator-supplied environment variables.
- `frontend/next.config.ts`: supported telemetry flag and shared-document Turbopack root.
- `deploy/Dockerfile.frontend`: copy the public shared JSON into the builder only.

### Frontend routes — modified

- `frontend/src/app/account/page.tsx`: rights access without querying gated group data.
- `frontend/src/app/app/page.tsx`: current-Terms entry gate.
- `frontend/src/app/groups/[groupId]/page.tsx`: current-Terms entry gate.
- `frontend/src/app/groups/[groupId]/sessions/page.tsx`: current-Terms entry gate.
- `frontend/src/app/groups/[groupId]/settings/page.tsx`: current-Terms entry gate.
- `frontend/src/app/join/[code]/page.tsx`: current-Terms gate preserving invite return.
- `frontend/src/app/layout.tsx`: supported Clerk opt-out and Next navigation listener.
- `frontend/src/app/onboarding/page.tsx`: explicit first/renewed acceptance.
- `frontend/src/app/page.tsx`: authenticated landing redirect respects acceptance.
- `frontend/src/app/privacy/page.tsx`: expanded factual privacy notice, verified
  OVH host and conditional Clerk transfer language; SMTP provider remains generic.
- `frontend/src/app/schedule/page.tsx`: current-Terms entry gate.
- `frontend/src/app/support/page.tsx`: support/rights/content-reporting categories
  and practical information for confidential content reports.

### Frontend routes/components/helpers — new

- `frontend/src/app/cookies/page.tsx`: stable authentication/preference storage
  categories and supported telemetry opt-out, without developer-only cache details.
- `frontend/src/app/legal/page.tsx`: Service / Publisher / Hosting sections;
  unresolved publisher fields stay explicit, verified OVH details are static.
- `frontend/src/app/terms/page.tsx`: shared versioned Terms document.
- `frontend/src/components/LegalLinks.tsx`: reusable five-link navigation.
- `frontend/src/components/TermsAcceptanceControl.tsx`: accessible Terms-only checkbox.
- `frontend/src/components/TermsNavigation.tsx`: Next router handling of stale-tab gates.
- `frontend/src/lib/legal.ts`: public legal links and disclaimer constants.
- `frontend/src/lib/legalConfig.ts`: server-page runtime operator configuration;
  obsolete host settings removed.
- `frontend/src/lib/legal.test.tsx`: seven focused legal/enforcement presentation tests.

### Existing frontend components/helpers/tests — modified

- `frontend/src/components/AccountDataView.tsx`: agreement metadata and rights guidance.
- `frontend/src/components/AppShell.tsx`: compact authenticated legal navigation.
- `frontend/src/components/PublicInfoPage.tsx`: shared legal footer and article formatting.
- `frontend/src/lib/accountPrivacy.test.tsx`: Account response fixture.
- `frontend/src/lib/onboarding.ts`: accepted-and-linked predicate, safe renewal return, event name.
- `frontend/src/lib/privacyRoutes.test.ts`: five public routes.
- `frontend/src/services/api.ts`: typed Terms metadata, acceptance call and central gate handling.
- `docs/LEGAL_COMPLIANCE_PREVIEW.md`: this handoff and release-review checklist (new).

## Primary references

- [Clerk supported telemetry opt-out](https://clerk.com/docs/guides/how-clerk-works/security/clerk-telemetry)
- [Clerk cookies](https://clerk.com/docs/guides/how-clerk-works/cookies)
- [Next Turbopack root configuration](https://nextjs.org/docs/app/api-reference/config/next-config-js/turbopack)
- [CNIL cookies guidance](https://www.cnil.fr/fr/cookies-et-autres-traceurs/que-dit-la-loi)
- [CNIL data subject rights](https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre3)
- [French government website-disclosure guidance](https://www.economie.gouv.fr/entreprises/developper-son-entreprise/innover-et-numeriser-son-entreprise/mentions-sur-votre-site-internet-les-obligations-respecter)
- [OVHcloud official legal notice](https://www.ovhcloud.com/fr/terms-and-conditions/)
- [OVHcloud official contact](https://www.ovhcloud.com/fr/contact/)
- [Clerk Data Processing Addendum, international transfers](https://clerk.com/legal/dpa)
