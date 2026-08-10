# -*- coding: utf-8 -*-
"""
SmartY-Anomalies test-cg entrypoint.

Windows/PySpigot-safe layout:
- anomaly.py is the only executable PySpigot script.
- anomaly_core.inc contains the exact production anomaly implementation from for-cg.
- anomaly_infection.inc contains the additive infection extension.
- anomaly_research.inc contains the experimental laboratory / gas-mask extension.

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
_ANOMALY_RESEARCH = os.path.join(_ANOMALY_SCRIPT_DIR, "anomaly_research.inc")

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
    INF_ZONE_CHANCE = 0.20

    def _production_puke(self, player, minimum=None, maximum=None):
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
        if stage <= 1:
            return random.randint(12 * 60, 18 * 60)
        if stage == 2:
            return random.randint(6 * 60, 9 * 60)
        return random.randint(3 * 60, 5 * 60)

    def _play_hallucination(self, player, stage):
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

            player.playSound(sound_loc, sound, float(volume), float(pitch))
        except Exception as exc:
            self.manager.log_error_throttled(
                "infection-hallucination",
                u"Infection hallucination sound failed",
                exc,
                120
            )

    def _online_stage1_symptom(self, player, record, now):
        strange = (
            "AMBIENT_CAVE",
            "BLOCK_SCULK_SENSOR_CLICKING",
            "ENTITY_ENDERMAN_STARE",
            "BLOCK_RESPAWN_ANCHOR_DEPLETE"
        )
        online_seconds = safe_int(record.get("stage_online_seconds"), 0)
        if online_seconds < INF_STAGE1_LATENT_SECONDS:
            self._play_private(player, strange, 0.30)
            return
        roll = random.random()
        if roll < 0.48:
            self._play_private(player, strange, 0.35)
        elif roll < 0.73:
            self._particles(player, False, random.randint(2, 5))
            self._play_private(player, strange, 0.25)
        else:
            self._effect(player, _INF_NAUSEA, 5)
            self._play_private(player, strange, 0.35)
            if random.random() < 0.35:
                self._puke(player, 1, 2)

    def _production_progress_and_symptoms(self, players, now):
        if not hasattr(self, "hallucination_next"):
            self.hallucination_next = {}
        if not hasattr(self, "online_progress_last_tick"):
            self.online_progress_last_tick = {}
        if not hasattr(self, "online_progress_last_save"):
            self.online_progress_last_save = now

        online = set()
        dirty = False

        for player in players:
            try:
                uid_key = self.uid(player)
                online.add(uid_key)
                record = self.record(player)
                if record is None:
                    self.hallucination_next.pop(uid_key, None)
                    self.online_progress_last_tick.pop(uid_key, None)
                    continue

                # Count only time while this player is actually online. The
                # first tick after join/reload establishes a baseline and adds
                # nothing, so offline time can never leak into progression.
                previous_tick = self.online_progress_last_tick.get(uid_key)
                self.online_progress_last_tick[uid_key] = now
                if "stage_online_seconds" not in record:
                    record["stage_online_seconds"] = 0
                    dirty = True
                if previous_tick is not None:
                    elapsed = max(0, safe_int(now - previous_tick, 0))
                    if elapsed > 0:
                        record["stage_online_seconds"] = (
                            safe_int(record.get("stage_online_seconds"), 0) + elapsed
                        )
                        dirty = True

                stage = safe_int(record.get("stage"), 1, 1, 3)
                online_seconds = safe_int(record.get("stage_online_seconds"), 0)
                required = INF_STAGE1_SECONDS if stage == 1 else INF_STAGE2_SECONDS

                if stage < 3 and online_seconds >= required:
                    overflow = max(0, online_seconds - required)
                    stage += 1
                    record["stage"] = stage
                    record["stage_started_at"] = now
                    record["stage_online_seconds"] = overflow if stage < 3 else 0
                    record["insomnia_night_key"] = None
                    record["insomnia_blocked"] = False
                    self.symptom_next[uid_key] = now + random.randint(20, 60)
                    dirty = True
                    self._save()
                    self.online_progress_last_save = now
                    dirty = False
                    log_action(u"Infection progressed by ONLINE time: {0} -> stage {1}.".format(
                        player.getName(), stage
                    ))

                due = safe_int(self.symptom_next.get(uid_key), 0)
                if due <= 0:
                    self.symptom_next[uid_key] = now + self._symptom_delay(stage)
                elif now >= due:
                    if stage == 1:
                        _online_stage1_symptom(self, player, record, now)
                    else:
                        self._stage2_or_3_symptom(player, stage)
                    self.symptom_next[uid_key] = now + self._symptom_delay(stage)

                if stage >= 3:
                    self._random_compass(player, now)

                hall_due = safe_int(self.hallucination_next.get(uid_key), 0)
                if hall_due <= 0:
                    self.hallucination_next[uid_key] = now + _hallucination_delay(stage)
                elif now >= hall_due:
                    _play_hallucination(self, player, stage)
                    self.hallucination_next[uid_key] = now + _hallucination_delay(stage)
            except Exception as exc:
                self.manager.log_error_throttled(
                    "infection-online-progression-cycle",
                    u"Infection online progression cycle failed",
                    exc,
                    120
                )

        # Forget baselines for players who left. If they return hours later,
        # their first tick starts from zero elapsed offline time.
        for uid_key in list(self.online_progress_last_tick.keys()):
            if uid_key not in online:
                self.online_progress_last_tick.pop(uid_key, None)
        for uid_key in list(self.hallucination_next.keys()):
            if uid_key not in online:
                self.hallucination_next.pop(uid_key, None)

        # Persist accumulated online time once a minute. A crash can therefore
        # lose at most roughly one minute of progression, while normal restart
        # calls stop() and saves immediately.
        if dirty and now - safe_int(self.online_progress_last_save, now) >= 60:
            if self._save():
                self.online_progress_last_save = now

    def _unique_zone_seed_count(self):
        """Count unique natural carriers, not repeated ZONE events."""
        seed_keys = set()
        for event in self.data.get("events", []):
            if not isinstance(event, dict):
                continue
            if to_unicode(event.get("source") or u"").upper() != u"ZONE":
                continue
            uid_key = to_unicode(event.get("target_uuid") or u"").strip()
            if uid_key:
                seed_keys.add(u"uuid:" + uid_key)
            else:
                seed_keys.add(u"name:" + to_unicode(event.get("target_name") or u"?").lower())
        return len(seed_keys)

    AnomalyInfectionController._puke = _production_puke
    AnomalyInfectionController._global_pulses = _production_global_pulses
    AnomalyInfectionController._progress_and_symptoms = _production_progress_and_symptoms
    AnomalyInfectionController._zone_seed_count = _unique_zone_seed_count

    if infection_controller is not None:
        infection_controller.hallucination_next = {}
        infection_controller.online_progress_last_tick = {}
        infection_controller.online_progress_last_save = now_ts()

    log_action(u"Infection tuning installed: zone=20%, unique zone seeds=3, ONLINE stage timers 2h+4h, pulse=30m S2-S3, puke=15-40, hallucinations enabled.")
except Exception as _infection_tuning_error:
    try:
        log_error(u"Cannot install infection tuning", _infection_tuning_error)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Research extension (experimental gas mask + laboratory trials)
# ---------------------------------------------------------------------------
try:
    _exec_required(_ANOMALY_RESEARCH, "research extension")
except Exception as _research_load_error:
    try:
        log_error(u"Fatal research extension load error", _research_load_error)
    except Exception:
        try:
            print("[SmartY-Anomalies] research extension load error: " + str(_research_load_error))
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
                            item for item in (
                                "list", "status", "stats", "history",
                                "infect", "stage", "clear", "reset",
                                "gasmask", "lab", "labtest"
                            ) if item.startswith(prefix)
                        ])
                    if len(converted) == 3 and converted[1].lower() in (
                            "status", "history", "infect", "stage", "clear"):
                        prefix = converted[2].lower()
                        try:
                            return build_java_list([
                                to_unicode(player.getName())
                                for player in Bukkit.getOnlinePlayers()
                                if to_unicode(player.getName()).lower().startswith(prefix)
                            ])
                        except Exception:
                            return build_java_list([])
                    if len(converted) == 3 and converted[1].lower() == "reset":
                        return build_java_list([
                            "confirm" for value in ("confirm",)
                            if value.startswith(converted[2].lower())
                        ])
                    if len(converted) == 3 and converted[1].lower() == "gasmask":
                        prefix = converted[2].lower()
                        return build_java_list([
                            value for value in ("give", "status") if value.startswith(prefix)
                        ])
                    if len(converted) == 3 and converted[1].lower() == "lab":
                        prefix = converted[2].lower()
                        return build_java_list([
                            value for value in ("set", "status") if value.startswith(prefix)
                        ])
                    if len(converted) == 4 and converted[1].lower() == "gasmask" and converted[2].lower() in ("give", "status"):
                        prefix = converted[3].lower()
                        try:
                            return build_java_list([
                                to_unicode(player.getName())
                                for player in Bukkit.getOnlinePlayers()
                                if to_unicode(player.getName()).lower().startswith(prefix)
                            ])
                        except Exception:
                            return build_java_list([])
                    if len(converted) == 4 and converted[1].lower() == "lab" and converted[2].lower() == "set":
                        prefix = converted[3]
                        return build_java_list([value for value in ("1", "2") if value.startswith(prefix)])
                    if len(converted) == 3 and converted[1].lower() == "labtest":
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
