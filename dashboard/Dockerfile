FROM node:22-alpine

RUN adduser -D -u 10002 dash && mkdir -p /app && chown -R dash:dash /app
WORKDIR /app
USER dash

COPY --chown=dash:dash server.js ./

ENV TZ=UTC

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["node", "server.js"]
