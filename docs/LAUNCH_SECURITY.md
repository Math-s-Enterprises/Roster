# Authentication and upload safeguards

Authentication attempts use atomic MongoDB counters shared by all backend workers.
Limits are per client address and endpoint, counting successful and failed attempts:

| Endpoint | Requests | Window |
|---|---:|---:|
| Login / Google sign-in | 20 | 60 seconds |
| Signup / forgot password | 5 | 15 minutes |
| Reset password | 10 | 60 seconds |

Excess attempts return HTTP 429 and `Retry-After`; database errors fail closed with
503. Counters contain hashed addresses, not raw IPs, and expire through MongoDB's
TTL index. Fixed windows can allow two windows' allowances near a boundary. People
sharing an office/public IP also share its allowance. This is not DDoS protection.

Before deployment, configure Uvicorn to trust only the actual ingress proxy and
verify `request.client.host` represents the end user. Do not blindly trust arbitrary
`X-Forwarded-For` headers or expose a backend that trusts all forwarding sources.
Without correct ingress configuration everyone may share the proxy's allowance;
overly broad trust lets attackers spoof addresses. Test this on Railway staging.

Google identities are matched by verified `sub`, with a unique partial database
index. Matching email alone cannot replace a linked subject. Automatic linking of
an unlinked account requires Gmail or a verified Google Workspace `hd` claim.
Other existing accounts must use password sign-in; there is no new self-service
Google-linking screen. Concurrent signup/link races run the same checks and use a
compare-and-set update. Existing duplicate Google subjects will prevent the unique
index from building: investigate them rather than deleting customer accounts.

Roster uploads read at most 25MB + one byte; contact uploads read at most 5MB + one
byte. Oversized files return 413 before parsing. The multipart framework may spool
the request to disk before handlers run, so production ingress also needs a body
size limit and request timeout. These checks do not bound spreadsheet decompression.

Emergent's external script and PostHog bootstrap were removed from the public HTML.
Google fonts and Google sign-in remain intentionally enabled. No replacement
analytics or consent system was added.

Google verification now allows five seconds of timestamp skew, including expiry,
while preserving signature, audience and issuer verification. Larger clock errors
still require server/host time synchronisation. Verification failures return a
friendly message rather than raw timestamps; certificate transport failures return
temporary-unavailability errors instead of blaming the credential.

Stripe entitlement handling remains outstanding. These checks are not a completed
penetration test or dependency vulnerability audit.
