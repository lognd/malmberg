# Privacy Filter (Optional, Strictly Opt-In)

The privacy filter is a post-ingest step that can flag images containing
specified faces or sensitive content before they enter the slideshow. It is
**entirely local** -- no cloud inference, no data leaves the machine.

**Installation:** the filter is in its own pip extra `[privacy]`. Nothing from
this extra is imported by any other part of the codebase. The provisioning
script does not mention it unless the user explicitly runs
`python -m malmberg_server setup --extras`. Even then, a clear warning is
shown: `"This will download ML model weights (~500 MB). Continue? [y/N]"`.

**Activation:** the filter is disabled in config by default. Three config keys
must all be `true` for it to run: `privacy_filter.enabled`,
`privacy_filter.faces_enabled` (or `content_enabled`), and the package must
actually be installed. If any condition is false, the filter is skipped and
logged at DEBUG as `"privacy filter not active"`.

**Behavior:** flagged items go to a review queue accessible from the web
dashboard (`/ui/review`). They are not served to Display clients until approved.
Items can be approved, hidden (applying `hide_policy`), or permanently deleted
from the dashboard.
