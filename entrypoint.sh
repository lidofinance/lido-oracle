#!/usr/bin/env sh

# NOTE: crond has to be invoked by root, otherwise it won't be able to run a job.
# crontab files have to have uid=0, and it's impossible to do via chown with no
# root privileges. So all the crond-related commands are in the entrypoint.

INIT_DIR=/container-init.d
CRONTABS=$INIT_DIR/crontabs
BOOTSTRAP_SCRIPT=$INIT_DIR/010-pin-cids.sh

if [ ! -e $CRONTABS ]; then mkdir -p $CRONTABS; fi
if [ ! -e $BOOTSTRAP_SCRIPT ]; then echo "Make sure $BOOTSTRAP_SCRIPT is mounted" && exit 1; fi

printf "@hourly timeout 600s $BOOTSTRAP_SCRIPT >&2\n" > $CRONTABS/ipfs
echo "Starting crond" && /bin/crond -c$CRONTABS

exec /usr/local/bin/start_ipfs "$@"
