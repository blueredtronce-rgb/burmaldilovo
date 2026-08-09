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

_exec_required(_ANOMALY_CORE, "anomaly core")

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

# ---------------------------------------------------------------------------
# Robust command bridge for Jython/PySpigot
# ---------------------------------------------------------------------------
# Some Jython/PySpigot builds keep the originally-bound manager method inside
# the registered Command proxy.  Runtime replacement of manager.handle_command
# can therefore be ignored.  Intercept the command at AnomalyCommand.execute
# itself so /anomaly infection ... is routed before the production help path.
try:
    _base_anomaly_execute = AnomalyCommand.execute
    _base_anomaly_tabcomplete = AnomalyCommand.tabComplete

    def _testcg_anomaly_execute(self, sender, command_label, args):
        try:
            converted = [to_unicode(value) for value in list(args)]
            if converted and converted[0].lower() == "infection":
                controller = globals().get("infection_controller")
                if controller is not None and controller.active:
                    if self.manager.is_admin(sender):
                        return bool(controller._admin(sender, converted[1:]))
                    self.manager.send_unknown_command(sender)
                    return True
            return bool(_base_anomaly_execute(self, sender, command_label, args))
        except Exception as exc:
            log_error(u"/anomaly test-cg command bridge error", exc)
            if self.manager.is_admin(sender):
                send_message(sender, AnomalyConfig.PREFIX + u"&cВнутренняя ошибка infection-команды. См. консоль.")
            else:
                self.manager.send_unknown_command(sender)
            return True

    def _testcg_anomaly_tabcomplete(self, sender, alias, args, location=None):
        try:
            converted = [to_unicode(value) for value in list(args)]
            if not self.manager.is_admin(sender):
                return _base_anomaly_tabcomplete(self, sender, alias, args, location)

            if len(converted) == 1 and "infection".startswith(converted[0].lower()):
                base = list(self.manager.tab_complete(sender, list(args)))
                if "infection" not in base:
                    base.append("infection")
                return build_java_list(base)

            if converted and converted[0].lower() == "infection":
                controller = globals().get("infection_controller")
                if controller is not None:
                    if len(converted) == 2:
                        prefix = converted[1].lower()
                        return build_java_list([
                            item for item in ("list", "status", "infect", "stage", "clear")
                            if item.startswith(prefix)
                        ])
                    if len(converted) == 3 and converted[1].lower() in ("status", "infect", "stage", "clear"):
                        prefix = converted[2].lower()
                        try:
                            return build_java_list([
                                to_unicode(player.getName())
                                for player in Bukkit.getOnlinePlayers()
                                if to_unicode(player.getName()).lower().startswith(prefix)
                            ])
                        except Exception:
                            return build_java_list([])
                    if len(converted) == 4 and converted[1].lower() in ("infect", "stage"):
                        prefix = converted[3]
                        return build_java_list([v for v in ("1", "2", "3") if v.startswith(prefix)])
                    return build_java_list([])

            return _base_anomaly_tabcomplete(self, sender, alias, args, location)
        except Exception as exc:
            log_error(u"/anomaly test-cg tab bridge error", exc)
            return build_java_list([])

    AnomalyCommand.execute = _testcg_anomaly_execute
    AnomalyCommand.tabComplete = _testcg_anomaly_tabcomplete
    log_action(u"test-cg infection command bridge installed.")
except Exception as _command_bridge_error:
    try:
        log_error(u"Cannot install test-cg infection command bridge", _command_bridge_error)
    except Exception:
        pass
