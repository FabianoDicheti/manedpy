"""Library discovery + ctypes.CDLL + ABI checks (MANEDPY_PLAN.md §4).

Will: honour $MANEDPY_LIB, else load manedpy/_lib/libmaned_c.<ext> by absolute
path; check MND_ABI_MIN <= mnd_abi_version() <= MND_ABI_MAX (a range, never an
exact match); assert sizeof(mnd_response) against maned_c_abi.json; register
the atexit hook that closes live handles (hazard 4); use CDLL, never PyDLL.
"""

_BLOCKED = (
    "manedpy is a scaffold: libmaned_c does not exist yet "
    "(MANEDPY_PLAN.md Phases 0-2b)"
)


def load_library():
    raise NotImplementedError(_BLOCKED)
