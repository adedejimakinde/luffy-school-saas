# Caddy with the Cloudflare DNS module, which the stock image does not carry and
# the wildcard certificate needs (DNS validation). Built by CI beside the app
# image and tagged with the same commit SHA, so a deploy moves both together.
FROM caddy:2.8-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.8
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
