# Continuous integration before deployment

`.github/workflows/ci.yml` runs on pull requests targeting `main`, pushes to
`main`, and manual Actions runs. Both jobs run independently:

- **Backend tests**: Python 3.11, install requirements, run the complete pytest suite.
- **Frontend tests and build**: Node 20, frozen Yarn lockfile, all frontend tests,
  then a production build with `CI=true` (warnings fail the build).

Backend fixtures replace MongoDB with an in-memory database. Integration keys are
empty and the JWT key is test-only. No Atlas connection, customer data, Railway,
Vercel or Stripe credentials are needed. Actions have read-only repository access,
are pinned to verified commit revisions, and checkout does not retain credentials.
Repeated runs on the same PR cancel older runs. Each job has a 20-minute timeout.

## Make the checks mandatory

1. Push `ci-launch-checks` and open a pull request into `main`.
2. Wait for **Backend tests** and **Frontend tests and build** to succeed.
3. In repository Settings, edit the existing ruleset/branch protection targeting
   `main`. Keep the pull-request requirement and other existing protections.
4. Enable “Require status checks to pass” and select those two checks from their
   first completed run. Require the branch to be up to date before merging.
5. Save, then merge the CI pull request only when its required checks pass.

The YAML itself does not change branch protection. If GitHub Actions is disabled
or an organisation policy blocks the pinned Actions, an administrator must enable
the allowed workflow first. Do not bypass a failing or absent check to deploy.

## Deployment remains manual

This workflow does not deploy. After a green merge, deploy the backend to Railway,
verify its public API, then deploy Vercel and configure backend URL/CORS. Initially
leave automatic production deployments disabled or gated; merely connecting the
repository to a hosting provider must not let unverified pushes deploy customers'
production app. Deployment tokens and a CD workflow are intentionally not added.

Locally, from the matching subdirectory, run:

```text
backend:  python -m pytest
frontend: yarn test --watchAll=false --runInBand
frontend: yarn build     (set CI=true for the strict check)
```

Jest and Webpack both resolve `@/` to `frontend/src`. Backend requirements explicitly
request JWT cryptography and Google requests support, rather than relying on packages
left over in a developer's environment. Backend dependency floors remain unpinned;
a production lockfile and GitHub-hosted execution still require verification.
