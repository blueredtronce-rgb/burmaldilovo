# -*- coding: utf-8 -*-
"""
SmartY-Anomalies test-cg entrypoint.

The production anomaly implementation is preserved byte-for-byte in
anomaly_core.py from branch for-cg.  This entrypoint executes that exact core
in the same script namespace, then attaches the test infection extension from
anomaly_infection.py.

Deploy all three test-cg files together:
  anomaly.py
  anomaly_core.py
  anomaly_infection.py
"""

import os


def _anomaly_script_dir():
    try:
        if "__file__" in globals() and __file__:
            return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        pass
    cwd = os.getcwd()
    guess = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.exists(guess):
        return guess
    return cwd


_ANOMALY_SCRIPT_DIR = _anomaly_script_dir()
_ANOMALY_CORE = os.path.join(_ANOMALY_SCRIPT_DIR, "anomaly_core.py")
_ANOMALY_INFECTION = os.path.join(_ANOMALY_SCRIPT_DIR, "anomaly_infection.py")

# Jython 2.7 executes the original production script in this exact namespace,
# so its manager, lifecycle, commands and JVM properties behave as they did in
# for-cg.  No copy/reimplementation of the production logic is maintained here.
execfile(_ANOMALY_CORE, globals(), globals())

# Infection is an additive event-phase extension.  If it ever fails to load,
# keep the original anomaly system alive and leave a clear server-side error.
try:
    execfile(_ANOMALY_INFECTION, globals(), globals())
except Exception as _infection_load_error:
    try:
        log_error(u"Fatal infection extension load error", _infection_load_error)
    except Exception:
        try:
            print("[SmartY-Anomalies] infection extension load error: " + str(_infection_load_error))
        except Exception:
            pass
