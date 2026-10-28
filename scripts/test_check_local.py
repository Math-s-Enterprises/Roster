"""Check the PowerShell runner's exit codes without Docker or live services.

Run on Windows: python -m unittest discover -s scripts -p test_check_local.py
"""
import shutil
import subprocess
import unittest
from pathlib import Path


POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
CHECK_SCRIPT = Path(__file__).resolve().parents[1] / "check-local.ps1"


@unittest.skipUnless(POWERSHELL, "PowerShell is needed to test the Windows runner")
class LocalCheckTests(unittest.TestCase):
    def run_check(self, failed_call):
        script_path = str(CHECK_SCRIPT).replace("'", "''")
        command = f"""$global:checkCalls = 0
function global:docker {{
    $global:checkCalls += 1
    Write-Host "DOCKER_CALL_$global:checkCalls"
    Write-Host "DOCKER_ARGS: $args"
    $global:LASTEXITCODE = if ($global:checkCalls -eq {failed_call}) {{ 17 }} else {{ 0 }}
}}
& '{script_path}'
"""
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=CHECK_SCRIPT.parent.parent, capture_output=True, text=True, timeout=30,
        )

    def test_backend_failure_stops_before_frontend_and_never_reports_success(self):
        result = self.run_check(1)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Backend checks failed", result.stdout)
        self.assertNotIn("DOCKER_CALL_2", result.stdout)
        self.assertNotIn("PASS:", result.stdout)

    def test_frontend_failure_returns_failure_and_never_reports_success(self):
        result = self.run_check(2)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("DOCKER_CALL_2", result.stdout)
        self.assertIn("Frontend checks failed", result.stdout)
        self.assertNotIn("PASS:", result.stdout)

    def test_success_requires_both_checks_and_works_outside_the_repository(self):
        result = self.run_check(0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DOCKER_CALL_2", result.stdout)
        self.assertNotIn("DOCKER_CALL_3", result.stdout)
        self.assertIn(f"compose -f {CHECK_SCRIPT.parent / 'docker-compose.yml'} exec -T", result.stdout)
        self.assertIn("backend python -m pytest", result.stdout)
        self.assertIn("ANTHROPIC_API_KEY=", result.stdout)
        self.assertIn("RESEND_API_KEY=", result.stdout)
        self.assertIn("CI=true", result.stdout)
        self.assertIn("yarn test --watchAll=false --runInBand && yarn build", result.stdout)
        self.assertIn("PASS: All local checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
