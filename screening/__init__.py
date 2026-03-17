"""screening – constants, term lists and phase-2 scoring logic."""

from screening.constants import *  # noqa: F401,F403

try:
    from screening.phase2 import *  # noqa: F401,F403
except ModuleNotFoundError:
    pass
