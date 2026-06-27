# Server-Display Handshake Protocol

## Discovery

1. Display broadcasts UDP to `255.255.255.255:52800` every 5 s until a Server
   responds. Payload: `{"role": "display", "mac": "<mac>", "port": 8443}`.
2. Server receives broadcast, records the Display's IP and port.

## Pairing PIN

Before any HTTPS exchange, both sides must agree on a shared PIN. This is the
only manual step the user performs after provisioning:

- Server generates a random 6-digit numeric PIN at startup (changes on each
  restart until pairing succeeds).
- PIN is shown on the Server's status panel in large text, or printed to
  console if no panel.
- Display shows a prompt: `"Enter the 6-digit number shown on your server box."`
  Entry is via the physical buttons (increment / confirm) or via the web
  dashboard form.
- Once the PIN is entered on the Display, it is included in the UDP broadcast.
  The Server accepts the broadcast only if the PIN matches.

No camera, no QR code, no fingerprint to read. A wrong PIN produces an
immediate `"Wrong PIN -- try again"` message. After 5 failed attempts the
Server rotates the PIN and shows the new one.

## Handshake (mutual HTTPS)

3. Server calls `GET https://<display-ip>:<port>/` using the Display's
   certificate (provided in the PIN-validated broadcast). Validates
   `Tag.id == "display"`.
4. Display receives the Server's TLS client cert and calls
   `GET https://<server-ip>:<server-port>/`. Validates `Tag.id == "server"`.
5. Both sides store the peer's certificate fingerprint (SHA-256). All
   subsequent requests use the pinned cert; any mismatch tears down the session
   and re-triggers discovery.
