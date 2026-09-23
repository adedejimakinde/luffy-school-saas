# Caddy with the Cloudflare DNS module, which the stock image does not carry and
# the wildcard certificate needs (DNS validation). Built by CI beside the app
# image and tagged with the same commit SHA, so a deploy moves both together.
#
# **Both versions are pinned, and must move together.** The first build here
# asked for `caddy:2.8` and an unpinned module; xcaddy fetched the newest module
# (v0.2.4), which needs certmagic 0.23, libdns 1.1 and zap/exp 0.3 — newer than
# Caddy 2.8.4 compiles against — and the build died with
# `undefined: zapslog.HandlerOptions`. Caddy 2.11.4 already builds against newer
# versions of all three (certmagic 0.25.3, libdns 1.1.1, zap/exp 0.3.0), read
# from both modules' go.mod on the Go module proxy. Unpinned, the same break
# returns the day either side releases; to upgrade, change both lines and let
# the `image` job build it.
FROM caddy:2.11.4-builder AS builder
RUN xcaddy build v2.11.4 --with github.com/caddy-dns/cloudflare@v0.2.4

FROM caddy:2.11.4
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
