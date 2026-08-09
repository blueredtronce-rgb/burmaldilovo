# -*- coding: utf-8 -*-
"""
Player infection extension for SmartY-Anomalies.
Loaded by anomaly.py after the exact for-cg anomaly core.
PySpigot / Jython 2.7 / Paper-Leaf 1.21.x.
"""

try:
    from org.bukkit import Sound as _InfSound, NamespacedKey as _InfKey
except Exception:
    _InfSound = None
    _InfKey = None

INF_PROPERTY = "SmartY_AnomalyInfectionController"
INF_FILE = os.path.join(AnomalyConfig.DATA_DIR, "anomaly-infections.json")
INF_BACKUP = INF_FILE + ".bak"

INF_ZONE_INTERVAL = 5
INF_ZONE_CHANCE = 0.25
INF_STAGE1_SECONDS = 2 * 3600
INF_STAGE2_SECONDS = 4 * 3600
INF_STAGE1_LATENT_SECONDS = 20 * 60
INF_CONTACT_INTERVAL = 5
INF_CONTACT_RADIUS = 5.0
INF_INSOMNIA_CHANCE = 0.50
INF_COMPASS_INTERVAL = 3
INF_STAGE1_SYMPTOM_MIN = 90
INF_STAGE1_SYMPTOM_MAX = 240
INF_STAGE2_SYMPTOM_MIN = 45
INF_STAGE2_SYMPTOM_MAX = 120
INF_STAGE3_SYMPTOM_MIN = 30
INF_STAGE3_SYMPTOM_MAX = 90


def _inf_effect(name, fallback=None):
    if PotionEffectType is None:
        return None
    try:
        value = getattr(PotionEffectType, name, None)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        if _InfKey is not None and hasattr(PotionEffectType, "getByKey"):
            value = PotionEffectType.getByKey(_InfKey.minecraft(name.lower()))
            if value is not None:
                return value
    except Exception:
        pass
    if fallback:
        try:
            return getattr(PotionEffectType, fallback, None)
        except Exception:
            pass
    return None


_INF_NAUSEA = _inf_effect("NAUSEA", "CONFUSION")
_INF_DARKNESS = _inf_effect("DARKNESS")


class AnomalyInfectionController(object):
    def __init__(self, anomaly_manager):
        self.manager = anomaly_manager
        self.plugin = anomaly_manager.plugin
        self.active = False
        self.listeners = []
        self.task_ids = []
        self.data = self._load()
        self.zone_next = {}
        self.symptom_next = {}
        self.compass_next = {}
        self.contact_next = 0
        self.last_pulse_key = None
        self.old_handle = None
        self.old_tab = None
        self._normalize()

    def _default(self):
        return {"schema_version": 1, "players": {}}

    def _normalize(self):
        if not isinstance(self.data, dict):
            self.data = self._default()
        if not isinstance(self.data.get("players"), dict):
            self.data["players"] = {}
        for uid_key in list(self.data["players"].keys()):
            record = self.data["players"].get(uid_key)
            if not isinstance(record, dict):
                self.data["players"].pop(uid_key, None)
                continue
            record.setdefault("uuid", uid_key)
            record.setdefault("name", u"?")
            record.setdefault("infected_at", now_ts())
            record["stage"] = max(1, min(3, safe_int(record.get("stage"), 1)))
            record.setdefault("stage_started_at", record.get("infected_at", now_ts()))
            record.setdefault("source", "UNKNOWN")
            record.setdefault("source_anomaly_id", None)
            record.setdefault("source_player_uuid", None)
            record.setdefault("insomnia_night_key", None)
            record.setdefault("insomnia_blocked", False)

    def _load_path(self, path):
        with open(path, "r") as handle:
            raw = json.load(handle, parse_constant=reject_json_constant)
        if not isinstance(raw, dict):
            raise ValueError("infection database root must be an object")
        return raw

    def _load(self):
        try:
            if os.path.exists(INF_FILE):
                return self._load_path(INF_FILE)
        except Exception as exc:
            log_error(u"Cannot read anomaly-infections.json", exc)
        try:
            if os.path.exists(INF_BACKUP):
                log_info(u"Loading infection data from backup.")
                return self._load_path(INF_BACKUP)
        except Exception as exc:
            log_error(u"Cannot read infection backup", exc)
        return self._default()

    def _save(self):
        try:
            if not os.path.exists(AnomalyConfig.DATA_DIR):
                os.makedirs(AnomalyConfig.DATA_DIR)
            temp = INF_FILE + ".tmp"
            with open(temp, "w") as handle:
                handle.write(json.dumps(self.data, indent=2, ensure_ascii=True, sort_keys=True, allow_nan=False))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
            if os.path.exists(INF_FILE):
                backup_tmp = INF_BACKUP + ".tmp"
                with open(INF_FILE, "rb") as source:
                    with open(backup_tmp, "wb") as target:
                        target.write(source.read())
                        target.flush()
                atomic_replace_file(backup_tmp, INF_BACKUP)
            atomic_replace_file(temp, INF_FILE)
            return True
        except Exception as exc:
            log_error(u"Cannot save anomaly-infections.json", exc)
            return False

    def start(self):
        self.active = True
        self._register_event(PlayerBedEnterEvent, self.on_bed, EventPriority.HIGHEST)
        self._schedule(self.tick, 20, 20)
        self._patch_commands()
        log_action(u"Infection system started; infected={0}.".format(len(self.data.get("players", {}))))

    def stop(self):
        self.active = False
        self._unpatch_commands()
        for listener in self.listeners:
            try:
                HandlerList.unregisterAll(listener)
            except Exception:
                pass
        self.listeners = []
        for task_id in self.task_ids:
            try:
                Bukkit.getScheduler().cancelTask(int(task_id))
            except Exception:
                pass
        self.task_ids = []
        self._save()
        try:
            if JAVA_AVAILABLE and System is not None:
                props = System.getProperties()
                if props.get(INF_PROPERTY) is self:
                    props.remove(INF_PROPERTY)
        except Exception:
            pass

    def _register_event(self, event_class, callback, priority):
        listener = EmptyListener()
        executor = CallbackExecutor(callback)
        Bukkit.getPluginManager().registerEvent(event_class, listener, priority, executor, self.plugin, False)
        self.listeners.append(listener)

    def _schedule(self, callback, delay, period):
        task = Bukkit.getScheduler().runTaskTimer(self.plugin, CallbackRunnable(callback), int(delay), int(period))
        self.task_ids.append(int(task.getTaskId()))

    def uid(self, player):
        return str(player.getUniqueId())

    def record(self, player):
        return self.data.get("players", {}).get(self.uid(player))

    def infect(self, player, source="ZONE", anomaly=None, source_player=None, stage=1):
        uid_key = self.uid(player)
        if uid_key in self.data.setdefault("players", {}):
            return False
        now = now_ts()
        stage = max(1, min(3, safe_int(stage, 1)))
        record = {
            "uuid": uid_key,
            "name": to_unicode(player.getName()),
            "infected_at": now,
            "stage": stage,
            "stage_started_at": now,
            "source": to_unicode(source),
            "source_anomaly_id": anomaly.get("id") if isinstance(anomaly, dict) else None,
            "source_player_uuid": self.uid(source_player) if source_player is not None else None,
            "insomnia_night_key": None,
            "insomnia_blocked": False
        }
        self.data["players"][uid_key] = record
        self.zone_next.pop(uid_key, None)
        self.symptom_next[uid_key] = now + random.randint(120, 300)
        if not self._save():
            self.data["players"].pop(uid_key, None)
            return False
        log_action(u"Player infected: {0}, source={1}, anomaly={2}.".format(player.getName(), source, record.get("source_anomaly_id") or "-"))
        return True

    def clear(self, player):
        uid_key = self.uid(player)
        removed = self.data.setdefault("players", {}).pop(uid_key, None)
        self.zone_next.pop(uid_key, None)
        self.symptom_next.pop(uid_key, None)
        self.compass_next.pop(uid_key, None)
        try:
            player.setCompassTarget(player.getWorld().getSpawnLocation())
        except Exception:
            pass
        if removed is None:
            return False
        self._save()
        log_action(u"Infection cleared administratively: {0}.".format(player.getName()))
        return True

    def set_stage(self, player, stage):
        stage = max(1, min(3, safe_int(stage, 1)))
        record = self.record(player)
        if record is None:
            return self.infect(player, "ADMIN", stage=stage)
        record["stage"] = stage
        record["stage_started_at"] = now_ts()
        record["insomnia_night_key"] = None
        record["insomnia_blocked"] = False
        self.symptom_next[self.uid(player)] = now_ts() + 5
        self._save()
        log_action(u"Infection stage set: {0} -> {1}.".format(player.getName(), stage))
        return True

    def _sound(self, name):
        if _InfSound is None:
            return None
        try:
            return getattr(_InfSound, name, None)
        except Exception:
            return None

    def _play_private(self, player, names, volume=0.45, pitch=None):
        sound = self._sound(random.choice(names))
        if sound is None:
            return
        try:
            if pitch is None:
                pitch = random.uniform(0.55, 1.30)
            player.playSound(player.getLocation(), sound, float(volume), float(pitch))
        except Exception:
            pass

    def _particle(self, names):
        if Particle is None:
            return None
        for name in names:
            try:
                value = getattr(Particle, name, None)
                if value is not None:
                    return value
            except Exception:
                pass
        return None

    def _particles(self, player, public, count):
        particle = self._particle(("SCULK_SOUL", "SOUL", "ASH")) if public else self._particle(("ASH", "SOUL", "PORTAL"))
        if particle is None:
            return
        try:
            loc = player.getLocation().clone().add(0.0, 0.18, 0.0)
            if public:
                player.getWorld().spawnParticle(particle, loc, int(count), 0.45, 0.18, 0.45, 0.015)
            else:
                player.spawnParticle(particle, loc, int(count), 0.35, 0.10, 0.35, 0.01)
        except Exception:
            pass

    def _effect(self, player, effect_type, seconds):
        if PotionEffect is None or effect_type is None:
            return
        try:
            player.addPotionEffect(PotionEffect(effect_type, int(seconds * 20), 0, False, False, False), True)
        except Exception:
            pass

    def _puke(self, player, minimum, maximum):
        try:
            amount = random.randint(int(minimum), int(maximum))
            Bukkit.dispatchCommand(Bukkit.getConsoleSender(), to_java_string(u"brew puke {0} {1}".format(player.getName(), amount)))
        except Exception as exc:
            self.manager.log_error_throttled("infection-puke", u"Brewery /brew puke integration failed", exc, 120)

    def _symptom_delay(self, stage):
        if stage <= 1:
            return random.randint(INF_STAGE1_SYMPTOM_MIN, INF_STAGE1_SYMPTOM_MAX)
        if stage == 2:
            return random.randint(INF_STAGE2_SYMPTOM_MIN, INF_STAGE2_SYMPTOM_MAX)
        return random.randint(INF_STAGE3_SYMPTOM_MIN, INF_STAGE3_SYMPTOM_MAX)

    def _stage1_symptom(self, player, record, now):
        strange = ("AMBIENT_CAVE", "BLOCK_SCULK_SENSOR_CLICKING", "ENTITY_ENDERMAN_STARE", "BLOCK_RESPAWN_ANCHOR_DEPLETE")
        infected_at = safe_int(record.get("infected_at"), now)
        if now - infected_at < INF_STAGE1_LATENT_SECONDS:
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

    def _stage2_or_3_symptom(self, player, stage):
        sculk = ("BLOCK_SCULK_SENSOR_CLICKING", "BLOCK_SCULK_SHRIEKER_SHRIEK", "ENTITY_WARDEN_HEARTBEAT", "ENTITY_WARDEN_AMBIENT")
        strange = ("AMBIENT_CAVE", "ENTITY_ENDERMAN_STARE", "BLOCK_RESPAWN_ANCHOR_DEPLETE", "BLOCK_PORTAL_AMBIENT")
        self._play_private(player, sculk, 0.50)
        if random.random() < 0.70:
            self._play_private(player, strange, 0.30)
        self._particles(player, True, random.randint(5, 10))
        chance = 0.60 if stage == 2 else 0.78
        if random.random() < chance:
            seconds = random.randint(10, 15) if stage == 2 else random.randint(12, 18)
            self._effect(player, _INF_NAUSEA, seconds)
            if random.random() < (0.40 if stage == 2 else 0.55):
                self._puke(player, 2, 4 if stage == 2 else 5)

    def _progress_and_symptoms(self, players, now):
        for player in players:
            record = self.record(player)
            if record is None:
                continue
            stage = safe_int(record.get("stage"), 1, 1, 3)
            started = safe_int(record.get("stage_started_at"), record.get("infected_at", now))
            required = INF_STAGE1_SECONDS if stage == 1 else INF_STAGE2_SECONDS
            if stage < 3 and now - started >= required:
                stage += 1
                record["stage"] = stage
                record["stage_started_at"] = now
                record["insomnia_night_key"] = None
                record["insomnia_blocked"] = False
                self.symptom_next[self.uid(player)] = now + random.randint(20, 60)
                self._save()
                log_action(u"Infection progressed: {0} -> stage {1}.".format(player.getName(), stage))
            due = safe_int(self.symptom_next.get(self.uid(player)), 0)
            if due <= 0:
                self.symptom_next[self.uid(player)] = now + self._symptom_delay(stage)
            elif now >= due:
                if stage == 1:
                    self._stage1_symptom(player, record, now)
                else:
                    self._stage2_or_3_symptom(player, stage)
                self.symptom_next[self.uid(player)] = now + self._symptom_delay(stage)
            if stage >= 3:
                self._random_compass(player, now)

    def _zone_exposure(self, players, now):
        online_healthy = set()
        for player in players:
            uid_key = self.uid(player)
            if self.record(player) is not None:
                self.zone_next.pop(uid_key, None)
                continue
            online_healthy.add(uid_key)
            try:
                anomaly = self.manager.anomaly_at_location(player.getLocation())
            except Exception:
                anomaly = None
            if anomaly is None:
                self.zone_next.pop(uid_key, None)
                continue
            due = self.zone_next.get(uid_key)
            if due is not None and now < safe_int(due, 0):
                continue
            self.zone_next[uid_key] = now + INF_ZONE_INTERVAL
            if random.random() < INF_ZONE_CHANCE:
                self.infect(player, "ZONE", anomaly=anomaly, stage=1)
        for uid_key in list(self.zone_next.keys()):
            if uid_key not in online_healthy:
                self.zone_next.pop(uid_key, None)

    def _contact_chance(self, distance):
        try:
            distance = float(distance)
        except Exception:
            return 0.0
        if distance > INF_CONTACT_RADIUS:
            return 0.0
        return min(0.30, max(0.0, (6.0 - distance) * 0.05))

    def _contact_spread(self, players, now):
        if now < self.contact_next:
            return
        self.contact_next = now + INF_CONTACT_INTERVAL
        infectious = []
        healthy = []
        for player in players:
            record = self.record(player)
            if record is None:
                healthy.append(player)
            elif safe_int(record.get("stage"), 1, 1, 3) >= 2:
                infectious.append(player)
        for target in healthy:
            nearest = None
            nearest_distance = INF_CONTACT_RADIUS + 1.0
            for source in infectious:
                try:
                    if source.getWorld() != target.getWorld():
                        continue
                    distance = source.getLocation().distance(target.getLocation())
                    if distance <= INF_CONTACT_RADIUS and distance < nearest_distance:
                        nearest = source
                        nearest_distance = distance
                except Exception:
                    continue
            if nearest is not None:
                chance = self._contact_chance(nearest_distance)
                if chance > 0.0 and random.random() < chance:
                    self.infect(target, "CONTACT", anomaly=None, source_player=nearest, stage=1)

    def _pulse(self, player, stage):
        self._effect(player, _INF_DARKNESS, random.randint(2, 5))
        self._play_private(player, ("ENTITY_WARDEN_HEARTBEAT", "BLOCK_SCULK_SENSOR_CLICKING"), 0.70, random.uniform(0.55, 0.80))
        try:
            sound = self._sound("BLOCK_SCULK_SENSOR_CLICKING")
            if sound is not None:
                player.playSound(player.getLocation(), sound, 0.45, random.uniform(0.75, 1.05))
        except Exception:
            pass
        self._particles(player, stage >= 2, random.randint(5, 12))

    def _global_pulses(self, players):
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
            if minute == 30 and stage < 3:
                continue
            self._pulse(player, stage)

    def _random_compass(self, player, now):
        uid_key = self.uid(player)
        if now < safe_int(self.compass_next.get(uid_key), 0):
            return
        self.compass_next[uid_key] = now + INF_COMPASS_INTERVAL
        try:
            limit = 29900000
            x = random.randint(-limit, limit)
            z = random.randint(-limit, limit)
            player.setCompassTarget(Location(player.getWorld(), float(x) + 0.5, 64.0, float(z) + 0.5))
        except Exception:
            pass

    def on_bed(self, event):
        try:
            player = event.getPlayer()
            record = self.record(player)
            if record is None or safe_int(record.get("stage"), 1, 1, 3) < 3:
                return
            day = int(player.getWorld().getFullTime() // 24000)
            night_key = u"{0}:{1}".format(to_unicode(player.getWorld().getName()), day)
            if to_unicode(record.get("insomnia_night_key")) != night_key:
                record["insomnia_night_key"] = night_key
                record["insomnia_blocked"] = random.random() < INF_INSOMNIA_CHANCE
                self._save()
            if record.get("insomnia_blocked"):
                event.setCancelled(True)
                send_message(player, u"&cВы страдаете бессонницей.")
        except Exception as exc:
            self.manager.log_error_throttled("infection-insomnia", u"Infection insomnia handler failed", exc)

    def tick(self):
        if not self.active or self.manager is None or not self.manager.active:
            return
        now = now_ts()
        try:
            players = list(Bukkit.getOnlinePlayers())
        except Exception:
            players = []
        try:
            self._zone_exposure(players, now)
            self._contact_spread(players, now)
            self._progress_and_symptoms(players, now)
            self._global_pulses(players)
        except Exception as exc:
            self.manager.log_error_throttled("infection-tick", u"Infection cycle failed", exc)

    def _online(self, name):
        try:
            return Bukkit.getPlayer(to_java_string(name))
        except Exception:
            return None

    def _admin_status(self, sender, player=None):
        if player is not None:
            record = self.record(player)
            if record is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&7Игрок &f{0}&7 не заражён.".format(player.getName()))
                return True
            send_message(sender, AnomalyConfig.PREFIX + u"&f{0}&7: стадия &f{1}&7, source=&f{2}&7, anomaly=&f{3}&7.".format(player.getName(), record.get("stage"), record.get("source"), record.get("source_anomaly_id") or u"-"))
            return True
        records = self.data.get("players", {})
        send_message(sender, AnomalyConfig.PREFIX + u"&7Заражённых в журнале: &f{0}".format(len(records)))
        for uid_key, record in sorted(records.items(), key=lambda item: to_unicode(item[1].get("name"))):
            send_message(sender, u"&8- &f{0} &7S{1} source={2}".format(record.get("name") or uid_key, record.get("stage"), record.get("source")))
        return True

    def _admin(self, sender, args):
        if not args or args[0].lower() in ("list", "status"):
            if len(args) >= 2:
                player = self._online(args[1])
                if player is None:
                    send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                    return True
                return self._admin_status(sender, player)
            return self._admin_status(sender)
        sub = args[0].lower()
        if sub == "infect":
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly infection infect <игрок> [1|2|3]")
                return True
            player = self._online(args[1])
            if player is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                return True
            stage = safe_int(args[2], 1, 1, 3) if len(args) >= 3 else 1
            ok = self.infect(player, "ADMIN", stage=stage)
            send_message(sender, AnomalyConfig.PREFIX + (u"&aЗаражение выдано." if ok else u"&eИгрок уже заражён или запись не сохранилась."))
            return True
        if sub == "stage":
            if len(args) < 3:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly infection stage <игрок> <1|2|3>")
                return True
            player = self._online(args[1])
            if player is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                return True
            stage = safe_int(args[2], 0)
            if stage not in (1, 2, 3):
                send_message(sender, AnomalyConfig.PREFIX + u"&cСтадия: 1, 2 или 3.")
                return True
            self.set_stage(player, stage)
            send_message(sender, AnomalyConfig.PREFIX + u"&aСтадия {0} установлена для {1}.".format(stage, player.getName()))
            return True
        if sub in ("clear", "cure"):
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly infection clear <игрок>")
                return True
            player = self._online(args[1])
            if player is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                return True
            ok = self.clear(player)
            send_message(sender, AnomalyConfig.PREFIX + (u"&aЗаражение очищено." if ok else u"&eИгрок не был заражён."))
            return True
        return self._admin_status(sender)

    def _patch_commands(self):
        self.old_handle = self.manager.handle_command
        self.old_tab = self.manager.tab_complete
        controller = self
        old_handle = self.old_handle
        old_tab = self.old_tab

        def handle(sender, args):
            converted = [to_unicode(value) for value in args]
            if converted and converted[0].lower() == "infection" and controller.manager.is_admin(sender):
                return controller._admin(sender, converted[1:])
            return old_handle(sender, args)

        def tab(sender, args):
            converted = [to_unicode(value) for value in args]
            if not controller.manager.is_admin(sender):
                return old_tab(sender, args)
            if len(converted) <= 1:
                base = list(old_tab(sender, args))
                prefix = converted[0].lower() if converted else ""
                if "infection".startswith(prefix) and "infection" not in base:
                    base.append("infection")
                return base
            if converted[0].lower() != "infection":
                return old_tab(sender, args)
            if len(converted) == 2:
                prefix = converted[-1].lower()
                return [item for item in ("list", "status", "infect", "stage", "clear") if item.startswith(prefix)]
            if len(converted) == 3 and converted[1].lower() in ("status", "infect", "stage", "clear"):
                prefix = converted[-1].lower()
                try:
                    return [to_unicode(player.getName()) for player in Bukkit.getOnlinePlayers() if to_unicode(player.getName()).lower().startswith(prefix)]
                except Exception:
                    return []
            if len(converted) == 4 and converted[1].lower() in ("infect", "stage"):
                prefix = converted[-1]
                return [value for value in ("1", "2", "3") if value.startswith(prefix)]
            return []

        self.manager.handle_command = handle
        self.manager.tab_complete = tab

    def _unpatch_commands(self):
        try:
            if self.old_handle is not None:
                self.manager.handle_command = self.old_handle
            if self.old_tab is not None:
                self.manager.tab_complete = self.old_tab
        except Exception:
            pass


infection_controller = None


def start_infection_extension():
    global infection_controller
    if manager is None or not BUKKIT_AVAILABLE:
        return
    try:
        if JAVA_AVAILABLE and System is not None:
            props = System.getProperties()
            old = props.get(INF_PROPERTY)
            if old is not None and hasattr(old, "stop"):
                old.stop()
    except Exception as exc:
        log_error(u"Cannot stop previous infection controller", exc)
    infection_controller = AnomalyInfectionController(manager)
    infection_controller.start()
    try:
        if JAVA_AVAILABLE and System is not None:
            System.getProperties().put(INF_PROPERTY, infection_controller)
    except Exception:
        pass


start_infection_extension()
_base_anomaly_on_disable = on_disable


def on_disable():
    global infection_controller
    if infection_controller is not None:
        try:
            infection_controller.stop()
        except Exception as exc:
            log_error(u"Infection shutdown error", exc)
    infection_controller = None
    _base_anomaly_on_disable()


def stop(script=None):
    on_disable()
