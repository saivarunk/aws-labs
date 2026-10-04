# kvd specification

**Product:** `kvd`, a single-node, in-memory, etcd-inspired key-value store with an HTTP/JSON API.

**In scope**
- Operations: put, get, delete, list-by-prefix, health.
- Monotonic global **revision** counter (increments on each successful put/delete); each key tracks `create_revision`, `mod_revision`, `version`.
- Optional compare-and-swap on put/delete via `If-Match: <mod_revision>` header.
- Keys: non-empty UTF-8 string, max 256 bytes. Values: arbitrary bytes, max 1 MiB.
- Thread safe (`sync.RWMutex`), deterministic list order (lexicographic).
- Layered code: `store` (interface + in-memory impl), `api` (HTTP handlers), `cmd/kvd` (main).
- Go standard library only. Go version pinned in `go.mod`.

**Out of scope**
Persistence/WAL/snapshots, clustering/Raft, watch/streaming, leases/TTL, transactions, gRPC, TLS, authentication, metrics endpoints, Dockerfile/containers, CI config, third-party dependencies.

**HTTP API**
| Method | Path | Behavior |
|---|---|---|
| PUT | `/v1/keys/{key}` | body = value; returns 200/201 JSON with revisions; honors `If-Match` (412 on mismatch) |
| GET | `/v1/keys/{key}` | 200 JSON with value (base64) + revisions; 404 if absent |
| DELETE | `/v1/keys/{key}` | 200 with deleted revision; 404 if absent; honors `If-Match` |
| GET | `/v1/keys?prefix=` | 200 JSON array sorted by key |
| GET | `/healthz` | 200 `ok` |

Errors: JSON `{"error": "..."}`; 400 for invalid keys or malformed `If-Match`; 413 for a value > 1 MiB; 404 for missing keys; 412 for compare-and-swap mismatch.

**Acceptance criteria (AC-KV)**
- AC-KV1 PUT new key returns 201, `version=1`, `create_revision==mod_revision==global revision`.
- AC-KV2 PUT existing key returns 200, `version` increments, `create_revision` unchanged, `mod_revision` updated.
- AC-KV3 GET returns exactly the stored bytes; missing key returns 404.
- AC-KV4 DELETE removes the key and bumps the global revision; second DELETE returns 404.
- AC-KV5 List with prefix returns only matching keys in lexicographic order; empty prefix lists all.
- AC-KV6 `If-Match` with wrong revision returns 412 and does not mutate state; correct revision succeeds.
- AC-KV7 Empty key, key > 256 bytes, or value > 1 MiB is rejected with the specified status codes.
- AC-KV8 Concurrent writers (e.g., 50 goroutines x 100 puts) finish without data races: `go test -race` passes and final revision equals total successful writes.
- AC-KV9 `go vet ./...` and `gofmt -l .` report nothing.

**Testing requirements (all in-memory, no Docker, no external network)**
- **Unit tests:** `store` tested directly; `api` tested against a **hand-written fake `Store`** (interface-based mock, including injectable errors) with `httptest.NewRecorder`. Use a fake clock only if time is used (it should not be needed).
- **Integration tests:** start the real `api` + real in-memory `store` in-process with `httptest.NewServer`; drive via `net/http` client; cover AC-KV1..KV8 end to end. Place under `internal/integration` with build tag or package-level naming so `go test ./...` runs everything and `go test ./internal/integration/...` runs only integration.
- Required gates: `go test -race -count=1 ./...` passes; coverage for `store` and `api` >= 80% (`go test -cover`).

**Deliverables from the harness run (written to the working tree, then pushed)**
`PLAN.md` (implementation plan written *before* coding), source, tests, `ACCEPTANCE_REPORT.md` (table of AC-KV1..KV9 with pass/fail and the command evidence), `README.md`, `.gitignore` (Go-appropriate), `go.mod`.

**Push requirements (via MCP only):** create branch `harness/kvd-<session-suffix>`, push all files in a single commit via the MCP multi-file push tool, open a PR against the default branch with a body containing the acceptance report summary. No direct `git push`, no tokens in the sandbox. Confirm tool names via the Gateway's `tools/list` at runtime; do not hardcode guessed names without checking.

## Clarifications

- A successful put increments global revision even if bytes are unchanged. Failed operations never increment it. Deleting then recreating a key starts version at 1 with a new create revision.
- `If-Match` is a positive decimal mod revision. Malformed values return 400. A put to a missing key with `If-Match` returns 412. A delete of a missing key returns 404.
- URL-decode a key once; validate UTF-8 and the 256-byte limit after decoding. The empty suffix `/v1/keys/` is an invalid key (400). Keys may include encoded slashes; tests must cover decoding.
- Copy values on input and output so caller-owned slices cannot mutate stored bytes. Lists observe a consistent snapshot.
- Pin the Go toolchain version provided by the harness image in `go.mod`; do not attempt toolchain downloads.
- The target repo must have an existing default branch with a minimal initial commit. It may be empty of application code, but cannot be an unborn Git repository if the run must open a PR.
