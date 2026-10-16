#!/usr/bin/env bash
# The Mailgun route for cpl's calendar address (settings.CALENDAR_INBOUND_ADDRESS):
# mail to it is posted raw (a URL ending in mime) to that machine's
# /calendar/inbound/mime.
#
#   deploy/mailgun-calendar-route.sh list   show the routes there are
#   deploy/mailgun-calendar-route.sh dev    cpl-calendar@mail.darmok.link
#   deploy/mailgun-calendar-route.sh prod   calendar@mail.cloud-portal.net
#
# A route already there with the same match is left as it is. The API key
# is MAILGUN_API_KEY in ~/cpl/.env.
set -euo pipefail

cd "$(dirname "$0")/.."
MAILGUN_API_KEY=$(grep -E '^MAILGUN_API_KEY=' .env | cut -d= -f2- | tr -d '"'"'")
API=https://api.mailgun.net/v3/routes

case "${1:-}" in
  dev)
    description="dev (darmok.link): cpl calendar address"
    expression='match_recipient("^cpl-calendar@mail\.darmok\.link$")'
    url="https://cloud.darmok.link/calendar/inbound/mime"
    ;;
  prod)
    description="prod cpl: calendar address"
    expression='match_recipient("^calendar@mail\.cloud-portal\.net$")'
    url="https://cloud-portal.net/calendar/inbound/mime"
    ;;
  list)
    curl -s --user "api:$MAILGUN_API_KEY" "$API" | python3 -c '
import json, sys
for route in json.load(sys.stdin)["items"]:
    print(route["priority"], route["description"])
    print("   ", route["expression"])
    print("   ", ", ".join(route["actions"]))'
    exit 0
    ;;
  *)
    echo "usage: $0 dev|prod|list" >&2
    exit 2
    ;;
esac

existing=$(curl -s --user "api:$MAILGUN_API_KEY" "$API" | EXPRESSION="$expression" python3 -c '
import json, os, sys
print(sum(r["expression"] == os.environ["EXPRESSION"] for r in json.load(sys.stdin)["items"]))')
if [ "$existing" != "0" ]; then
  echo "A route matching $expression is already there; nothing changed."
  exit 0
fi

curl -s --user "api:$MAILGUN_API_KEY" "$API" \
  -F priority=1 \
  -F description="$description" \
  -F expression="$expression" \
  -F action="forward(\"$url\")" \
  -F action='stop()' | python3 -m json.tool
