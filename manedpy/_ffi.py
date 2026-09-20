"""mnd_response struct, open/request wrappers, free discipline (MANEDPY_PLAN.md §4).

Two ownership rules: char* out-params from mnd_open -> mnd_free_string;
mnd_response* -> mnd_response_free. Python never calls libc.free.
This file is a transcription of maned_c.h — a drift-check test must diff every
signature against the header (MANEDPY_PLAN.md §8.3).
"""
