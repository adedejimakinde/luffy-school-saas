#!/usr/bin/env bash
# Sign in on the portal through the forwarded URL, then use that session on the
# school's forwarded host — the path a browser takes. Usage: e2e.sh <login> <school-path>...
S=/home/vscode/luffy-handover/demo
P=https://$CODESPACE_NAME-8002.app.github.dev
C=https://$CODESPACE_NAME-8001.app.github.dev
J=$S/jar-$1.txt
rm -f "$J"
H=(-s -m 30 -H "X-Github-Token: $GITHUB_TOKEN" -b "$J" -c "$J")
TOK=$(curl "${H[@]}" "$P/api/csrf/" | python3 -c "import sys,json;print(json.load(sys.stdin)['csrf_token'])")
curl "${H[@]}" -o "$S/login-$1.json" -w "login $1: %{http_code}\n" \
  -H "Content-Type: application/json" -H "X-CSRFToken: $TOK" -H "Origin: $P" -H "Referer: $P/sign-in/" \
  -d "{\"identifier\":\"$1\",\"password\":\"demo-pass-2026\"}" "$P/api/login/"
python3 -c "import json;d=json.load(open('$S/login-$1.json'));print('  schools:', [(s['name'], s['host']) for s in d.get('schools', [])])" 2>/dev/null
grep -v Tunnels "$J" | grep -v "^#" | awk -F'\t' 'NF{print "  cookie", $6, "domain", $1}'
shift
for path in "$@"; do
  curl "${H[@]}" -o "$S/e2e-body.txt" -w "  school $path: %{http_code} %{size_download}B\n" "$C$path"
done
