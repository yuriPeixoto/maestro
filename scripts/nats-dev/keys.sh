#!/bin/sh
# Local development only. Generates NKeys for the operator and two fake servers (dev-a, dev-b) and
# the users file the dev NATS server includes. Runs once: an existing users file is kept, so the
# keys survive `docker compose down` (they go with `down -v`).
set -eu

dir=/nats-dev
if [ -f "$dir/users.conf" ]; then
  echo "keys: keeping the existing ones in $dir"
  exit 0
fi

for name in admin dev-a dev-b; do
  nk -gen user > "$dir/$name.nk"
  chmod 600 "$dir/$name.nk"
done

public_key() { nk -inkey "$dir/$1.nk" -pubout; }

sh /deploy/nats/render-users.sh "$(public_key admin)" \
  "dev-a=$(public_key dev-a)" \
  "dev-b=$(public_key dev-b)" > "$dir/users.conf.tmp"
mv "$dir/users.conf.tmp" "$dir/users.conf"
echo "keys: generated admin, dev-a and dev-b in $dir"
