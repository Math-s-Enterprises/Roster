# Docker development checkout

Use `C:\Users\anees\Roster` as the working folder in VS Code and Codex.
The Desktop checkout is a separate copy; edits there do not reach these containers.

From PowerShell:

```powershell
cd C:\Users\anees\Roster
docker compose up -d --build
```

The existing Compose setup mounts `./frontend` and `./backend` into `/app`.
Frontend polling and backend `--reload` pick up saved source changes while
containers are running. Refresh the browser if it still shows the previous UI.
Restarting in Docker Desktop reuses the same images; rebuild when requirements,
Dockerfiles or installed dependencies change. Environment changes require
recreating the affected service.

```powershell
docker compose exec -T -e CI=true frontend yarn test --watchAll=false --runInBand
docker compose exec -T backend python -m pytest
```

Keep `.env` files local. MongoDB uses the existing `mongo-data` volume;
never use `docker compose down -v` to refresh code, because it deletes volumes.
Keep `mongo-backup` untouched and excluded from Git.
