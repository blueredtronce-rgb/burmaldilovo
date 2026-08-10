# -*- coding: utf-8 -*-
"""
Research extension for SmartY-Anomalies.
Loaded from anomaly.py after anomaly_infection.inc.

Adds:
- Experimental Gas Mask Mk.I (PDC-marked iron helmet).
- 50% reduction of both zone and CONTACT infection chance while worn.
- Two configurable laboratory test pods.
- Non-destructive laboratory filtration trials for comparing masked/unmasked
  subjects without creating extra infections or consuming ZONE seed slots.
- Hidden admin controls under /anomaly infection ...

PySpigot / Jython 2.7 / Paper-Leaf 1.21.x.
"""

try:
    from org.bukkit import NamespacedKey as _ResearchKey
    from org.bukkit.inventory import ItemStack as _ResearchItemStack
    from org.bukkit.persistence import PersistentDataType as _ResearchPDT
except Exception:
    _ResearchKey = None
    _ResearchItemStack = None
    _ResearchPDT = None

RESEARCH_MASK_ID = u"mk1"
RESEARCH_MASK_FACTOR = 0.50
RESEARCH_LAB_BASE_CHANCE = 0.20
RESEARCH_LAB_RADIUS = 2.75
RESEARCH_LAB_DEFAULT_TRIALS = 20
RESEARCH_LAB_MAX_TRIALS = 100


def _research_root(controller):
    root = controller.data.setdefault("research", {})
    if not isinstance(root, dict):
        root = {}
        controller.data["research"] = root
    pods = root.setdefault("lab_pods", {})
    if not isinstance(pods, dict):
        root["lab_pods"] = {}
    return root


def _research_mask_key(controller):
    if _ResearchKey is None:
        return None
    try:
        return _ResearchKey(controller.plugin, "anomaly_gasmask")
    except Exception:
        return None


def _research_is_mask_item(controller, item):
    if item is None:
        return False
    try:
        if Material is not None and item.getType() != Material.IRON_HELMET:
            return False
    except Exception:
        return False
    try:
        meta = item.getItemMeta()
        if meta is None:
            return False
        key = _research_mask_key(controller)
        if key is None or _ResearchPDT is None:
            return False
        value = meta.getPersistentDataContainer().get(key, _ResearchPDT.STRING)
        return to_unicode(value or u"").lower() == RESEARCH_MASK_ID
    except Exception:
        return False


def _research_player_has_mask(controller, player):
    try:
        helmet = player.getInventory().getHelmet()
    except Exception:
        return False
    return _research_is_mask_item(controller, helmet)


def _research_mask_factor(controller, player):
    return RESEARCH_MASK_FACTOR if _research_player_has_mask(controller, player) else 1.0


def _research_create_mask(controller):
    if _ResearchItemStack is None or Material is None:
        return None
    try:
        item = _ResearchItemStack(Material.IRON_HELMET, 1)
        meta = item.getItemMeta()
        if meta is None:
            return None
        meta.setDisplayName(colorize(u"&fЭкспериментальный противогаз &7Mk.I"))
        try:
            meta.setLore(build_java_list([
                colorize(u"&7Кустарный фильтрующий прототип."),
                colorize(u"&8Бумага + песчаный фильтр."),
                colorize(u"&8Эффективность требует проверки."),
                colorize(u"&8Исследовательский образец.")
            ]))
        except Exception:
            pass
        key = _research_mask_key(controller)
        if key is None or _ResearchPDT is None:
            return None
        meta.getPersistentDataContainer().set(
            key, _ResearchPDT.STRING, to_java_string(RESEARCH_MASK_ID)
        )
        item.setItemMeta(meta)
        return item
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-gasmask-create",
            u"Cannot create experimental gas mask",
            exc,
            120
        )
        return None


def _research_give_mask(controller, sender, player):
    item = _research_create_mask(controller)
    if item is None:
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось создать противогаз.")
        return True
    try:
        leftovers = player.getInventory().addItem(item)
        if leftovers and len(leftovers) > 0:
            player.getWorld().dropItemNaturally(player.getLocation(), item)
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&aПротивогаз Mk.I выдан игроку &f{0}&a.".format(player.getName())
        )
        send_message(
            player,
            u"&fПолучен исследовательский прототип: &7Экспериментальный противогаз Mk.I"
        )
        log_action(u"Research gas mask Mk.I issued to {0}.".format(player.getName()))
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-gasmask-give",
            u"Cannot give experimental gas mask",
            exc,
            120
        )
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось выдать противогаз.")
    return True


def _research_set_pod(controller, sender, pod_id):
    if pod_id not in ("1", "2"):
        send_message(sender, AnomalyConfig.PREFIX + u"&cКолба: 1 или 2.")
        return True
    try:
        loc = sender.getLocation()
        world = loc.getWorld()
        if world is None:
            raise ValueError("world is null")
    except Exception:
        send_message(
            sender,
            AnomalyConfig.PREFIX + u"&cЭту команду нужно выполнить игроком внутри нужной колбы."
        )
        return True

    root = _research_root(controller)
    root["lab_pods"][pod_id] = {
        "world": to_unicode(world.getName()),
        "x": float(loc.getX()),
        "y": float(loc.getY()),
        "z": float(loc.getZ())
    }
    controller._save()
    send_message(
        sender,
        AnomalyConfig.PREFIX +
        u"&aЛабораторная колба {0} привязана к текущей позиции.".format(pod_id)
    )
    log_action(u"Research lab pod {0} configured by {1}.".format(
        pod_id, getattr(sender, "getName", lambda: "console")()
    ))
    return True


def _research_near_pod(controller, player):
    root = _research_root(controller)
    pods = root.get("lab_pods", {})
    try:
        loc = player.getLocation()
        world_name = to_unicode(loc.getWorld().getName())
    except Exception:
        return None
    radius_sq = RESEARCH_LAB_RADIUS * RESEARCH_LAB_RADIUS
    for pod_id in ("1", "2"):
        pod = pods.get(pod_id)
        if not isinstance(pod, dict):
            continue
        if to_unicode(pod.get("world")) != world_name:
            continue
        try:
            dx = float(loc.getX()) - float(pod.get("x"))
            dy = float(loc.getY()) - float(pod.get("y"))
            dz = float(loc.getZ()) - float(pod.get("z"))
            if dx * dx + dy * dy + dz * dz <= radius_sq:
                return pod_id
        except Exception:
            continue
    return None


def _research_lab_status(controller, sender):
    pods = _research_root(controller).get("lab_pods", {})
    for pod_id in ("1", "2"):
        pod = pods.get(pod_id)
        if isinstance(pod, dict):
            send_message(
                sender,
                AnomalyConfig.PREFIX +
                u"&7Колба {0}: &f{1} {2:.1f} {3:.1f} {4:.1f}".format(
                    pod_id,
                    to_unicode(pod.get("world") or u"?"),
                    float(pod.get("x", 0.0)),
                    float(pod.get("y", 0.0)),
                    float(pod.get("z", 0.0))
                )
            )
        else:
            send_message(sender, AnomalyConfig.PREFIX + u"&7Колба {0}: &cне задана".format(pod_id))
    return True


def _research_lab_test(controller, sender, player, trials):
    pod_id = _research_near_pod(controller, player)
    if pod_id is None:
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&cИгрок должен находиться в одной из настроенных лабораторных колб."
        )
        return True

    trials = safe_int(trials, RESEARCH_LAB_DEFAULT_TRIALS)
    trials = max(1, min(RESEARCH_LAB_MAX_TRIALS, trials))
    masked = _research_player_has_mask(controller, player)
    chance = RESEARCH_LAB_BASE_CHANCE * _research_mask_factor(controller, player)
    penetrations = 0
    for _unused in range(trials):
        if random.random() < chance:
            penetrations += 1

    try:
        controller._particles(player, False, random.randint(4, 8))
        controller._play_private(
            player,
            ("BLOCK_SCULK_SENSOR_CLICKING", "AMBIENT_CAVE"),
            0.22
        )
    except Exception:
        pass

    send_message(
        sender,
        AnomalyConfig.PREFIX +
        u"&7Лабораторная проба: колба=&f{0}&7, игрок=&f{1}&7, противогаз=&f{2}&7, проникновений=&f{3}/{4}&7.".format(
            pod_id,
            player.getName(),
            u"ДА" if masked else u"НЕТ",
            penetrations,
            trials
        )
    )
    send_message(
        sender,
        u"&8Тест не заражает игрока и не расходует лимит естественных носителей. Сравнивайте серии проб."
    )
    send_message(
        player,
        u"&7Лабораторное испытание завершено. Результат зафиксирован исследователями."
    )
    log_action(
        u"Research lab trial: player={0}, pod={1}, mask={2}, penetrations={3}/{4}.".format(
            player.getName(), pod_id, masked, penetrations, trials
        )
    )
    return True


try:
    _research_base_zone_exposure = AnomalyInfectionController._zone_exposure
    _research_base_contact_spread = AnomalyInfectionController._contact_spread
    _research_base_admin = AnomalyInfectionController._admin

    def _research_zone_exposure(self, players, now):
        seed_count = self._zone_seed_count()
        if seed_count >= INF_ZONE_SEED_LIMIT:
            self.zone_next = {}
            return

        online_healthy = set()
        for player in players:
            if seed_count >= INF_ZONE_SEED_LIMIT:
                break
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
            chance = INF_ZONE_CHANCE * _research_mask_factor(self, player)
            if random.random() < chance:
                if self.infect(player, "ZONE", anomaly=anomaly, stage=1):
                    seed_count += 1

        for uid_key in list(self.zone_next.keys()):
            if uid_key not in online_healthy:
                self.zone_next.pop(uid_key, None)

    def _research_contact_spread(self, players, now):
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
            if nearest is None:
                continue
            chance = self._contact_chance(nearest_distance)
            chance *= _research_mask_factor(self, target)
            if chance > 0.0 and random.random() < chance:
                self.infect(
                    target,
                    "CONTACT",
                    anomaly=None,
                    source_player=nearest,
                    stage=1,
                    contact_distance=nearest_distance,
                    contact_chance=chance
                )

    def _research_admin(self, sender, args):
        if args:
            sub = to_unicode(args[0]).lower()

            if sub == "gasmask":
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7/anomaly infection gasmask give <игрок> | gasmask status <игрок>"
                    )
                    return True
                action = to_unicode(args[1]).lower()
                if action in ("give", "status"):
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите онлайн-игрока.")
                        return True
                    player = self._online(args[2])
                    if player is None:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                        return True
                    if action == "give":
                        return _research_give_mask(self, sender, player)
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7{0}: противогаз Mk.I надет=&f{1}&7.".format(
                            player.getName(),
                            u"ДА" if _research_player_has_mask(self, player) else u"НЕТ"
                        )
                    )
                    return True

            if sub == "lab":
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7/anomaly infection lab set <1|2> | lab status"
                    )
                    return True
                action = to_unicode(args[1]).lower()
                if action == "set":
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите колбу 1 или 2.")
                        return True
                    return _research_set_pod(self, sender, to_unicode(args[2]))
                if action == "status":
                    return _research_lab_status(self, sender)

            if sub == "labtest":
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&c/anomaly infection labtest <игрок> [число проб]"
                    )
                    return True
                player = self._online(args[1])
                if player is None:
                    send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                    return True
                trials = args[2] if len(args) >= 3 else RESEARCH_LAB_DEFAULT_TRIALS
                return _research_lab_test(self, sender, player, trials)

        return _research_base_admin(self, sender, args)

    AnomalyInfectionController._zone_exposure = _research_zone_exposure
    AnomalyInfectionController._contact_spread = _research_contact_spread
    AnomalyInfectionController._admin = _research_admin

    if infection_controller is not None:
        _research_root(infection_controller)

    log_action(
        u"Research extension installed: Gas Mask Mk.I x0.50 infection risk, two lab pods, non-destructive filtration trials."
    )
except Exception as _research_install_error:
    try:
        log_error(u"Cannot install anomaly research extension", _research_install_error)
    except Exception:
        pass
