#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
name="ada-guard-$$"
tmp=$(mktemp -d)
cleanup() { docker rm -f "$name-on" "$name-off" "$name-stub" >/dev/null 2>&1 || true; docker network rm "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
docker build -q -t "$name" -f services/gateway/Dockerfile . >/dev/null
docker network create "$name" >/dev/null
printf "server { listen 8000; listen 5173; location / { return 200 'v=\$http_x_ada_visitor'; } }\n" > "$tmp/stub.conf"
docker run -d --name "$name-stub" --network "$name" --network-alias backend --network-alias frontend -v "$tmp/stub.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.30.6-alpine >/dev/null
for mode in on off; do
    token=testonly
    [[ $mode == on ]] || token=''
    docker run -d --name "$name-$mode" --network "$name" -p 127.0.0.1::80 -e DEMO_TOKEN="$token" "$name" >/dev/null
    port=$(docker port "$name-$mode" 80/tcp | cut -d: -f2)
    for _ in {1..50}; do curl -s "http://127.0.0.1:$port/" >/dev/null && break; sleep .2; done
    if [[ $mode == on ]]; then on=$port; else off=$port; fi
done
port=$on
request() {
    local expected=$1 method=$2 path=$3; shift 3
    code=$(curl -sS -D "$tmp/headers" -o "$tmp/body" -w '%{http_code}' -X "$method" "http://127.0.0.1:$port$path" "$@")
    [[ $code == "$expected" ]] || { echo "FAIL $method $path: expected $expected, got $code"; cat "$tmp/body"; exit 1; }
    if [[ $expected == 403 || $expected == 429 ]]; then
        grep -qi '^Content-Type: application/json' "$tmp/headers"
        grep -q '"detail":"[^"].*"' "$tmp/body"
    fi
}
request 200 GET /
grep -qi '^Set-Cookie: ada_visitor=' "$tmp/headers"
request 200 GET /api/projects
request 200 GET /api/health/live
request 403 GET /api/settings/agent
grep -q 'Settings are locked on the public demo.' "$tmp/body"
request 403 POST /mcp
request 200 PATCH /api/dashboards/x -H 'X-Ada-Visitor: 0'
grep -qx 'v=1' "$tmp/body"
for path in alert-rules/x/test alert-rules/x/check; do request 403 POST "/api/$path"; done
for path in dashboards/x/pins reports/x/versions sources/x/refresh widgets/x/review; do request 200 POST "/api/$path"; done
request 200 POST /api/projects
request 200 DELETE /api/sessions/s/attachments/a
for _ in {1..40}; do request 200 POST /api/hooks/context/x; done
for _ in {1..6}; do request 200 POST /api/sessions/s/messages -H 'Cookie: ada_visitor=browser' -H 'X-Forwarded-For: 203.0.113.1'; done
request 429 POST /api/sessions/s/messages -H 'Cookie: ada_visitor=browser' -H 'X-Forwarded-For: 203.0.113.1'
grep -q 'Demo limit reached: one agent turn per minute.' "$tmp/body"
request 200 POST /api/sessions/s/messages -H 'Cookie: ada_visitor=other' -H 'X-Forwarded-For: 203.0.113.2'
for i in {1..21}; do request 200 POST /api/sessions/s/research -H "Cookie: ada_visitor=rotate$i" -H 'X-Forwarded-For: 203.0.113.3'; done
request 429 POST /api/sessions/s/analysis -H 'Cookie: ada_visitor=rotate22' -H 'X-Forwarded-For: 203.0.113.3'
for _ in {1..31}; do request 200 POST /api/projects -H 'Cookie: ada_visitor=posts'; done
request 429 POST /api/projects -H 'Cookie: ada_visitor=posts'
grep -q 'Too many changes at once.' "$tmp/body"
request 200 GET /api/projects -H 'Cookie: ada_visitor=posts'
request 302 GET /team/testonly
grep -qi '^Set-Cookie: ada_team=testonly; Path=/; Max-Age=604800; HttpOnly; Secure; SameSite=Lax' "$tmp/headers"
grep -qi '^Location: .*/' "$tmp/headers"
request 200 GET /team/wrong
for cookie in wrong TESTONLY ''; do request 403 GET /api/settings/agent -H "Cookie: ada_team=$cookie"; done
request 200 GET /api/settings/agent -H 'Cookie: ada_team=testonly'
request 200 PATCH /api/dashboards/x -H 'Cookie: ada_team=testonly' -H 'X-Ada-Visitor: 1'
grep -qx 'v=' "$tmp/body"
for _ in {1..30}; do request 200 POST /api/sessions/s/messages -H 'Cookie: ada_team=testonly'; done
port=$off
request 200 GET /api/settings/agent
request 200 PATCH /api/dashboards/x
if env -u DEMO_TOKEN docker compose --env-file /dev/null -f docker-compose.yml -f docker-compose.deploy.yml config >"$tmp/compose" 2>&1; then echo 'FAIL: deploy accepted missing token'; exit 1; fi
grep -q 'DEMO_TOKEN' "$tmp/compose"
echo 'PASS: visitor policies, cookies, turn/browser/IP/POST limits, team bypass, guard off, mandatory deploy token'
