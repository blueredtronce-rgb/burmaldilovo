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
import math
import random
import time


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
# Infection tuning approved after test
# ---------------------------------------------------------------------------
try:
    # 20% per exposure roll: first detection in an active zone, then every 5s.
    INF_ZONE_CHANCE = 0.20

    _base_infection_progress = AnomalyInfectionController._progress_and_symptoms

    def _production_puke(self, player, minimum=None, maximum=None):
        """Brewery visual looks best with 15-40 puke blocks."""
        try:
            amount = random.randint(15, 40)
            Bukkit.dispatchCommand(
                Bukkit.getConsoleSender(),
                to_java_string(u"brew puke {0} {1}".format(player.getName(), amount))
            )
        except Exception as exc:
            self.manager.log_error_throttled(
                "infection-puke",
                u"Brewery /brew puke integration failed",
                exc,
                120
            )

    def _production_global_pulses(self, players):
        """Stage II-III pulse at every real-world :00 and :30; stage I is silent."""
        try:
            local = time.localtime()
            minute = int(local.tm_min)
        except Exception:
            return
        if minute not in (0, 30):
            return
        key = time.strftime("%Y%m%d%H%M", local)
        if key == self.last_pulse_key:
            return
        self.last_pulse_key = key
        for player in players:
            record = self.record(player)
            if record is None:
                continue
            stage = safe_int(record.get("stage"), 1, 1, 3)
            if stage < 2:
                continue
            self._pulse(player, stage)

    def _hallucination_delay(stage):
        # Stage I: rare; stage II: noticeably more often; stage III: never
        # more frequent than roughly once every 3-5 minutes.
        if stage <= 1:
            return random.randint(12 * 60, 18 * 60)
        if stage == 2:
            return random.randint(6 * 60, 9 * 60)
        return random.randint(3 * 60, 5 * 60)

    def _play_hallucination(self, player, stage):
        """Play a fake nearby mob/explosion sound to this player only."""
        try:
            base = player.getLocation()
            angle = random.random() * math.pi * 2.0
            distance = random.uniform(4.0, 12.0)
            sound_loc = base.clone().add(
                math.cos(angle) * distance,
                random.uniform(-1.0, 2.0),
                math.sin(angle) * distance
            )

            roll = random.random()
            if roll < 0.30:
                names = ("ENTITY_CREEPER_PRIMED",)
                volume = random.uniform(0.55, 0.85)
                pitch = random.uniform(0.85, 1.08)
            elif roll < 0.50:
                names = ("ENTITY_TNT_PRIMED",)
                volume = random.uniform(0.50, 0.80)
                pitch = random.uniform(0.85, 1.10)
            elif roll < 0.65:
                names = ("ENTITY_GENERIC_EXPLODE",)
                volume = random.uniform(0.40, 0.70)
                pitch = random.uniform(0.90, 1.15)
            else:
                names = (
                    "ENTITY_ZOMBIE_AMBIENT",
                    "ENTITY_SKELETON_AMBIENT",
                    "ENTITY_SPIDER_AMBIENT",
                    "ENTITY_ENDERMAN_AMBIENT"
                )
                volume = random.uniform(0.45, 0.75)
                pitch = random.uniform(0.85, 1.15)

            sound = None
            candidates = list(names)
            random.shuffle(candidates)
            for name in candidates:
                sound = self._sound(name)
                if sound is not None:
                    break
            if sound is None:
                sound = self._sound("AMBIENT_CAVE")
            if sound is None:
                return

            # Player#playSound sends the positional sound only to this player.
            # No entity, TNT or explosion is spawned in the world.
            player.playSound(sound_loc, sound, float(volume), float(pitch))
        except Exception as exc:
            self.manager.log_error_throttled(
                "infection-hallucination",
                u"Infection hallucination sound failed",
                exc,
                120
            )

    def _production_progress_and_symptoms(self, players, now):
        _base_infection_progress(self, players, now)
        if not hasattr(self, "hallucination_next"):
            self.hallucination_next = {}

        online = set()
        for player in players:
            try:
                uid_key = self.uid(player)
                online.add(uid_key)
                record = self.record(player)
                if record is None:
                    self.hallucination_next.pop(uid_key, None)
                    continue
                stage = safe_int(record.get("stage"), 1, 1, 3)
                due = safe_int(self.hallucination_next.get(uid_key), 0)
                if due <= 0:
                    self.hallucination_next[uid_key] = now + _hallucination_delay(stage)
                    continue
                if now < due:
                    continue
                _play_hallucination(self, player, stage)
                self.hallucination_next[uid_key] = now + _hallucination_delay(stage)
            except Exception as exc:
                self.manager.log_error_throttled(
                    "infection-hallucination-cycle",
                    u"Infection hallucination cycle failed",
                    exc,
                    120
                )

        for uid_key in list(self.hallucination_next.keys()):
            if uid_key not in online:
                self.hallucination_next.pop(uid_key, None)

    AnomalyInfectionController._puke = _production_puke
    AnomalyInfectionController._global_pulses = _production_global_pulses
    AnomalyInfectionController._progress_and_symptoms = _production_progress_and_symptoms

    if infection_controller is not None:
        infection_controller.hallucination_next = {}

    log_action(u"Infection tuning installed: zone=20%, pulse=30m S2-S3, puke=15-40, hallucinations enabled.")
except Exception as _infection_tuning_error:
    try:
        log_error(u"Cannot install infection tuning", _infection_tuning_error)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Robust command bridge for Jython/PySpigot
# ---------------------------------------------------------------------------
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
