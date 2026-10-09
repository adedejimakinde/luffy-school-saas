#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 VPS to run Classnode. Run as root, on the server:
#
#   bootstrap.sh                   everything below except the SSH lock
#   bootstrap.sh --lock-ssh        turn password login off (key login only)
#   bootstrap.sh --unlock-ssh      turn it back on (the way out of --lock-ssh)
#
# **Safe to re-run.** Every step asks "is it already so?" first, so a second run
# (after a failure, or to pick up a newer version of this file) changes nothing
# that is already right. docs/first-day.md is the walkthrough.
#
# What a plain run does, in order:
#  1. Refuses anything but Ubuntu 24.04 with sshd on port 22 — the firewall
#     below only lets in 22, and a firewall that blocks the port you are logged
#     in on is the classic way to lock yourself out.
#  2. Reads the two public keys it was given (below) before changing anything.
#  3. apt update and upgrade.
#  4. ufw: deny everything in, allow 22/tcp, 80/tcp, 443/tcp and 443/udp (HTTP/3).
#     Docker publishes ports around ufw; only 80 and 443 are published
#     (deploy/compose.yml), so that is fine. Never publish another port there.
#  5. fail2ban on sshd: five wrong tries in ten minutes is an hour's ban.
#  6. unattended-upgrades: security updates install themselves, and the server
#     reboots at 03:30 UTC (04:30 Lagos) when one needs it. Containers come
#     back by themselves (`restart: unless-stopped`).
#  7. Docker Engine and the compose plugin from Docker's own apt repository,
#     with its logs capped so they cannot fill the disk.
#  8. The `deploy` user: in the docker group, no password, and logged in to only
#     by the GitHub Actions key. deploy.yml signs in as this user.
#  9. The directories the compose file expects, and the clone of the repository
#     at /opt/classnode (docs/deployment.md, "One layout on the server").
#
# The two keys are PUBLIC keys (not secrets), copied here from your computer:
#   /root/deploy_key.pub   the GitHub Actions key        -> deploy's authorized_keys
#   /root/admin_key.pub    your own login key            -> root's authorized_keys
# (--deploy-key-file and --admin-key-file name other places.) A re-run without
# a file keeps the key that is already installed.
#
# The SSH lock is a separate command on purpose. Turning off passwords before
# you have seen your key work is the other classic lock-out, so --lock-ssh
# refuses without a key in root's authorized_keys, asks you to confirm that you
# logged in from a second window with it, checks sshd's own verdict on the new
# setting, and reloads (not restarts) sshd, which keeps your open window open.
set -euo pipefail

DEPLOY_KEY_FILE=/root/deploy_key.pub
ADMIN_KEY_FILE=/root/admin_key.pub
REPO_URL="${CLASSNODE_REPO_URL:-https://github.com/adedejimakinde/luffy-school-saas.git}"
SSHD_DROPIN=/etc/ssh/sshd_config.d/00-classnode.conf
MODE=run

while [ $# -gt 0 ]; do
  case "$1" in
    --lock-ssh) MODE=lock ;;
    --unlock-ssh) MODE=unlock ;;
    --deploy-key-file) DEPLOY_KEY_FILE="${2:?--deploy-key-file needs a path}"; shift ;;
    --admin-key-file) ADMIN_KEY_FILE="${2:?--admin-key-file needs a path}"; shift ;;
    *) echo "usage: bootstrap.sh [--lock-ssh | --unlock-ssh] [--deploy-key-file F] [--admin-key-file F]" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nSTOPPED: %s\n' "$*" >&2; exit 1; }
trap 'printf "\nSTOPPED at line %s. Nothing is half-done that a re-run will not finish: run the same command again.\n" "$LINENO" >&2' ERR

[ "$(id -u)" = 0 ] || die "run this as root (you are $(id -un))."

# install_file DEST MODE [OWNER:GROUP] — stdin becomes DEST. Returns 0 if it
# wrote something new, 1 if DEST already held exactly that (so a re-run changes
# nothing and `&& changed=1` says whether anything needs reloading).
install_file() {
  local dest=$1 mode=$2 owner=${3:-root:root} tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [ -f "$dest" ] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
    return 1
  fi
  install -D -m "$mode" -o "${owner%%:*}" -g "${owner##*:}" "$tmp" "$dest"
  rm -f "$tmp"
}

# one_public_key FILE — the file's only line, if it is a real public key. A
# private key, an empty file or two keys are refused: the file is copied into
# authorized_keys, and what goes in there is who may log in.
one_public_key() {
  local file=$1 line tmp
  [ -s "$file" ] || return 1
  [ "$(grep -c . "$file")" = 1 ] || return 1
  line="$(grep . "$file" | tr -d '\r')"
  case "$line" in ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*) ;; *) return 1 ;; esac
  tmp="$(mktemp)"
  printf '%s\n' "$line" > "$tmp"
  if ! ssh-keygen -l -f "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"
  printf '%s\n' "$line"
}

reload_sshd() {
  sshd -t || return 1
  systemctl reload ssh
}

# ---------------------------------------------------------------- the SSH lock
if [ "$MODE" = unlock ]; then
  say "Turning password login back on"
  rm -f "$SSHD_DROPIN"
  reload_sshd
  echo "Done. $SSHD_DROPIN is gone; sshd accepts what it accepted before."
  echo "Effective setting: $(sshd -T | grep -i '^passwordauthentication')"
  exit 0
fi

if [ "$MODE" = lock ]; then
  say "Turning password login off"
  keys=0
  if [ -s /root/.ssh/authorized_keys ]; then
    keys="$(grep -cE '^(ssh-|ecdsa-)' /root/.ssh/authorized_keys || true)"
  fi
  [ "$keys" -ge 1 ] || die "root has no key in /root/.ssh/authorized_keys. Run bootstrap.sh with your key in $ADMIN_KEY_FILE first; locking now would shut you out."
  echo "root has $keys key(s) installed."
  echo
  echo "Before this goes on, in a SECOND PowerShell window you must already have run:"
  echo "    ssh root@<this server>"
  echo "and got in WITHOUT being asked for the server's password."
  echo "(A passphrase for your own key is fine; that is not the server's password.)"
  if [ -r /dev/tty ]; then
    read -r -p "Did that work? Type yes to lock: " answer < /dev/tty
  else
    die "no terminal to ask on. Run this from your SSH window."
  fi
  [ "$answer" = yes ] || die "not confirmed, nothing changed."

  install_file "$SSHD_DROPIN" 644 <<'EOF' || true
# Written by deploy/bootstrap.sh --lock-ssh. Removed by --unlock-ssh.
# Named 00- so it is read before cloud-init's 50-cloud-init.conf, which turns
# passwords on: sshd keeps the FIRST value it reads for each setting.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF
  # sshd's own answer, not ours: if another file won, undo and say so.
  if ! reload_sshd || [ "$(sshd -T | awk '$1 == "passwordauthentication" {print $2}')" != no ]; then
    rm -f "$SSHD_DROPIN"
    reload_sshd || true
    die "sshd does not report passwordauthentication no, so the lock was taken back off. Nothing is locked."
  fi
  echo "Effective setting: $(sshd -T | grep -i '^passwordauthentication')"
  echo "Your open windows stay open. Now test from a NEW window that a password is refused:"
  echo "    ssh -o PubkeyAuthentication=no root@<this server>     (expect: Permission denied (publickey).)"
  echo "If anything is wrong: bootstrap.sh --unlock-ssh"
  exit 0
fi

# -------------------------------------------------------------------- 1. checks
say "Checking this is the server we expect"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || die "this is ${PRETTY_NAME:-unknown}, not Ubuntu 24.04."
ssh_port="$(sshd -T | awk '$1 == "port" {print $2; exit}')"
[ "$ssh_port" = 22 ] || die "sshd listens on port $ssh_port, and the firewall below only opens 22. Put sshd back on 22 or change this script on purpose."

# ------------------------------------------------------------------- 2. the keys
say "Reading the keys before changing anything"
deploy_key=""
if [ -e "$DEPLOY_KEY_FILE" ]; then
  deploy_key="$(one_public_key "$DEPLOY_KEY_FILE")" || die "$DEPLOY_KEY_FILE is not exactly one public key (it must be the .pub file, one line starting ssh-ed25519)."
elif [ -s /home/deploy/.ssh/authorized_keys ]; then
  echo "No $DEPLOY_KEY_FILE; keeping the key deploy already has."
else
  die "no $DEPLOY_KEY_FILE. Copy classnode_deploy.pub from your computer to it (docs/first-day.md, step 5)."
fi
admin_key=""
if [ -e "$ADMIN_KEY_FILE" ]; then
  admin_key="$(one_public_key "$ADMIN_KEY_FILE")" || die "$ADMIN_KEY_FILE is not exactly one public key (it must be the .pub file)."
elif [ -s /root/.ssh/authorized_keys ]; then
  echo "No $ADMIN_KEY_FILE; keeping the keys root already has."
else
  die "no $ADMIN_KEY_FILE. Copy your id_ed25519.pub from your computer to it (docs/first-day.md, step 5)."
fi
if [ -n "$deploy_key" ] && [ "$deploy_key" = "$admin_key" ]; then
  die "the deploy key and your own key are the same file. They must be two different keys: the deploy key's private half goes to GitHub."
fi

# --------------------------------------------------------------- 3. updates
export DEBIAN_FRONTEND=noninteractive
# needrestart (installed on Ubuntu 24.04) would otherwise stop to ask which
# services to restart after an upgrade; none is restarted here.
export NEEDRESTART_SUSPEND=1
APT=(apt-get -y -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confold)

say "Updating the system (a few minutes the first time)"
"${APT[@]}" update
"${APT[@]}" upgrade

say "Installing the tools"
"${APT[@]}" install ufw fail2ban python3-systemd unattended-upgrades ca-certificates curl git gnupg openssl

# --------------------------------------------------------------- your key, root
say "Your login key for root"
if [ -n "$admin_key" ]; then
  install -d -m 700 -o root -g root /root/.ssh
  touch /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
  if grep -qxF "$admin_key" /root/.ssh/authorized_keys; then
    echo "already installed"
  else
    printf '%s\n' "$admin_key" >> /root/.ssh/authorized_keys
    echo "installed"
  fi
fi

# ------------------------------------------------------------------ 4. firewall
say "Firewall: only 22, 80 and 443"
ufw default deny incoming
ufw default allow outgoing
# 22 first, before the firewall is switched on.
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
ufw status verbose

# ------------------------------------------------------------------ 5. fail2ban
say "fail2ban"
changed=0
install_file /etc/fail2ban/jail.d/classnode.local 644 <<'EOF' && changed=1
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
EOF
systemctl enable --now fail2ban
[ "$changed" = 0 ] || systemctl restart fail2ban

# --------------------------------------------------------- 6. unattended upgrades
say "Automatic security updates"
install_file /etc/apt/apt.conf.d/20auto-upgrades 644 <<'EOF' || true
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
# 52- is read after Ubuntu's own 50unattended-upgrades, so these win.
install_file /etc/apt/apt.conf.d/52classnode-unattended 644 <<'EOF' || true
// Written by deploy/bootstrap.sh. Ubuntu's own file still decides WHAT is
// installed (security updates); this decides what happens after.
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades

# ------------------------------------------------------------------ 7. Docker
say "Docker"
docker_was_running=0
systemctl is-active --quiet docker 2>/dev/null && docker_was_running=1
daemon_changed=0
# Before the install, so the first start already has it. Without a cap a
# container's log grows until the disk is full.
install_file /etc/docker/daemon.json 644 <<'EOF' && daemon_changed=1
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
fi
chmod a+r /etc/apt/keyrings/docker.asc
install_file /etc/apt/sources.list.d/docker.list 644 <<EOF || true
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable
EOF
"${APT[@]}" update
"${APT[@]}" install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# A re-run that changed the log settings has to restart Docker for them to
# apply, and that restarts the containers (they come straight back).
if [ "$daemon_changed" = 1 ] && [ "$docker_was_running" = 1 ]; then
  systemctl restart docker
fi

# --------------------------------------------------------------- 8. deploy user
say "The deploy user"
if ! id deploy >/dev/null 2>&1; then
  adduser --disabled-password --gecos "Classnode deploy" deploy
fi
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
if [ -n "$deploy_key" ]; then
  # `restrict` switches off port forwarding, agents, X11 and a terminal; the
  # deploy workflow runs one command and needs none of them. A replaced key
  # replaces the old one (this is also how you rotate it).
  install_file /home/deploy/.ssh/authorized_keys 600 deploy:deploy <<EOF || true
restrict ${deploy_key}
EOF
fi
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

# --------------------------------------------------------------- 9. directories
say "Directories and the repository"
# The database and Redis data (deploy/compose.yml, CLASSNODE_DATA).
install -d -m 755 /srv/classnode /srv/classnode/postgres /srv/classnode/redis
# The secrets. deploy must be able to read them: `docker compose` reads an
# env_file on the CLIENT side, as whoever runs it. Nobody else can.
install -d -m 750 -o root -g deploy /etc/classnode
if [ ! -d /opt/classnode/.git ]; then
  git clone "$REPO_URL" /opt/classnode
fi
# deploy.sh writes `deployed-sha` next to itself, as deploy.
chown -R deploy:deploy /opt/classnode

say "Done"
if [ -f /var/run/reboot-required ]; then
  echo "This server wants a reboot (a new kernel). Run:  reboot"
  echo "Then wait a minute and log in again. Everything above is already in place."
fi
echo "Next: docs/first-day.md, step 7 — log in a second time, with your key."
