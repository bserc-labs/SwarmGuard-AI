"""Modules that are not part of the running product.

Nothing under `backend/services/` imports anything here, and nothing here runs
on the live telemetry path. Each module is retained rather than deleted because
it represents real work with a plausible future; see README.md for what each one
is and what would have to be true for it to move back into `services/`.

If you wire one of these into the request or detection path, move the file back
into `services/` in the same change. A module that is live but filed under
`experimental/` is worse than either arrangement on its own.
"""
