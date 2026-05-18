#!/usr/bin/env bash
set -uo pipefail

echo "==== HTTPS frontend ===="
curl -sk -m 5 -o /dev/null -w 'https://5.42.118.110/  -> %{http_code}\n' https://5.42.118.110/

echo
echo "==== HTTP -> HTTPS redirect ===="
curl -sk -m 5 -o /dev/null -w 'http://5.42.118.110:8080/  -> %{http_code} (redirect to %{redirect_url})\n' http://5.42.118.110:8080/
curl -sk -m 5 -o /dev/null -w 'http://5.42.118.110/       -> %{http_code} (redirect to %{redirect_url})\n' http://5.42.118.110/

echo
echo "==== Backend services over HTTPS ===="
for p in 8001 8002 8003 8004 8005 8006; do
  curl -sk -m 5 -o /dev/null -w "https://5.42.118.110:${p}/health -> %{http_code}\n" "https://5.42.118.110:${p}/health"
done

echo
echo "==== LiveKit WSS health (HTTP HEAD on the WSS port) ===="
curl -sk -m 5 -o /dev/null -w 'https://5.42.118.110:7880/ -> %{http_code}\n' https://5.42.118.110:7880/

echo
echo "==== Plain HTTP on TLS-only port should 400 ===="
curl -s -m 5 -o /dev/null -w 'http://5.42.118.110:8001/health -> %{http_code}\n' http://5.42.118.110:8001/health
