FROM golang:1.27.1-bookworm AS go
FROM node:24-bookworm-slim
ARG OPENCODE_VERSION=2.0.22
RUN apt-get update && apt-get install -y --no-install-recommends python3 git gcc libc6-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @opencode/cli@${OPENCODE_VERSION} \
    && npm cache clean --force
COPY --from=go /usr/local/go /usr/local/go
ENV PYTHONPATH=/opt PATH=/usr/local/go/bin:$PATH \
    GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local
RUN useradd --uid 10001 --create-home harness && mkdir -p /workspace /opt/harness \
    && chown harness:harness /workspace
COPY harness /opt/harness/
COPY specs /opt/specs
USER 10001
WORKDIR /workspace
EXPOSE 8080
CMD ["python3", "-m", "harness.app"]
