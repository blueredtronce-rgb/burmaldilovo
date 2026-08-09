# -*- coding: utf-8 -*-
"""
SmartY-Anomalies test-cg entrypoint.

Windows/PySpigot-safe layout:
- anomaly.py is the only executable PySpigot script.
- anomaly_core.inc contains the exact production anomaly implementation from for-cg.
- anomaly_infection.inc contains the additive infection extension.

PySpigot scans .py files in its scripts directory as standalone scripts, so the
internal implementation files deliberately use the .inc extension and are
executed only from this entrypoint.
"""

import os


def _anomaly_script_dir():
    """Return the real directory containing this loader on Windows/Linux."""
    try:
        if "__file__" in globals() and __file__:
            return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        pass

    # Fallback used by some PySpigot/Jython execution modes where __file__ is
    # absent.  os.path.join keeps the path correct on Windows and Unix.
    cwd = os.getcwd()
    guess = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.isdir(guess):
        return os.path.abspath(guess)
    return os.path.abspath(cwd)


def _exec_required(path, label):
    if not os.path.isfile(path):
        raise IOError("Missing {0}: {1}".format(label, path))
    execfile(path, globals(), globals())


_ANOMALY_SCRIPT_DIR = _anomaly_script_dir()
_ANOMALY_CORE = os.path.join(_ANOMALY_SCRIPT_DIR, "anomaly_core.inc")
_ANOMALY_INFECTION = os.path.join(_ANOMALY_SCRIPT_DIR, "anomaly_infection.inc")

# Execute the exact production core in this script namespace.  This preserves
# all existing manager/lifecycle/CoreProtect behaviour from for-cg.
_exec_required(_ANOMALY_CORE, "anomaly core")

# Infection is additive.  A failure here must not kill the already-started
# production anomaly core; it is logged server-side instead.
try:
    _exec_required(_ANOMALY_INFECTION, "infection extension")
except Exception as _infection_load_error:
    try:
        log_error(u"Fatal infection extension load error", _infection_load_error)
    except Exception:
        try:
            print("[SmartY-Anomalies] infection extension load error: " + str(_infection_load_error))
        except Exception:
            pass
