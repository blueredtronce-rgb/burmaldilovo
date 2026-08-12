# -*- coding: utf-8 -*-
"""
Protective-research extension for SmartY-Anomalies.
Loaded by anomaly.py after anomaly_infection.inc.

This file intentionally contains ONLY the current research technology:
- Isolation Suit Mk.I, a four-piece PDC-marked leather set.
- The suit protects only against CONTACT transmission from infected players.
- A COMPLETE set reduces each contact-infection roll by 95% (x0.05).
- Any missing/wrong piece breaks the seal and gives no protection.
- The suit does not protect from anomaly-zone exposure, does not cure infection,
  does not suppress symptoms and does not slow stage progression.
- Four custom crafting recipes are registered automatically.
- Two configurable laboratory pods can be used for safe comparative trials.
  Lab trials never infect anyone and never modify infection history.
- Hidden admin helpers live under /anomaly infection suit|lab|labtest ...

PySpigot / Jython 2.7 / Paper-Leaf 1.21.x.
"""

try:
    from org.bukkit import NamespacedKey as _ResearchKey, Color as _ResearchColor
    from org.bukkit.inventory import (
        ItemStack as _ResearchItemStack,
        ShapedRecipe as _ResearchShapedRecipe
    )
    from org.bukkit.persistence import PersistentDataType as _ResearchPDT
except Exception:
    _ResearchKey = None
    _ResearchColor = None
    _ResearchItemStack = None
    _ResearchShapedRecipe = None
    _ResearchPDT = None


# ---------------------------------------------------------------------------
# tuning
# ---------------------------------------------------------------------------

RESEARCH_SUIT_VERSION = u"mk1"
RESEARCH_SUIT_CONTACT_FACTOR = 0.05       # 95% lower CONTACT roll
RESEARCH_LAB_RADIUS = 2.75
RESEARCH_LAB_BASE_CHANCE = 0.20
RESEARCH_LAB_DEFAULT_TRIALS = 50
RESEARCH_LAB_MAX_TRIALS = 200

_RESEARCH_PIECES = (
    (u"helmet", "LEATHER_HELMET", u"Шлем изоляционного костюма Mk.I"),
    (u"chest", "LEATHER_CHESTPLATE", u"Куртка изоляционного костюма Mk.I"),
    (u"legs", "LEATHER_LEGGINGS", u"Брюки изоляционного костюма Mk.I"),
    (u"boots", "LEATHER_BOOTS", u"Ботинки изоляционного костюма Mk.I")
)


# ---------------------------------------------------------------------------
# generic helpers / persistence
# ---------------------------------------------------------------------------


def _research_root(controller):
    root = controller.data.setdefault("research", {})
    if not isinstance(root, dict):
        root = {}
        controller.data["research"] = root
    pods = root.setdefault("lab_pods", {})
    if not isinstance(pods, dict):
        root["lab_pods"] = {}
    return root


def _research_key(controller, name):
    if _ResearchKey is None:
        return None
    try:
        return _ResearchKey(controller.plugin, to_java_string(name))
    except Exception:
        try:
            return _ResearchKey(controller.plugin, name)
        except Exception:
            return None


def _research_piece_key(controller):
    return _research_key(controller, "anomaly_isolation_suit")


def _research_recipe_key(controller, piece):
    return _research_key(controller, "anomaly_isolation_suit_" + str(piece))


def _research_material(name):
    if Material is None:
        return None
    try:
        return getattr(Material, name, None)
    except Exception:
        return None


def _research_char(value):
    try:
        return to_java_string(value).charAt(0)
    except Exception:
        return value


# ---------------------------------------------------------------------------
# suit items
# ---------------------------------------------------------------------------


def _research_create_piece(controller, piece):
    piece = to_unicode(piece).lower()
    selected = None
    for info in _RESEARCH_PIECES:
        if info[0] == piece:
            selected = info
            break
    if selected is None or _ResearchItemStack is None:
        return None

    material = _research_material(selected[1])
    if material is None:
        return None

    try:
        item = _ResearchItemStack(material, 1)
        meta = item.getItemMeta()
        if meta is None:
            return None

        meta.setDisplayName(colorize(u"&e" + selected[2]))
        try:
            meta.setLore(build_java_list([
                colorize(u"&7Экспериментальная многослойная изоляция."),
                colorize(u"&8Защита работает только полным комплектом."),
                colorize(u"&8Не является лекарством."),
                colorize(u"&8Исследовательский образец Mk.I.")
            ]))
        except Exception:
            pass

        # Make the set visually recognizable as a laboratory/hazmat suit.
        try:
            if _ResearchColor is not None and hasattr(meta, "setColor"):
                meta.setColor(_ResearchColor.fromRGB(226, 207, 67))
        except Exception:
            pass

        key = _research_piece_key(controller)
        if key is None or _ResearchPDT is None:
            return None
        meta.getPersistentDataContainer().set(
            key,
            _ResearchPDT.STRING,
            to_java_string(RESEARCH_SUIT_VERSION + u":" + piece)
        )
        item.setItemMeta(meta)
        return item
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-suit-piece",
            u"Cannot create isolation suit piece",
            exc,
            120
        )
        return None


def _research_item_piece(controller, item):
    if item is None:
        return None
    try:
        meta = item.getItemMeta()
        if meta is None:
            return None
        key = _research_piece_key(controller)
        if key is None or _ResearchPDT is None:
            return None
        raw = meta.getPersistentDataContainer().get(key, _ResearchPDT.STRING)
        raw = to_unicode(raw or u"")
        prefix = RESEARCH_SUIT_VERSION + u":"
        if not raw.startswith(prefix):
            return None
        piece = raw[len(prefix):].lower()
        if piece in (u"helmet", u"chest", u"legs", u"boots"):
            return piece
    except Exception:
        pass
    return None


def _research_suit_state(controller, player):
    state = {
        "helmet": False,
        "chest": False,
        "legs": False,
        "boots": False,
        "full": False
    }
    try:
        inventory = player.getInventory()
        state["helmet"] = _research_item_piece(controller, inventory.getHelmet()) == u"helmet"
        state["chest"] = _research_item_piece(controller, inventory.getChestplate()) == u"chest"
        state["legs"] = _research_item_piece(controller, inventory.getLeggings()) == u"legs"
        state["boots"] = _research_item_piece(controller, inventory.getBoots()) == u"boots"
        state["full"] = bool(
            state["helmet"] and state["chest"] and
            state["legs"] and state["boots"]
        )
    except Exception:
        pass
    return state


def _research_contact_factor(controller, player):
    return RESEARCH_SUIT_CONTACT_FACTOR if _research_suit_state(controller, player)["full"] else 1.0


def _research_drop_leftovers(player, leftovers):
    try:
        if leftovers is None or len(leftovers) <= 0:
            return
        for item in leftovers.values():
            try:
                player.getWorld().dropItemNaturally(player.getLocation(), item)
            except Exception:
                pass
    except Exception:
        pass


def _research_give_set(controller, sender, player):
    created = []
    for piece, _material_name, _display_name in _RESEARCH_PIECES:
        item = _research_create_piece(controller, piece)
        if item is None:
            send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось создать полный комплект.")
            return True
        created.append(item)

    try:
        for item in created:
            leftovers = player.getInventory().addItem(item)
            _research_drop_leftovers(player, leftovers)
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&aИзоляционный костюм Mk.I выдан игроку &f{0}&a.".format(player.getName())
        )
        send_message(
            player,
            u"&eПолучен исследовательский комплект: &fИзоляционный костюм Mk.I"
        )
        log_action(u"Isolation Suit Mk.I issued to {0}.".format(player.getName()))
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-suit-give",
            u"Cannot give isolation suit",
            exc,
            120
        )
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось выдать костюм.")
    return True


# ---------------------------------------------------------------------------
# crafting recipes
# ---------------------------------------------------------------------------


def _research_add_recipe(controller, piece, rows, ingredients):
    if _ResearchShapedRecipe is None:
        return False
    result = _research_create_piece(controller, piece)
    key = _research_recipe_key(controller, piece)
    if result is None or key is None:
        return False
    try:
        try:
            Bukkit.removeRecipe(key)
        except Exception:
            pass

        recipe = _ResearchShapedRecipe(key, result)
        recipe.shape(
            to_java_string(rows[0]),
            to_java_string(rows[1]),
            to_java_string(rows[2])
        )
        for symbol, material_name in ingredients.items():
            material = _research_material(material_name)
            if material is None:
                raise ValueError("Missing material: " + str(material_name))
            recipe.setIngredient(_research_char(symbol), material)
        return bool(Bukkit.addRecipe(recipe))
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-suit-recipe-" + str(piece),
            u"Cannot register isolation suit recipe",
            exc,
            120
        )
        return False


def _research_register_recipes(controller):
    recipes = (
        (
            u"helmet",
            ("WGW", "WHW", "SAS"),
            {"W": "WHITE_WOOL", "G": "GLASS_PANE", "H": "LEATHER_HELMET",
             "S": "SLIME_BALL", "A": "AMETHYST_SHARD"}
        ),
        (
            u"chest",
            ("WAW", "WCW", "SWS"),
            {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "C": "LEATHER_CHESTPLATE",
             "S": "SLIME_BALL"}
        ),
        (
            u"legs",
            ("WAW", "WLW", "SWS"),
            {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "L": "LEATHER_LEGGINGS",
             "S": "SLIME_BALL"}
        ),
        (
            u"boots",
            ("WAW", "WBW", "SWS"),
            {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "B": "LEATHER_BOOTS",
             "S": "SLIME_BALL"}
        )
    )
    ok = 0
    for piece, rows, ingredients in recipes:
        if _research_add_recipe(controller, piece, rows, ingredients):
            ok += 1
    log_action(u"Isolation Suit Mk.I recipes registered: {0}/4.".format(ok))


def _research_print_recipe(sender):
    send_message(sender, AnomalyConfig.PREFIX + u"&eРецепт Изоляционного костюма Mk.I")
    send_message(sender, u"&7Шлем: &fWGW / WHW / SAS")
    send_message(sender, u"&7Остальные части: &fWAW / W?W / SWS")
    send_message(sender, u"&8? = C нагрудник, L поножи, B ботинки (кожаная база)")
    send_message(sender, u"&8W=белая шерсть, A=осколок аметиста, S=слизь, G=стеклянная панель")
    return True


# ---------------------------------------------------------------------------
# laboratory pods / safe comparative trial
# ---------------------------------------------------------------------------


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
            AnomalyConfig.PREFIX +
            u"&cКоманду нужно выполнить игроком внутри нужной лабораторной колбы."
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
    log_action(u"Research lab pod {0} configured.".format(pod_id))
    return True


def _research_lab_status(controller, sender):
    pods = _research_root(controller).get("lab_pods", {})
    for pod_id in ("1", "2"):
        pod = pods.get(pod_id)
        if not isinstance(pod, dict):
            send_message(sender, AnomalyConfig.PREFIX + u"&7Колба {0}: &cне задана".format(pod_id))
            continue
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
    return True


def _research_pod_occupant(controller, pod_id):
    pod = _research_root(controller).get("lab_pods", {}).get(pod_id)
    if not isinstance(pod, dict):
        return None
    world_name = to_unicode(pod.get("world") or u"")
    best = None
    best_sq = RESEARCH_LAB_RADIUS * RESEARCH_LAB_RADIUS
    try:
        players = list(Bukkit.getOnlinePlayers())
    except Exception:
        players = []
    for player in players:
        try:
            loc = player.getLocation()
            if to_unicode(loc.getWorld().getName()) != world_name:
                continue
            dx = float(loc.getX()) - float(pod.get("x"))
            dy = float(loc.getY()) - float(pod.get("y"))
            dz = float(loc.getZ()) - float(pod.get("z"))
            dist_sq = dx * dx + dy * dy + dz * dz
            if dist_sq <= best_sq:
                best = player
                best_sq = dist_sq
        except Exception:
            continue
    return best


def _research_lab_test(controller, sender, trials):
    pod1 = _research_pod_occupant(controller, "1")
    pod2 = _research_pod_occupant(controller, "2")
    if pod1 is None or pod2 is None:
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&cДля опыта в обеих настроенных колбах должен находиться онлайн-игрок."
        )
        return True

    r1 = controller.record(pod1)
    r2 = controller.record(pod2)

    infectious1 = isinstance(r1, dict) and safe_int(r1.get("stage"), 1, 1, 3) >= 2
    infectious2 = isinstance(r2, dict) and safe_int(r2.get("stage"), 1, 1, 3) >= 2
    healthy1 = r1 is None
    healthy2 = r2 is None

    if infectious1 and healthy2:
        source = pod1
        target = pod2
    elif infectious2 and healthy1:
        source = pod2
        target = pod1
    else:
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&eДля сравнительного теста нужна одна здоровая цель и один заразный носитель S2/S3."
        )
        send_message(
            sender,
            u"&8Колба 1: {0}; колба 2: {1}.".format(
                u"здоров" if r1 is None else u"S{0}".format(safe_int(r1.get("stage"), 1)),
                u"здоров" if r2 is None else u"S{0}".format(safe_int(r2.get("stage"), 1))
            )
        )
        return True

    trials = safe_int(trials, RESEARCH_LAB_DEFAULT_TRIALS)
    trials = max(1, min(RESEARCH_LAB_MAX_TRIALS, trials))
    suit = _research_suit_state(controller, target)
    factor = RESEARCH_SUIT_CONTACT_FACTOR if suit["full"] else 1.0
    chance = RESEARCH_LAB_BASE_CHANCE * factor

    reactions = 0
    for _unused in range(trials):
        if random.random() < chance:
            reactions += 1

    try:
        controller._particles(target, False, random.randint(3, 7))
        controller._play_private(
            target,
            ("BLOCK_SCULK_SENSOR_CLICKING", "AMBIENT_CAVE"),
            0.20
        )
    except Exception:
        pass

    send_message(
        sender,
        AnomalyConfig.PREFIX +
        u"&7Контрольный опыт: источник=&f{0}&7, цель=&f{1}&7, полный костюм=&f{2}&7, реакций=&f{3}/{4}&7.".format(
            source.getName(),
            target.getName(),
            u"ДА" if suit["full"] else u"НЕТ",
            reactions,
            trials
        )
    )
    send_message(
        sender,
        u"&8Опыт безопасный: состояние игроков и история заражений не изменяются."
    )
    send_message(target, u"&7Лабораторный цикл завершён. Результаты сняты исследователем.")
    log_action(
        u"Research contact trial: source={0}, target={1}, full_suit={2}, reactions={3}/{4}.".format(
            source.getName(), target.getName(), suit["full"], reactions, trials
        )
    )
    return True


# ---------------------------------------------------------------------------
# CONTACT transmission override
# ---------------------------------------------------------------------------


try:
    _research_base_admin = AnomalyInfectionController._admin

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
            chance *= _research_contact_factor(self, target)
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

            if sub in ("suit", "gasmask"):
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7/anomaly infection suit give <игрок> | status <игрок> | recipe"
                    )
                    return True
                action = to_unicode(args[1]).lower()

                if action == "recipe":
                    return _research_print_recipe(sender)

                if action in ("give", "status"):
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите онлайн-игрока.")
                        return True
                    player = self._online(args[2])
                    if player is None:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                        return True
                    if action == "give":
                        return _research_give_set(self, sender, player)

                    state = _research_suit_state(self, player)
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7{0}: H={1} C={2} L={3} B={4}; полная защита=&f{5}&7.".format(
                            player.getName(),
                            int(state["helmet"]), int(state["chest"]),
                            int(state["legs"]), int(state["boots"]),
                            u"ДА" if state["full"] else u"НЕТ"
                        )
                    )
                    return True

            if sub == "lab":
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7/anomaly infection lab set <1|2> | status"
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
                trials = args[1] if len(args) >= 2 else RESEARCH_LAB_DEFAULT_TRIALS
                return _research_lab_test(self, sender, trials)

        return _research_base_admin(self, sender, args)

    AnomalyInfectionController._contact_spread = _research_contact_spread
    AnomalyInfectionController._admin = _research_admin

    if infection_controller is not None:
        _research_root(infection_controller)
        _research_register_recipes(infection_controller)

    log_action(
        u"Research extension installed: Isolation Suit Mk.I, CONTACT x0.05 only, four recipes, two safe lab pods."
    )
except Exception as _research_install_error:
    try:
        log_error(u"Cannot install anomaly research extension", _research_install_error)
    except Exception:
        pass
