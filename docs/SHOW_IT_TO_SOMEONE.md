# Letting somebody else look at your local copy

For "have a look at what I've built" — not for a customer, and not for
anything that has to stay up. Two public URLs pointing at your laptop, alive
only while the terminals are open.

If they need to test over days rather than minutes, this is the wrong tool;
deploy it instead.

---

## Before you start

Your laptop stays on and the terminals stay open. Close a window, the link
dies. Sleep the laptop, the link dies.

The link is public: anyone who has it reaches your **login page**. The data
behind it is still behind a password, but the roster holds 25 real people's
names, wages and dates of birth, so treat the URL as you would a key to the
back office. Stop the tunnel when they are done — `Ctrl+C` is the whole
security model here.

---

## One-time install

```powershell
winget install --id Cloudflare.cloudflared
```

No account, no signup. Free quick tunnels are exactly what this is for.

---

## Every time — four terminals, in this order

The order matters: both servers need to know the tunnel URLs before they
start, and the tunnels hand out a fresh random URL each run.

### 1. Backend tunnel

```powershell
cloudflared tunnel --url http://localhost:8001
```

Prints something like `https://tall-fox-runs.trycloudflare.com`. It will 502
until step 3 — that is expected. **Copy the URL.**

### 2. Frontend tunnel

```powershell
cloudflared tunnel --url http://localhost:3000
```

Another URL, e.g. `https://blue-lake-sings.trycloudflare.com`. **This is the
one you send your brother.** Copy it too.

### 3. Point the two at each other

`backend\.env` — let the frontend's address through CORS:

```
CORS_ORIGINS=http://localhost:3000,https://blue-lake-sings.trycloudflare.com
```

`frontend\.env` — tell the browser where the API lives. It cannot stay
`localhost`: the browser running this is on HIS machine, and localhost there
is HIS computer, not yours.

```
REACT_APP_BACKEND_URL=https://tall-fox-runs.trycloudflare.com
DANGEROUSLY_DISABLE_HOST_CHECK=true
```

That second line is needed because the dev server rejects requests whose Host
header it does not recognise, and a tunnel hostname never is. Without it the
page loads as **"Invalid Host header"** and nothing else.

### 4. Start both servers

```powershell
# backend, from backend\ with the venv active
uvicorn app.main:app --reload --port 8001

# frontend, from frontend\
yarn start
```

Create React App reads `.env` **once at startup**, so it has to start after
step 3. Editing it while running changes nothing.

---

## When it does not work

| What you see | Why |
|---|---|
| **Invalid Host header** | `DANGEROUSLY_DISABLE_HOST_CHECK=true` missing, or the frontend was started before it was added |
| Page loads, login fails, console says CORS | The frontend tunnel URL is not in `CORS_ORIGINS`, or the backend was not restarted after adding it |
| Page loads, every request fails | `REACT_APP_BACKEND_URL` is still `localhost` |
| **502 Bad Gateway** | That tunnel's server is not running yet |

---

## Afterwards

`Ctrl+C` both tunnels. Then put the two `.env` files back:

```
CORS_ORIGINS=http://localhost:3000
REACT_APP_BACKEND_URL=http://localhost:8001
```

Leaving the tunnel URLs in place means your local setup points at hostnames
that no longer exist, and the app will look broken tomorrow for a reason that
has nothing to do with your code.
