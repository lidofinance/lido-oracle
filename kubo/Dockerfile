FROM ipfs/kubo:v0.34.1

ENV GATEWAY_PORT 8080
ENV API_PORT 5001

ENV CHAIN mainnet

COPY ./_pin-cids /usr/local/bin/_pin-cids
COPY ./010-set-conf.sh /container-init.d/
COPY ./020-pin-cids.sh /container-init.d/

COPY ./entrypoint.sh /

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
