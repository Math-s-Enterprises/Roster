# Shared Atlas database with local Docker

The application still runs locally; only MongoDB is in the cloud. Use the
working checkout at `C:\Users\anees\Roster`. Frontend/backend hosting is separate.

## Start with Atlas

Keep these values in the ignored `backend/.env`, never in Git:

```dotenv
ATLAS_MONGO_URL=mongodb+srv://<database-user>:<url-encoded-password>@<cluster-host>/?appName=Roster
DB_NAME=roster_dev
```

Keep existing authentication settings. Permit each developer's current public
IP in Atlas, and use a separate database user with access only to the application
database where possible. Do not put the URI in frontend environment variables.

From the repository root:

```powershell
docker compose --env-file backend/.env -f docker-compose.yml -f docker-compose.atlas.yml up -d
```

The override replaces the base Compose file's hardcoded local `MONGO_URL`.
It fails if `ATLAS_MONGO_URL` is missing and disables development reset/seed
routes on shared data. Docker Desktop stop/start retains the recreated
container's configuration. When recreating containers from the command line,
include this override again; plain `docker compose up` selects local MongoDB.

Open `http://localhost:3000` and sign in with the existing app account.
Another developer running the same setup can access the same account/data;
their machine needs Atlas network access and private backend configuration.
All development changes against this database affect shared data. Use a separate
database for experiments and never aim tests or reset scripts at shared data.

## Migration performed

The authorised transfer paused backend writes, backed up `roster_dev`, then
restored into an empty Atlas target using the native MongoDB tools. Before
switching the backend, verification compared all document contents/IDs, counts
and indexes across 13 collections (458 documents). Existing password hashes and
shop relationships were preserved, not recreated.

Private backup: `mongo-backup/atlas-transfer/local-final.archive.gz`.
That folder is ignored by Git. Protect it as sensitive account/staff data.
The one-off restore credential file was removed. Routine backup scheduling
has not been configured by this migration.

## Local fallback

The original MongoDB volume remains intact. This command deliberately returns
only the backend to the old local database:

```powershell
docker compose -f docker-compose.yml up -d --no-deps backend
```

It does **not** copy subsequent cloud changes back. Local and Atlas are separate
databases; do not alternate them expecting synchronisation. Never remove the
MongoDB volume or overwrite the backup to switch connections.
