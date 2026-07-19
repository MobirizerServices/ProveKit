> **Note — alternative topology, not the current setup.** provekit.online runs on a *dedicated* VPS via [DEPLOY_PROVEKIT_ONLINE.md](DEPLOY_PROVEKIT_ONLINE.md). Keep this only if you later co-host with another app on one box.

# One-at-a-time on the Contabo VPS (cere ⇄ ProveKit toggle)

Run **one** app at a time on the VPS and switch on demand. Each app runs its own Caddy and
owns 80/443 while it's up, so there's no conflict — the inactive app is simply stopped. Data
persists across switches (named Docker volumes; the toggle never deletes them).

```
DNS: cerebrozen.in  ─┐
     provekit.online ─┴─▶ 194.163.182.1 (VPS)   ← whichever stack is UP answers on 80/443
```

## One-time setup (on the VPS)

Both repos checked out (e.g. `~/cere` and `~/ProveKit`), and:

```bash
cd ~/ProveKit
cp deploy/provekit.online.env.example deploy/provekit.online.env
# fill in: SECRET_KEY, POSTGRES_PASSWORD, and the WORKING Titan SMTP password.
# (DOMAIN=provekit.online is already set.)
```

Point **both** domains' A-records at the VPS IP. Only the running stack answers; that's the
whole point of the toggle.

## Switching

```bash
cd ~/ProveKit
./deploy/switch.sh provekit    # stop cere, start ProveKit  → provekit.online live
./deploy/switch.sh cere        # stop ProveKit, start cere  → cerebrozen.in live
./deploy/switch.sh status      # what's running
./deploy/switch.sh down        # stop both
```

(If the repos aren't in `$HOME`, set paths: `CERE_DIR=/srv/cere PROVEKIT_DIR=/srv/ProveKit ./deploy/switch.sh provekit`.)

The first `provekit` switch builds the images and, because DNS + 80/443 are ready, Caddy
auto-issues the Let's Encrypt cert for `provekit.online` — no manual certs, and it fixes the
old bad-cert error.

## Notes

- **While one is up, the other domain is down** (by design). Requests to the stopped app's
  domain hit the running app's Caddy, which has no site block for it → no valid response. That's
  expected for a one-at-a-time toggle.
- **8 GB VPS**: both stacks would actually fit at once — if you later want them both live
  simultaneously (each on its own domain, no toggling), use `compose.contabo.yml` + the shared
  Caddy block instead (see `docs/DEPLOY_CONTABO_SHARED.md`).
- **Secrets** live only in `deploy/provekit.online.env` (gitignored). Never committed.
- **Email**: the current Titan password fails auth (535) — fix it in the panel before relying
  on password-reset / verification mail.

## Validate after a switch to ProveKit

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://provekit.online/          # 200/307
curl -sS https://provekit.online/api/auth/me                                # JSON, not HTML 404
curl -sS -o /dev/null -w "%{http_code}\n" https://provekit.online/healthz   # 200
```

Then in a browser: valid padlock, sign up, create a project, and confirm a live SDK trace
(`PROVEKIT_ENDPOINT=https://provekit.online`) appears in the portal.
