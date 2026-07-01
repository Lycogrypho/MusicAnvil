"""Backwards-compatible alias for :mod:`ma_utils`.

All library code lives in ``ma_utils``; this module simply re-exports it so existing
imports (and the GUI) that reference ``MusicAnvil`` keep working. Edit ``ma_utils.py`` only.
"""

try:
    from . import ma_utils as _ma_utils  # package-relative import
    from .ma_utils import *  # noqa: F401,F403
except ImportError:
    import ma_utils as _ma_utils  # flat / script-directory import
    from ma_utils import *  # noqa: F401,F403

__all__ = [name for name in dir(_ma_utils) if not name.startswith("_")]
