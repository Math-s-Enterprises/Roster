$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'docker-compose.yml'

try {
    Write-Host '1/2 Checking the backend (in-memory test database)...'
    & docker compose -f $composeFile exec -T `
        -e ENV=test -e MONGO_URL=mongodb://127.0.0.1:27017 `
        -e DB_NAME=roster_test -e JWT_SECRET=local-check-not-for-production `
        -e BILLING_ENFORCED=false -e EMAIL_VERIFICATION_REQUIRED=false `
        -e ANTHROPIC_API_KEY= -e RESEND_API_KEY= -e GOOGLE_CLIENT_ID= `
        -e STRIPE_SECRET_KEY= -e STRIPE_WEBHOOK_SECRET= `
        backend python -m pytest -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend checks failed. Fix the error above before pushing.'
    }

    Write-Host '2/2 Checking frontend CSS, leave display, tests and production build...'
    & docker compose -f $composeFile exec -T `
        -e CI=true -e ENABLE_HEALTH_CHECK=false `
        -e REACT_APP_BACKEND_URL=http://127.0.0.1:8001 `
        frontend sh -c 'yarn check:css && yarn check:runs && yarn test --watchAll=false --runInBand && yarn build'
    if ($LASTEXITCODE -ne 0) {
        throw 'Frontend checks failed. Fix the error above before pushing.'
    }

    Write-Host 'PASS: All local checks passed. You can now run your git push command.' -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'If Docker or a container is unavailable, start Docker Desktop and your existing Roster containers, then retry.'
    exit 1
}
