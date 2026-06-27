# Server-Server Backup Protocol

## Discovery

Same UDP broadcast on port 52801. Payload: `{"role": "server", "mac": "<mac>", "port": 8444}`.

## Master / Slave Election

- On startup, each Server broadcasts and waits 10 s.
- If no peer responds: self-elect as **MASTER**.
- If a peer responds and completes the mutual handshake: the node that received
  the broadcast first becomes MASTER; the broadcaster becomes SLAVE. Tie-break
  by lexicographic MAC comparison (lower MAC = MASTER).

## Backup Transfer

MASTER initiates ZFS snapshot (`zfs snapshot tank/malmberg@<timestamp>`) and
sends the incremental stream to SLAVE via the HTTPS `/backup/stream` endpoint
(chunked transfer, mutual TLS). If ZFS is unavailable on SLAVE, MASTER falls
back to rsync-over-HTTPS.

## Backup Retention (Circular Buffer with Exponential Backoff)

- Let `n` be the configurable retention count (default 20).
- The first `ceil(n/2)` snapshots are always kept.
- For each additional snapshot slot, retention probability halves (geometric
  series), capped at `2n` total snapshots.
- On each new backup: evaluate retention for the oldest candidates; delete
  those that fail the probabilistic test.
- All deletions are appended to `logs/backup-audit.jsonl` with timestamp,
  snapshot name, and reason.

`GET /backup/history` returns the full audit log.

The same exponential-backoff retention policy is used for log rotation (see
architecture.md Section 3.6), with `n=10` by default.
