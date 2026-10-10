# Day one: from an empty server to a school that can sign in

For the founder, on Windows, using PowerShell. The server is a fresh Contabo VPS
running Ubuntu 24.04 at **169.58.181.9**. You do not need to understand the
commands: copy each block, run it where the step says, and check the
**Confirm** line before moving on. Every step that changes something has an
**Undo**.

Plan on most of a day. Parts 1 to 3 are about two hours, the first deploy and
the first school about an hour, and the backup and restore drill another two.
You can stop between any two steps and come back: the steps say what is safe to
leave half done.

**Status: written, not yet run on the real server.** The commands come from this
repository's own files, and `deploy/bootstrap.sh` and `deploy/init-env.sh` were run
here against a stand-in server (twice each, to prove a re-run changes nothing).
Nothing in this file has run on Contabo, in Docker, against Cloudflare, GitHub's
package registry or Backblaze. If a step is wrong when you do it, stop, and fix
this file in the same change that fixes the step.

## How to read this

| it looks like | where you are |
|---|---|
| `PS C:\Users\you>` | **your PC**, in PowerShell |
| `root@vmi123456:~#` | **the server**, logged in as `root` (the all-powerful account) |
| `deploy@vmi123456:~$` | **the server**, as `deploy` (the account that runs the app) |

Two windows are better than one from step 7 on. Open PowerShell from the Start
menu; to open a second one, do it again.

**Where a secret may go.** A secret is a password, a key or a token. Rules for the
whole day:

- A secret goes into a **file on the server**, typed or pasted in the `nano`
  editor. Not into a command (commands are saved in history and visible in process
  lists), not into a chat, an email, a ticket or a message to anyone, and never to me.
- The generated ones (the database password, the app's secret key, the backup
  key) are made on the server and never shown unless you open the file.
- **One exception, by necessity:** the deploy key's private half (step 13) is pasted
  into GitHub's own secret box, because that is where GitHub Actions reads it from.
  Nothing else leaves the server or your PC.
- One more thing is typed at a hidden prompt on the server rather than put in a
  file: your own platform-operator password (step 19). It is stored only as a hash.
- Keep every secret in your password manager as well. A secret that exists only on
  the server is lost with it.

**Using `nano`.** Open a file with `nano /path`. Move with the arrow keys. To paste,
right-click (or `Ctrl+Shift+V` in Windows Terminal). Save with `Ctrl+O` then
`Enter`; leave with `Ctrl+X`.

**What you need before you start**

- The Contabo email or panel with the server's **root password**.
- Your password manager, open.
- The `classnode.co` domain, with its DNS on Cloudflare, and your Cloudflare login.
- Admin rights on the GitHub repository `adedejimakinde/luffy-school-saas`
  (Settings must be visible to you).
- A Backblaze account for step 23 (the backups). You can do steps 1 to 22 without it.

---

# Part 1: Your PC, and getting in

## 1. Check that Windows can do SSH

**What it does.** SSH is how your PC talks to the server. Windows 10 and 11 include it.

```powershell
ssh -V
```

**Confirm.** It prints a line starting `OpenSSH_`. If PowerShell says `ssh` is not
recognised: Settings, Apps, Optional features, Add a feature, **OpenSSH Client**,
install, then close and reopen PowerShell.

**Undo.** Nothing changed.

## 2. Make your two keys

**What it does.** A key is a pair of files: a **public** one (ends in `.pub`, safe
to share) and a **private** one (no `.pub`, never shared). You make two pairs:

- **Your own key**, to log in to the server. Give it a passphrase: a password for
  the key file, so a stolen laptop is not a stolen server.
- **The deploy key**, which GitHub Actions uses to deploy. It has **no passphrase**,
  because no one is there to type it.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519" -C "classnode-admin"
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\classnode_deploy" -C "classnode-github-actions"
```

For the first, type a passphrase twice (nothing shows as you type). For the
second, press **Enter** twice for no passphrase. If it says `id_ed25519 already
exists` you already have a key: answer `n` and carry on with the one you have.

**Confirm.**

```powershell
Get-ChildItem "$env:USERPROFILE\.ssh\*.pub"
```

shows `id_ed25519.pub` and `classnode_deploy.pub`.

**Undo.** Delete the files you made (`Remove-Item "$env:USERPROFILE\.ssh\classnode_deploy*"`).
Nothing else knows about them yet.

## 3. Rehearse the emergency door (before you need it)

**What it does.** If you ever lock yourself out (see the last section), your only
way back in is Contabo's **VNC console**, a screen and keyboard over the internet.
Contabo's VNC works only through a VNC program installed on your PC; it is not
a window inside their website. Find out now that you can reach it, not at midnight.

1. Install a VNC viewer: [TigerVNC](https://tigervnc.org/) or RealVNC Viewer.
2. In Contabo's Customer Control Panel, find your VPS and its **VNC** details
   (Contabo's guide: [How to connect to your server using VNC](https://help.contabo.com/en/support/solutions/articles/103000407800-how-to-connect-to-your-server-using-vnc)).
   It gives an address, a port and a VNC password, which is separate from the root
   password. Save all of it in your password manager.
3. Connect, and look at the screen.

**Confirm.** You see a text login prompt ending `login:`. You do not need to log
in. Contabo's own pages are the authority on the exact buttons, which change.

**Undo.** Nothing changed on the server. If you cannot get VNC working, **do not
do step 8** until you can.

## 4. First login, as root

**What it does.** Logs in with the password Contabo gave you, to look around
before changing anything.

```powershell
ssh root@169.58.181.9
```

The first time, it shows a fingerprint and asks `Are you sure you want to continue
connecting?` Type `yes`. It records this server so that, if anything ever
impersonates it, you get a loud warning instead. Then type the root password; **nothing
shows while you type**; press Enter.

**Confirm.** The prompt changes to `root@vmi...:~#`. Then:

```bash
lsb_release -d
```

prints `Ubuntu 24.04`. Then leave: `exit`.

**Undo.** Nothing changed. `Permission denied`: re-type slowly, or reset the root
password in the Contabo panel ([how](https://help.contabo.com/en/support/solutions/articles/103000286845-how-do-i-reset-my-server-password-)).

## 5. Send the two public keys to the server

**What it does.** Copies the two `.pub` files (public, safe to send) onto the
server so the bootstrap script can install them. It asks for the root password
each time. **Copy the files ending `.pub` only**, as written.

```powershell
scp "$env:USERPROFILE\.ssh\id_ed25519.pub" root@169.58.181.9:/root/admin_key.pub
scp "$env:USERPROFILE\.ssh\classnode_deploy.pub" root@169.58.181.9:/root/deploy_key.pub
```

**Confirm.** Each prints a line ending `100%`.

**Undo.** `ssh root@169.58.181.9 "rm /root/admin_key.pub /root/deploy_key.pub"`.

---

# Part 2: Make the server safe

## 6. Run the bootstrap script

**What it does.** One script, `deploy/bootstrap.sh`, that sets the server up and can
be run again whenever you like without harm:

- updates everything;
- turns on a firewall that lets in only ports **22** (you), **80** and **443**
  (the website);
- installs **fail2ban**, which bans an address for an hour after five wrong logins;
- turns on **automatic security updates**, rebooting at 03:30 UTC (04:30 in Lagos)
  when one needs it;
- installs **Docker**, with its logs capped so they cannot fill the disk;
- creates the **deploy** user, which only the GitHub Actions key can log in as;
- installs your own key for root;
- copies the project to `/opt/classnode`.

It does **not** turn off password login. That is step 8, after you have proved the
key works.

On the server (`ssh root@169.58.181.9`), then:

```bash
curl -fsSL -o /root/bootstrap.sh https://raw.githubusercontent.com/adedejimakinde/luffy-school-saas/main/deploy/bootstrap.sh
bash /root/bootstrap.sh
```

It takes five to ten minutes and prints a `==>` heading for each stage.

**Confirm.** It ends with `==> Done`. If it says **STOPPED**, it says why: either
a sentence, or the line number, the command that failed and its exit code
(`STOPPED at line 164: the command  ...  failed with exit code 1.`). Send that
line to whoever is helping you. Nothing it did before that is harmed by running
the same command again. Then:

```bash
ufw status verbose        # Status: active; only 22/tcp, 80/tcp, 443/tcp, 443/udp allowed
systemctl is-active fail2ban unattended-upgrades docker     # three lines: active
docker --version
id deploy                  # ... groups=...,docker
```

If it says the server wants a reboot, run `reboot`, wait two minutes, and log in
again with `ssh root@169.58.181.9` (the password is still how you log in until step 8).

**Undo.** The script only adds. To take pieces back off:
`ufw disable` (firewall off), `systemctl disable --now fail2ban`,
`rm /etc/apt/apt.conf.d/52classnode-unattended` (no automatic reboot; security
updates still install), `deluser --remove-home deploy` (the deploy user). Docker
and the updates stay; you would not want them gone.

## 7. Prove your key works, in a second window

**What it does.** Before passwords are turned off, check the other door opens. If it
does not, you find out while the first door is still open.

**Keep the window from step 6 open.** Open a **second** PowerShell window and run:

```powershell
ssh root@169.58.181.9
```

**Confirm, part 1.** You get in **without being asked for the server's password**.
(A prompt `Enter passphrase for key ...` is fine: that is your key's passphrase from
step 2, not the server's password.) The prompt shows `root@vmi...:~#`. If it asks for
`root@169.58.181.9's password:` instead, the key did not work. **Stop here** and do
not do step 8; the first window is still open to fix it from.

**Confirm, part 2: the deploy key.** In the second window, `exit`, and then run:

```powershell
ssh -i "$env:USERPROFILE\.ssh\classnode_deploy" deploy@169.58.181.9 "docker ps"
```

It prints a table heading `CONTAINER ID   IMAGE ...` and nothing under it. That proves the
deploy key logs in as `deploy` and that `deploy` can run Docker, which is exactly
what GitHub will do.

**Undo.** Nothing changed.

## 8. ⚠ Turn off password login

**What it does.** Anyone on the internet can try passwords against your server all
day. With this on, only keys work, so passwords stop mattering. It is the one step
that can lock you out, which is why it is separate, and why steps 3 and 7 come first.

In the **first** window (the one still logged in on the server):

```bash
/opt/classnode/deploy/bootstrap.sh --lock-ssh
```

It asks whether you did step 7. Type `yes` only if you did. It then asks sshd
itself whether passwords are now off, and takes the change back by itself if
not. Your open windows stay open.

**Confirm.** In a **new** third window:

```powershell
ssh -o PubkeyAuthentication=no root@169.58.181.9
```

must say `Permission denied (publickey).` And a normal `ssh root@169.58.181.9`
must still log in. Only now close the other windows.

**Undo.** In any logged-in window: `/opt/classnode/deploy/bootstrap.sh --unlock-ssh`.
If you cannot log in at all: the last section.

---

# Part 3: Connect the accounts

## 9. DNS: point the domain at the server

**What it does.** Tells the internet that `classnode.co` and every name under it is
this server. The wildcard `*` means a new school needs no DNS work.

In Cloudflare, domain `classnode.co`, DNS, Records, add three:

| type | name | content | proxy status |
|---|---|---|---|
| A | `@` | `169.58.181.9` | **DNS only** (grey cloud) |
| A | `app` | `169.58.181.9` | **DNS only** |
| A | `*` | `169.58.181.9` | **DNS only** |

The cloud must be **grey**. Caddy holds the certificate itself, and an orange cloud
puts Cloudflare's in front of it and breaks the setup.

**Confirm.**

```powershell
Resolve-DnsName app.classnode.co -Type A
Resolve-DnsName anything.classnode.co -Type A
```

Both show `169.58.181.9`. A new record can take a few minutes.

**Undo.** Delete the records.

## 10. Cloudflare: the token for certificates

**What it does.** To prove to Let's Encrypt that you own the domain, Caddy writes a
temporary DNS record. It needs a key that can do that and nothing else.

Cloudflare, your profile, API Tokens, Create Token, **Create Custom Token**:

- Permissions: **Zone, DNS, Edit** and **Zone, Zone, Read**.
- Zone Resources: **Include, Specific zone, `classnode.co`**.
- Nothing else. Create it, and **leave the page open**: Cloudflare shows the token
  once. Step 11 puts it into a file on the server, straight from this page. Do not
  paste it anywhere else.

**Confirm.** The page shows a token and a green "This token is active". Keep it open.

**Undo.** Delete the token in the same place; make another.

## 11. ⚠ Create secrets.env and caddy.env

**What it does.** The app's passwords live in two files in `/etc/classnode`, which
only `root` and `deploy` can read. `init-env.sh` makes them from the templates in
`deploy/env/`, writing a random database password and secret key into
`secrets.env` without showing them to you. It **never touches a file that already
exists**, so running it again is harmless.

On the server as root:

```bash
/opt/classnode/deploy/init-env.sh
```

It prints `secrets.env: created` and `caddy.env: created`. Now the part that is yours,
the Cloudflare token and an email address:

```bash
nano /etc/classnode/caddy.env
```

Replace `CHANGE_ME` after `CLOUDFLARE_API_TOKEN=` with the token from step 10 (paste
it), and after `ACME_EMAIL=` with an address you read. Save and leave.

Then **open `secrets.env` once and copy the generated values to your password
manager**: `nano /etc/classnode/secrets.env`, select the `DJANGO_SECRET_KEY` and
`POSTGRES_PASSWORD` values with the mouse, copy, paste each into a new password
manager entry called "Classnode server secrets". Leave nano with `Ctrl+X`. Don't change anything in it.

**Confirm.**

```bash
/opt/classnode/deploy/init-env.sh --check
```

prints `All the files that exist are ready.` It prints names, never values, and tells you if a
placeholder is left, a permission is wrong, or the Cloudflare token does not look
like a token (the Global API Key is the common mistake).

**Undo.** ⚠ **Only before step 15.** Until the first deploy you can `rm
/etc/classnode/secrets.env` and run `init-env.sh` again for a fresh one. **After the
first deploy, never delete or regenerate `secrets.env`**: the database is created with
the password in it and will not accept a different one. If it is ever lost, put back
the copy from your password manager. `caddy.env` can be edited any time.

## 12. Let the server pull our images

**What it does.** The app is built by GitHub and stored in GitHub's registry. A
read-only token lets the `deploy` user download it. You do this once.

1. On GitHub, signed in as someone who can read the repository: Settings, Developer
   settings, Personal access tokens, **Tokens (classic)**, Generate new token (classic).
2. Tick **`read:packages` and nothing else.** Give it an expiry and put the date in
   your calendar: when it lapses, every deploy fails with `denied`.
3. Copy it, and on the server (as root) put it in a file, paste, save:

   ```bash
   install -m 600 -o deploy -g deploy /dev/null /home/deploy/ghcr-token
   nano /home/deploy/ghcr-token
   ```

4. Log in with it as `deploy`, then destroy the file (replace `YOUR-GITHUB-USERNAME`):

   ```bash
   su - deploy -c 'docker login ghcr.io -u YOUR-GITHUB-USERNAME --password-stdin < /home/deploy/ghcr-token'
   shred -u /home/deploy/ghcr-token
   ```

**Confirm.** It prints `Login Succeeded`, and `ls /home/deploy/ghcr-token` says no such file.

**Undo.** `su - deploy -c 'docker logout ghcr.io'`, and delete the token on GitHub.
Docker keeps the login in `/home/deploy/.docker/config.json`; use this token for nothing else.

## 13. Give GitHub the deploy key and the server's address

**What it does.** The **deploy** button on GitHub needs to know where the server is,
how to log in, and which server it is meant to be talking to.

First, the server's identity, which is public. On the server:

```bash
echo "169.58.181.9 $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
```

It prints one line starting `169.58.181.9 ssh-ed25519 AAAA...`. Copy that whole line.

On GitHub, repository, Settings, **Environments**, New environment, name it
`production`, no other settings. Then Settings, Secrets and variables, Actions,
**New repository secret**, three times:

| name | value |
|---|---|
| `DEPLOY_HOST` | `169.58.181.9` |
| `DEPLOY_KNOWN_HOSTS` | the line you just copied |
| `DEPLOY_SSH_KEY` | the **private** deploy key, below |

For the third, on your PC, copy the key to the clipboard without showing it, paste
it into the secret's box on GitHub, then wipe the clipboard:

```powershell
Get-Content "$env:USERPROFILE\.ssh\classnode_deploy" -Raw | Set-Clipboard
# paste into GitHub's box now, then:
Set-Clipboard -Value " "
```

This is the one secret that goes into a website, as the rules at the top said.
GitHub never shows it again. Keep the key file on your PC until step 16 has worked.

**Confirm.** The Secrets page lists `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS` and
`DEPLOY_SSH_KEY`, and Environments lists `production`.

**Undo.** Delete the secrets. To change the key later: make a new pair as in step 2,
`scp` the new `.pub` to `/root/deploy_key.pub`, run `bash /opt/classnode/deploy/bootstrap.sh`
(it replaces the old key), and update `DEPLOY_SSH_KEY`.

---

# Part 4: The first deploy

## 14. Choose what to deploy

**What it does.** A deploy runs one exact commit, named by its full 40-character
SHA, and only one on `main` where CI has passed. The images are built for that
commit and nothing else.

On GitHub, repository, **Commits** (branch `main`). Find the newest commit with a
**green tick** (every check passed, including the one that publishes the
images). Click the small copy icon beside it: that copies the full SHA.

**Confirm.** The pasted SHA is 40 letters and digits, with no spaces.
Click the green tick on that commit: `publish` is in the list.

**Undo.** Nothing changed. A commit without a tick is not ready: choose the one before.

## 15. ⚠ Deploy by hand, once

**What it does.** Downloads that commit's images, creates the database, applies its
tables, starts the website, and checks it answers: first inside the server, then
over HTTPS from outside. The first time, Caddy also has to get the certificate, so
it can take longer.

On the server, as root, become `deploy` (the prompt changes to `deploy@...$`):

```bash
su - deploy
```

Then, with your SHA in place of `YOUR-40-CHARACTER-SHA` (twice). This is the one
time you move the server's copy to the release by hand; from step 16 on, the
deploy button does it:

```bash
cd /opt/classnode && git fetch origin && git checkout YOUR-40-CHARACTER-SHA
/opt/classnode/deploy/deploy.sh YOUR-40-CHARACTER-SHA
```

**Confirm.** The last line is `DEPLOYED <your sha>`. Then:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://classnode.co/healthz/     # 200
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha) && docker compose ps
ss -tulnH | awk '{print $1, $5}' | sort -u
```

`docker compose ps` lists `caddy`, `web`, `worker`, `db`, `redis` all `Up`. The last
command lists what is listening: only **22, 80, 443** (and local-only addresses
starting `127.`). Anything else is wrong: stop and ask. In a browser,
`https://classnode.co/` shows the Classnode page with a padlock.

**If it says `NOT HEALTHY`** the first time: look at `docker compose logs caddy`
(with the `export` line above). If it says it is still obtaining a certificate, wait
until you see `certificate obtained`, then run the same `deploy.sh` command again.
An error mentioning `403` or `zone` means the Cloudflare token or zone (steps 9, 10); `no such
host` means the `*` record. Let's Encrypt limits repeated failures, so fix the cause
before retrying in a loop. `denied` on the pull is step 12; `manifest unknown` is a SHA
whose images are not published (step 14).

**Undo.** A later deploy that fails health checks puts the previous images back by
itself (the first has nothing to go back to). To stop everything and keep the data:
`docker compose down` (**never** add `-v`; that deletes the certificate). Database
changes are not undone by a rollback; on day one the database is empty, so if you
want to start again from nothing: `docker compose down`, `rm -rf /srv/classnode/postgres
/srv/classnode/redis` (as root; recreate both empty directories), `deploy.sh` again.
Never do that once a real school exists.

## 16. Press the deploy button once

**What it does.** Proves the button works, while no school is waiting on it.

GitHub, **Actions**, **deploy** (left list), **Run workflow**, paste the **same**
SHA, Run. If you set reviewers on `production`, approve. It checks the SHA is on
`main` and passed CI, logs in with the deploy key, moves the server's copy of the
project to that exact SHA (`git fetch`, then `git checkout`, so the deploy files
are the release's own and not an older commit's), and runs `deploy.sh` from it.
Redeploying the same commit changes nothing. This is how every later release goes;
the by-hand `git checkout` in step 15 was needed only because the button did not
exist yet.

**Confirm.** The run goes green. Its step "Check out the SHA on the server" prints
`Server checkout is at <your sha>`, and its last step prints `DEPLOYED <sha>`. Now you
may delete the key file from your PC (GitHub has its copy):
`Remove-Item "$env:USERPROFILE\.ssh\classnode_deploy"` (keep the `.pub` if you wish).

**Undo.** Nothing changed. If it fails at "Check out the SHA on the server", the log
says why: usually someone edited a file in `/opt/classnode` by hand, and the button
refuses to deploy over it (look with `su - deploy -c 'git -C /opt/classnode status'`).
If it fails at "Deploy over SSH", the cause is one of the three secrets or step 7's
test; fix and run again. A deploy that fails puts the server's copy back on the
commit that is still running, so the files always match what is serving.

Deploy outside school hours: the website restarts for a few seconds.

## 17. Switch on the nightly jobs

**What it does.** Installs the schedule: clearing dead login sessions, releasing held
messages at 07:00 Lagos, the daily money summary, the nightly backup and the weekly
restore test. As root:

```bash
install -m 644 -o root -g root /opt/classnode/deploy/cron/classnode /etc/cron.d/classnode
```

**Confirm.** `ls -l /etc/cron.d/classnode` shows `-rw-r--r-- 1 root root`. Until step
26 the backup lines fail and write that to `/var/log/classnode-backup.log`. That is
by design (there is nowhere to back up to yet), not a fault. After 01:15 UTC the next
day, `cat /var/log/classnode-housekeeping.log` shows no errors.

**Undo.** `rm /etc/cron.d/classnode`.

---

# Part 5: Operator and first school

Run these as `deploy`, in `/opt/classnode/deploy`, with the tag set. Become
`deploy` with `su - deploy` (from root), then set the tag. Every new login needs the
second line again (`docker compose` says `set CLASSNODE_TAG` when it is missing):

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
```

## 18. Create the portal

**What it does.** The portal is the front door, `app.classnode.co`, where staff sign in.

```bash
docker compose run --rm web python manage.py setup_portal
```

**Confirm.** It prints `The portal answers on https://app.classnode.co/`; open
that address in a browser. Running it again is safe.

**Undo.** Nothing to undo; it is safe to repeat.

## 19. Create yourself as the platform operator

**What it does.** Makes the account that creates schools and sees across them. A
school's own administrator never has this power.

```bash
docker compose run --rm web python manage.py createsuperuser
```

It asks for a username (lowercase, no spaces; you will use it in step 20), your full
name, and a password twice, typed at a **hidden prompt on the server**. Make it long
and unique, from your password manager. It is stored only as a hash.

**Confirm.** It ends `Superuser created successfully.` In a browser, sign in at
`https://app.classnode.co/staff-sign-in/` and open `https://app.classnode.co/platform/`.

**Undo.** Not removable from here; if you mistyped the name, make another account
and stop using the first.

## 20. ⚠ Create the first school

**What it does.** Builds the school's private area of the database, gives it the
address `<slug>.classnode.co`, and invites its first administrator. **There is no
command to remove a school**, so spell it right: the slug is lowercase letters,
digits and hyphens (`stmarys`), with no dots, and not one of `app`, `www`,
`api`, `admin`, `mail`, `static`, `portal` or `public`.

```bash
docker compose run --rm web python manage.py create_school stmarys "St Mary's Secondary School" --admin-email principal@example.com --operator YOUR-USERNAME
```

Use the real slug, name and the administrator's email, and your username from step 19.

**No email provider exists yet, so nothing is emailed.** The command prints a
**link**. Whoever opens it becomes that school's administrator, so it is a
credential: send it **only to that one person**, directly (not to a group, not to me,
not by pasting it into a document). It stops working at the time printed. Then
close the terminal window, so it is not left on screen.

**Confirm.** It prints `... answers on https://stmarys.classnode.co/`. That address
shows the school's public page. The administrator opens the link, sets a password,
and signs in at `https://app.classnode.co/staff-sign-in/`.

**Undo.** ⚠ If you got the slug wrong **on day one, with no real data anywhere**,
the clean start is step 15's "start again from nothing". Once a school has real
children's data, you do not undo it from here: ask a developer, because removing a
school's database area is deliberate surgery.

---

# Part 6: The uptime monitor

## 21. Create the monitor

**What it does.** Asks your website "are you alive?" every few minutes from outside
and tells you when it says no. Without it you learn from a parent's phone call.

Use any uptime service (Better Stack, UptimeRobot or similar: check the free plan's
current limits and that it allows commercial use; I have not). Create an **HTTP(S)**
monitor with:

- URL: `https://classnode.co/healthz/`
- Method GET, expects status **200** (and, if offered, the text `ok`)
- Check every **5 minutes or faster**
- Alerts to **two people** by email and by a phone alert (push, SMS or a call) so one
  lost phone is not silence
- Alert on **certificate expiry** too, if offered

`/healthz/` answers 200 when the web app can reach the database and 503 when it
cannot. It does **not** see Redis or the background worker.

**Confirm.** The monitor shows **Up** after its first check.

**Undo.** Pause or delete the monitor.

## 22. Prove the alarm rings

**What it does.** An alarm you have never heard is a guess. Switch the website off
for a few minutes **on day one, while no school depends on it**, and see the alert arrive.

```bash
docker compose stop web
```

Wait for the alert on both people's phones, which can take as long as the check
interval plus a minute or two. Then:

```bash
docker compose start web
```

**Confirm.** The alert arrives, then a recovery notice, and
`curl -sS https://classnode.co/healthz/` prints `ok`.

**Undo.** `docker compose start web` is the undo. If `web` will not start,
`/opt/classnode/deploy/deploy.sh $(cat /opt/classnode/deploy/deployed-sha)` brings
everything back.

---

# Part 7: Backups, and the timed restore drill

Backups matter once there are real children's records. A backup you have never
restored is a hope, so this part ends with two timed restores.

## 23. A Backblaze B2 bucket and a key limited to it

**What it does.** Creates the off-server place the backups go.

In Backblaze B2: create a **private** bucket (any unique name). Then Application Keys,
Add a New Application Key, **limited to that one bucket**, read and write. Leave the
page open; the key is shown once. Note the bucket's **endpoint** (it looks like
`s3.us-west-004.backblazeb2.com`) and its region (`us-west-004`).

**Confirm.** You have: the bucket name, a key ID, the key, the endpoint, the region.
**Undo.** Delete the key or the bucket in the same place.

## 24. ⚠ Create backup.env

**What it does.** Same idea as step 11. Run it only now, with your B2 details to hand:
while `WALG_S3_PREFIX` is set the database archives to B2, so a half-filled file would
make it fail repeatedly. The backup encryption key is generated for you.

On the server, as root:

```bash
/opt/classnode/deploy/init-env.sh backup
nano /etc/classnode/backup.env
```

Replace every `CHANGE_ME`: `WALG_S3_PREFIX=s3://YOUR-BUCKET/classnode`; the key ID
and the key from step 23; `AWS_ENDPOINT=https://s3.us-west-004.backblazeb2.com`
(with your region); `AWS_REGION=us-west-004`. If you have no Sentry check-in URL,
leave the last line commented. **Copy `WALG_LIBSODIUM_KEY` to your password manager now.**
The backups are encrypted with it. Without it they are unreadable noise, and
this key exists nowhere else.

**Confirm.** `/opt/classnode/deploy/init-env.sh --check` prints `All the files that exist are ready.`

**Undo.** Nothing is using the file yet: `rm /etc/classnode/backup.env`. **Once step
25 has run, do not regenerate this key**; old backups would become unreadable.

## 25. ⚠ Switch backups on

**What it does.** Restarts the database container so it starts sending its change log
to B2 (a few seconds of downtime: do it after school hours).

As `deploy` with the tag set:

```bash
docker compose up -d --force-recreate db
docker compose logs db | grep classnode-postgres
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT archived_count, failed_count, last_failed_time FROM pg_stat_archiver"'
```

**Confirm.** The log says `archiving WAL to s3://...`. After a minute, run the last
command again: `archived_count` is above 0 and `failed_count` is 0. If `failed_count`
climbs, the B2 details are wrong (look at `docker compose logs db`). Fix `backup.env` and
repeat step 25. A failing archive piles up files on the server's disk, so don't leave
it failing: `df -h /` shows free space.

**Undo.** Remove or empty the B2 lines (`rm /etc/classnode/backup.env`), then
`docker compose up -d --force-recreate db`. The log then says `WAL is NOT being archived`.

## 26. Take the first backup

**What it does.** A full copy now, on top of the continuous change log. The cron job
does this every night at 00:30 UTC; this proves it works.

```bash
docker compose exec -T db classnode-backup
docker compose exec -T db wal-g backup-list
```

**Confirm.** The first ends `classnode-backup: done`. The second lists one backup. In
the Backblaze website the bucket now has files under `classnode/`.

**Undo.** Backups only add. Delete them in Backblaze if you must.

## 27. Drill A: the weekly restore test, timed

**What it does.** The check that runs every Sunday on its own. It counts one school's
records on the live database, recovers the **latest backup** from B2 into a throwaway
database, and requires that it holds the same records and every school and migration.
The live database is not touched. This needs at least one school (step 20).

As **root**, with a stopwatch (phone is fine), start it when you press Enter:

```bash
time /opt/classnode/deploy/restore-check.sh
```

**Confirm.** It prints `The restore is whole`, with the school's row counts, and
`time` prints how long it took. **Write the time down.**

**Undo.** The script removes its own throwaway database even when it fails. If a run
was cut off, clean up with: `cd /opt/classnode/deploy && export
CLASSNODE_TAG=$(cat deployed-sha) && docker compose --profile restore rm -sfv
restore-db && docker volume rm classnode_restore-data`. Never use `down -v`.

## 28. ⚠ Drill B: a full restore, timed

**What it does.** Drill A proves a backup can be read. This proves **you** can bring
the real database back, and how long it takes: the recovery time you can promise a
school. It moves the live database aside, restores the latest backup in its place, and
checks it. **Do it on day one, while the database holds nothing real.** The
old database is kept beside it, so the way back is a rename.

As root. Start the stopwatch, then:

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
START=$(date +%s)
docker compose stop web worker caddy db
mv /srv/classnode/postgres /srv/classnode/postgres.old
install -d -m 700 -o 999 -g 999 /srv/classnode/postgres
docker compose run --rm --no-deps --entrypoint sh db -c "
  gosu postgres wal-g backup-fetch \"\$PGDATA\" LATEST &&
  gosu postgres touch \"\$PGDATA/recovery.signal\" &&
  echo \"restore_command = 'wal-g wal-fetch %f %p'\" >> \"\$PGDATA/postgresql.auto.conf\" &&
  echo \"recovery_target_action = 'promote'\" >> \"\$PGDATA/postgresql.auto.conf\""
docker compose up -d db
docker compose exec -T db sh -c 'until [ "$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT NOT pg_is_in_recovery()")" = t ]; do sleep 5; done'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER SYSTEM RESET restore_command" -c "ALTER SYSTEM RESET recovery_target_action"'
docker compose run --rm --no-deps web python manage.py verify_restore
docker compose up -d web worker caddy
echo "The whole restore took $(( $(date +%s) - START )) seconds"
```

Keep the window open until it finishes. The website is down while it runs.

**Confirm.** `verify_restore` prints `The restore is whole`, and the last line prints the
time. Then `curl -sS https://classnode.co/healthz/` prints `ok`, and the school's
page and your platform-operator sign-in still work. **Write the time down.**

Then take a fresh base backup, because the restore starts a new timeline:
`docker compose exec -T db classnode-backup`. Delete `/srv/classnode/postgres.old`
only when you are satisfied (`rm -rf /srv/classnode/postgres.old`).

**Undo.** If anything fails, put the old database back:

```bash
docker compose stop web worker caddy db
rm -rf /srv/classnode/postgres
mv /srv/classnode/postgres.old /srv/classnode/postgres
docker compose up -d db web worker caddy
```

**What this does and doesn't prove.** It proves the backup, the key and the commands
on **this** server. It does not prove rebuilding from nothing, which is the real
disaster: `docs/deployment.md` asks for one timed restore onto a **fresh server**
before real children's data. That is this file again from step 4 on a
wiped server (Contabo's panel can reinstall Ubuntu on this VPS; the host-key warning
that follows is cured by `ssh-keygen -R 169.58.181.9`), with the `backup.env` and
`secrets.env` values from your password manager, in place of steps 11 and 24, and
then step 28. Run the stopwatch from the reinstall. Do that before launch.

## 29. Write down the result

Record, somewhere permanent: today's date, Drill A's time, Drill B's time, who ran
them. Send the two numbers to whoever maintains `docs/handover.md`, so they go in the
repository. A school asking "how long if the server dies?" gets that number plus the
time to reinstall and bootstrap.

**Undo.** Nothing changed on the server.

---

# If you locked yourself out

The usual causes: password login turned off (step 8) before your key worked; the
firewall; fail2ban banning you after typed-wrong attempts (your address is banned
for an hour; it lifts by itself). The way back in does not use the network, so none
of them can stop it: **Contabo's VNC console.**

1. Open your VNC viewer (step 3) and connect with the address, port and VNC password
   from the Contabo panel. VNC password problems:
   [Contabo's article](https://help.contabo.com/en/support/solutions/articles/103000270404-why-am-i-getting-an-incorrect-password-error-when-logging-into-my-server-via-vnc-).
   If VNC is off, switch it on in the panel, and reboot the server if it asks you to.
2. At `login:` type `root`, then the **root password** (nothing shows as you type; the
   VNC keyboard may be a US layout, so symbols can land on different keys). Lost it:
   reset it in the panel ([how](https://help.contabo.com/en/support/solutions/articles/103000286845-how-do-i-reset-my-server-password-)).
3. Then fix whichever it was:

| what happened | fix, typed in the VNC window |
|---|---|
| Passwords off and your key is lost or not working | `/opt/classnode/deploy/bootstrap.sh --unlock-ssh`. If that file is missing: `rm /etc/ssh/sshd_config.d/00-classnode.conf && systemctl reload ssh`. Then log in with the password from PowerShell and redo step 2 and 5 |
| Your key is not in root's list | `nano /root/.ssh/authorized_keys`; paste a line from your `id_ed25519.pub` on its own line |
| fail2ban banned you | `fail2ban-client set sshd unbanip YOUR-HOME-IP` (find the address by searching "what is my IP"), or wait an hour |
| The firewall blocks SSH | `ufw allow 22/tcp` (and if that is not it, `ufw disable` while you look; then `bash /opt/classnode/deploy/bootstrap.sh` turns it back on) |
| `Host key has changed` warning in PowerShell (after a reinstall) | `ssh-keygen -R 169.58.181.9` on your PC, then log in again |

4. Log out of VNC (`exit`), and test the normal login from PowerShell before
   relying on it.

A server nobody can get into at all can always be reinstalled from Contabo's panel;
the data in `/srv/classnode` goes with it, which is what the backups (Part 7) are for.

---

# Where things are, afterwards

| what | where |
|---|---|
| The app's secrets | `/etc/classnode/secrets.env` (root:deploy, mode 640) and your password manager |
| Cloudflare token | `/etc/classnode/caddy.env` |
| Backup details and key | `/etc/classnode/backup.env` and your password manager |
| The project and the deploy scripts | `/opt/classnode/deploy/` |
| The database and Redis | `/srv/classnode/postgres`, `/srv/classnode/redis` |
| Which commit is running | `/opt/classnode/deploy/deployed-sha` |
| Nightly job logs | `/var/log/classnode-*.log` |
| Re-run the server setup | `bash /opt/classnode/deploy/bootstrap.sh` (safe at any time) |
| The wider runbook | `docs/deployment.md`; the demo server's variant, `docs/demo-server.md` |

Not covered here, and still yours before real children's data: the lawyer's TODOs
on the privacy notice and terms, your confirmation on data residency, an email
provider (until then `create_school` prints the invitation link), Sentry, and raising
HSTS from a day to a year after a certificate renewal has been seen
(`docs/handover.md`, "Only you").
