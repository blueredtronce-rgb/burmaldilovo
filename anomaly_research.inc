# -*- coding: utf-8 -*-
"""
Protective-research extension for SmartY-Anomalies.
Loaded by anomaly.py after anomaly_infection.inc.

Current research arc:
- Isolation Suit Mk.I: 95% lower CONTACT infection roll with a complete set.
- Isolation Suit Mk.II: 100% CONTACT protection while the complete seal survives.
  Mk.II keeps ordinary leather-armor durability and additionally wears down
  while standing close to infectious S2/S3 carriers.
- Two laboratory pods plus a physical lever terminal. Researchers can start a
  safe animated comparative test by pulling the configured lever; no admin
  command is needed for normal RP use.
- Resonator Mk.I mechanics are prebuilt but locked by default. Admin can unlock
  them only when the story reaches the diagnostic/resonance phase.
- Hidden admin helpers live under /anomaly infection suit|lab|labtest|research|resonator.

PySpigot / Jython 2.7 / Paper-Leaf 1.21.x.
"""

try:
    from org.bukkit import NamespacedKey as _ResearchKey, Color as _ResearchColor
    from org.bukkit.inventory import (
        ItemStack as _ResearchItemStack,
        ShapedRecipe as _ResearchShapedRecipe
    )
    from org.bukkit.persistence import PersistentDataType as _ResearchPDT
    from org.bukkit.event.player import PlayerInteractEvent, PlayerInteractEntityEvent
    from org.bukkit.event.block import Action as _ResearchAction
except Exception:
    _ResearchKey = None
    _ResearchColor = None
    _ResearchItemStack = None
    _ResearchShapedRecipe = None
    _ResearchPDT = None
    PlayerInteractEvent = None
    PlayerInteractEntityEvent = None
    _ResearchAction = None


# ---------------------------------------------------------------------------
# tuning
# ---------------------------------------------------------------------------

RESEARCH_SUIT1_VERSION = u"mk1"
RESEARCH_SUIT2_VERSION = u"mk2"

RESEARCH_SUIT1_CONTACT_FACTOR = 0.05      # 95% lower CONTACT roll
RESEARCH_SUIT2_CONTACT_FACTOR = 0.00      # complete Mk.II blocks CONTACT entirely

RESEARCH_LAB_RADIUS = 2.75
RESEARCH_LAB_BASE_CHANCE = 0.20
RESEARCH_LAB_DEFAULT_TRIALS = 100
RESEARCH_LAB_MAX_TRIALS = 300
RESEARCH_LAB_DURATION_SECONDS = 16
RESEARCH_LAB_TERMINAL_COOLDOWN = 6

RESEARCH_RESONATOR_VERSION = u"mk1"
RESEARCH_RESONATOR_COOLDOWN = 8

_RESEARCH_PIECES = (
    (u"helmet", "LEATHER_HELMET", u"Шлем"),
    (u"chest", "LEATHER_CHESTPLATE", u"Куртка"),
    (u"legs", "LEATHER_LEGGINGS", u"Брюки"),
    (u"boots", "LEATHER_BOOTS", u"Ботинки")
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

    unlocked = root.setdefault("unlocked", {})
    if not isinstance(unlocked, dict):
        unlocked = {}
        root["unlocked"] = unlocked
    unlocked.setdefault("suit1", True)
    unlocked.setdefault("suit2", False)
    unlocked.setdefault("resonator1", False)

    root.setdefault("lab_terminal", None)
    return root


def _research_is_unlocked(controller, key):
    return bool(_research_root(controller).get("unlocked", {}).get(key, False))


def _research_set_unlocked(controller, key, value):
    root = _research_root(controller)
    root["unlocked"][key] = bool(value)
    controller._save()


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


def _research_resonator_key(controller):
    return _research_key(controller, "anomaly_resonator")


def _research_recipe_key(controller, name):
    return _research_key(controller, "anomaly_research_" + str(name))


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


def _research_primary_hand(event):
    try:
        hand = event.getHand()
        if hand is None:
            return True
        return to_unicode(hand.name()) == u"HAND"
    except Exception:
        return True


# ---------------------------------------------------------------------------
# suit items
# ---------------------------------------------------------------------------


def _research_piece_info(piece):
    piece = to_unicode(piece).lower()
    for info in _RESEARCH_PIECES:
        if info[0] == piece:
            return info
    return None


def _research_create_piece(controller, version, piece):
    info = _research_piece_info(piece)
    if info is None or _ResearchItemStack is None:
        return None

    material = _research_material(info[1])
    if material is None:
        return None

    try:
        item = _ResearchItemStack(material, 1)
        meta = item.getItemMeta()
        if meta is None:
            return None

        if version == RESEARCH_SUIT2_VERSION:
            title = u"&f{0} герметичного костюма &bMk.II".format(info[2])
            lore = [
                u"&7Второй изоляционный прототип.",
                u"&8Контур работает только полным комплектом.",
                u"&8При контакте изоляция постепенно изнашивается.",
                u"&8Повреждение любой части нарушает герметичность."
            ]
            rgb = (213, 229, 232)
        else:
            title = u"&e{0} изоляционного костюма &7Mk.I".format(info[2])
            lore = [
                u"&7Экспериментальная многослойная изоляция.",
                u"&8Защита работает только полным комплектом.",
                u"&8Не является лекарством.",
                u"&8Исследовательский образец Mk.I."
            ]
            rgb = (226, 207, 67)

        meta.setDisplayName(colorize(title))
        try:
            meta.setLore(build_java_list([colorize(line) for line in lore]))
        except Exception:
            pass

        try:
            if _ResearchColor is not None and hasattr(meta, "setColor"):
                meta.setColor(_ResearchColor.fromRGB(rgb[0], rgb[1], rgb[2]))
        except Exception:
            pass

        key = _research_piece_key(controller)
        if key is None or _ResearchPDT is None:
            return None
        meta.getPersistentDataContainer().set(
            key,
            _ResearchPDT.STRING,
            to_java_string(version + u":" + to_unicode(piece).lower())
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
        return None, None
    try:
        meta = item.getItemMeta()
        if meta is None:
            return None, None
        key = _research_piece_key(controller)
        if key is None or _ResearchPDT is None:
            return None, None
        raw = meta.getPersistentDataContainer().get(key, _ResearchPDT.STRING)
        raw = to_unicode(raw or u"")
        parts = raw.split(u":", 1)
        if len(parts) != 2:
            return None, None
        version = parts[0].lower()
        piece = parts[1].lower()
        if version not in (RESEARCH_SUIT1_VERSION, RESEARCH_SUIT2_VERSION):
            return None, None
        if piece not in (u"helmet", u"chest", u"legs", u"boots"):
            return None, None
        return version, piece
    except Exception:
        return None, None


def _research_suit_state(controller, player):
    state = {
        "helmet": None,
        "chest": None,
        "legs": None,
        "boots": None,
        "full1": False,
        "full2": False
    }
    try:
        inventory = player.getInventory()
        version, piece = _research_item_piece(controller, inventory.getHelmet())
        state["helmet"] = version if piece == u"helmet" else None
        version, piece = _research_item_piece(controller, inventory.getChestplate())
        state["chest"] = version if piece == u"chest" else None
        version, piece = _research_item_piece(controller, inventory.getLeggings())
        state["legs"] = version if piece == u"legs" else None
        version, piece = _research_item_piece(controller, inventory.getBoots())
        state["boots"] = version if piece == u"boots" else None

        state["full1"] = all(
            state[name] == RESEARCH_SUIT1_VERSION
            for name in ("helmet", "chest", "legs", "boots")
        )
        state["full2"] = all(
            state[name] == RESEARCH_SUIT2_VERSION
            for name in ("helmet", "chest", "legs", "boots")
        )
    except Exception:
        pass
    return state


def _research_contact_factor(controller, player):
    state = _research_suit_state(controller, player)
    if state["full2"]:
        return RESEARCH_SUIT2_CONTACT_FACTOR
    if state["full1"]:
        return RESEARCH_SUIT1_CONTACT_FACTOR
    return 1.0


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


def _research_give_set(controller, sender, player, version):
    created = []
    for piece, _material_name, _display_name in _RESEARCH_PIECES:
        item = _research_create_piece(controller, version, piece)
        if item is None:
            send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось создать полный комплект.")
            return True
        created.append(item)

    try:
        for item in created:
            leftovers = player.getInventory().addItem(item)
            _research_drop_leftovers(player, leftovers)
        pretty = u"Mk.II" if version == RESEARCH_SUIT2_VERSION else u"Mk.I"
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&aИзоляционный костюм {0} выдан игроку &f{1}&a.".format(pretty, player.getName())
        )
        send_message(
            player,
            u"&eПолучен исследовательский комплект: &fИзоляционный костюм " + pretty
        )
        log_action(u"Isolation Suit {0} issued to {1}.".format(pretty, player.getName()))
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-suit-give",
            u"Cannot give isolation suit",
            exc,
            120
        )
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось выдать костюм.")
    return True


def _research_damage_mk2(controller, player, distance):
    state = _research_suit_state(controller, player)
    if not state["full2"]:
        return

    candidates = []
    try:
        inv = player.getInventory()
        slots = (
            (u"helmet", inv.getHelmet(), inv.setHelmet),
            (u"chest", inv.getChestplate(), inv.setChestplate),
            (u"legs", inv.getLeggings(), inv.setLeggings),
            (u"boots", inv.getBoots(), inv.setBoots)
        )
        for piece, item, setter in slots:
            version, found_piece = _research_item_piece(controller, item)
            if version == RESEARCH_SUIT2_VERSION and found_piece == piece:
                candidates.append((piece, item, setter))
    except Exception:
        return

    if not candidates:
        return

    piece, item, setter = random.choice(candidates)
    try:
        amount = 1
        if float(distance) <= 3.0:
            amount += 1
        if float(distance) <= 1.5:
            amount += 1

        meta = item.getItemMeta()
        if meta is None or not hasattr(meta, "getDamage") or not hasattr(meta, "setDamage"):
            return

        current = int(meta.getDamage())
        maximum = int(item.getType().getMaxDurability())
        new_damage = current + int(amount)

        if maximum > 0 and new_damage >= maximum:
            setter(None)
            try:
                sound = controller._sound("ENTITY_ITEM_BREAK")
                if sound is not None:
                    player.playSound(player.getLocation(), sound, 0.8, 1.0)
            except Exception:
                pass
            send_message(
                player,
                u"&cОдна из частей герметичного костюма разрушилась. Контур больше не защищает вас."
            )
            log_action(u"Isolation Suit Mk.II piece broke: {0} {1}.".format(
                player.getName(), piece
            ))
            return

        meta.setDamage(new_damage)
        item.setItemMeta(meta)
        setter(item)
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-suit2-wear",
            u"Cannot wear Isolation Suit Mk.II",
            exc,
            120
        )


# ---------------------------------------------------------------------------
# crafting recipes
# ---------------------------------------------------------------------------


def _research_add_recipe(controller, name, result, rows, ingredients):
    if _ResearchShapedRecipe is None or result is None:
        return False
    key = _research_recipe_key(controller, name)
    if key is None:
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
            "research-recipe-" + str(name),
            u"Cannot register research recipe",
            exc,
            120
        )
        return False


def _research_register_suit1_recipes(controller):
    specs = (
        (u"helmet", ("WGW", "WHW", "SAS"),
         {"W": "WHITE_WOOL", "G": "GLASS_PANE", "H": "LEATHER_HELMET",
          "S": "SLIME_BALL", "A": "AMETHYST_SHARD"}),
        (u"chest", ("WAW", "WCW", "SWS"),
         {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "C": "LEATHER_CHESTPLATE",
          "S": "SLIME_BALL"}),
        (u"legs", ("WAW", "WLW", "SWS"),
         {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "L": "LEATHER_LEGGINGS",
          "S": "SLIME_BALL"}),
        (u"boots", ("WAW", "WBW", "SWS"),
         {"W": "WHITE_WOOL", "A": "AMETHYST_SHARD", "B": "LEATHER_BOOTS",
          "S": "SLIME_BALL"})
    )
    ok = 0
    for piece, rows, ingredients in specs:
        if _research_add_recipe(
                controller,
                "suit1_" + str(piece),
                _research_create_piece(controller, RESEARCH_SUIT1_VERSION, piece),
                rows,
                ingredients):
            ok += 1
    return ok


def _research_register_suit2_recipes(controller):
    if not _research_is_unlocked(controller, "suit2"):
        return 0

    specs = (
        (u"helmet", ("CGC", "WHW", "SAS"),
         {"C": "COPPER_INGOT", "G": "GLASS_PANE", "W": "WHITE_WOOL",
          "H": "LEATHER_HELMET", "S": "SLIME_BALL", "A": "AMETHYST_SHARD"}),
        (u"chest", ("CAC", "WNW", "SHS"),
         {"C": "COPPER_INGOT", "A": "AMETHYST_SHARD", "W": "WHITE_WOOL",
          "N": "LEATHER_CHESTPLATE", "S": "SLIME_BALL", "H": "HONEYCOMB"}),
        (u"legs", ("CAC", "WLW", "SHS"),
         {"C": "COPPER_INGOT", "A": "AMETHYST_SHARD", "W": "WHITE_WOOL",
          "L": "LEATHER_LEGGINGS", "S": "SLIME_BALL", "H": "HONEYCOMB"}),
        (u"boots", ("CAC", "WBW", "SHS"),
         {"C": "COPPER_INGOT", "A": "AMETHYST_SHARD", "W": "WHITE_WOOL",
          "B": "LEATHER_BOOTS", "S": "SLIME_BALL", "H": "HONEYCOMB"})
    )
    ok = 0
    for piece, rows, ingredients in specs:
        if _research_add_recipe(
                controller,
                "suit2_" + str(piece),
                _research_create_piece(controller, RESEARCH_SUIT2_VERSION, piece),
                rows,
                ingredients):
            ok += 1
    return ok


def _research_create_resonator(controller):
    if _ResearchItemStack is None:
        return None
    material = _research_material("COMPASS")
    if material is None:
        return None
    try:
        item = _ResearchItemStack(material, 1)
        meta = item.getItemMeta()
        if meta is None:
            return None
        meta.setDisplayName(colorize(u"&dРезонатор &7Mk.I"))
        try:
            meta.setLore(build_java_list([
                colorize(u"&7Экспериментальный измеритель отклика."),
                colorize(u"&8ПКМ по человеку — провести измерение."),
                colorize(u"&8ПКМ в аномальной среде — измерить фон."),
                colorize(u"&8Не является медицинским диагнозом.")
            ]))
        except Exception:
            pass
        key = _research_resonator_key(controller)
        if key is None or _ResearchPDT is None:
            return None
        meta.getPersistentDataContainer().set(
            key, _ResearchPDT.STRING, to_java_string(RESEARCH_RESONATOR_VERSION)
        )
        item.setItemMeta(meta)
        return item
    except Exception:
        return None


def _research_register_resonator_recipe(controller):
    if not _research_is_unlocked(controller, "resonator1"):
        return False
    return _research_add_recipe(
        controller,
        "resonator1",
        _research_create_resonator(controller),
        ("ACA", "RSR", "AMA"),
        {"A": "AMETHYST_SHARD", "C": "COPPER_INGOT", "R": "REDSTONE",
         "S": "SCULK_SENSOR", "M": "COMPARATOR"}
    )


def _research_register_recipes(controller):
    ok1 = _research_register_suit1_recipes(controller)
    ok2 = _research_register_suit2_recipes(controller)
    okr = 1 if _research_register_resonator_recipe(controller) else 0
    log_action(u"Research recipes registered: suit1={0}/4 suit2={1}/4 resonator={2}/1.".format(
        ok1, ok2, okr
    ))


def _research_print_recipe(controller, sender, version):
    if version == RESEARCH_SUIT2_VERSION:
        if not _research_is_unlocked(controller, "suit2"):
            send_message(sender, AnomalyConfig.PREFIX + u"&eMk.II ещё не открыт в исследованиях.")
            return True
        send_message(sender, AnomalyConfig.PREFIX + u"&bРецепт герметичного костюма Mk.II")
        send_message(sender, u"&7Шлем: &fCGC / WHW / SAS")
        send_message(sender, u"&7Нагрудник: &fCAC / WNW / SHS")
        send_message(sender, u"&7Поножи: &fCAC / WLW / SHS")
        send_message(sender, u"&7Ботинки: &fCAC / WBW / SHS")
        send_message(sender, u"&8C=медь, G=стекло, W=шерсть, S=слизь, A=аметист, H=соты.")
        send_message(sender, u"&8H/N/L/B в центре = кожаная база соответствующей части.")
        return True

    send_message(sender, AnomalyConfig.PREFIX + u"&eРецепт Изоляционного костюма Mk.I")
    send_message(sender, u"&7Шлем: &fWGW / WHW / SAS")
    send_message(sender, u"&7Остальные части: &fWAW / W?W / SWS")
    send_message(sender, u"&8? = C нагрудник, L поножи, B ботинки (кожаная база)")
    send_message(sender, u"&8W=белая шерсть, A=аметист, S=слизь, G=стеклянная панель")
    return True


# ---------------------------------------------------------------------------
# laboratory pods / physical terminal
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


def _research_target_block(sender, distance):
    try:
        return sender.getTargetBlockExact(int(distance))
    except Exception:
        try:
            return sender.getLocation().getBlock()
        except Exception:
            return None


def _research_set_terminal(controller, sender):
    block = _research_target_block(sender, 6)
    if block is None:
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось определить блок.")
        return True
    lever = _research_material("LEVER")
    try:
        if lever is not None and block.getType() != lever:
            send_message(
                sender,
                AnomalyConfig.PREFIX +
                u"&cПосмотри прямо на рычаг лаборатории и повтори команду."
            )
            return True
        loc = block.getLocation()
        root = _research_root(controller)
        root["lab_terminal"] = {
            "world": to_unicode(loc.getWorld().getName()),
            "x": int(loc.getBlockX()),
            "y": int(loc.getBlockY()),
            "z": int(loc.getBlockZ())
        }
        controller._save()
        send_message(sender, AnomalyConfig.PREFIX + u"&aРычаг лабораторного терминала привязан.")
        log_action(u"Research lab terminal lever configured.")
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-lab-terminal-set",
            u"Cannot configure lab terminal",
            exc,
            120
        )
        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось привязать рычаг.")
    return True


def _research_block_matches_terminal(controller, block):
    if block is None:
        return False
    terminal = _research_root(controller).get("lab_terminal")
    if not isinstance(terminal, dict):
        return False
    try:
        loc = block.getLocation()
        return (
            to_unicode(loc.getWorld().getName()) == to_unicode(terminal.get("world")) and
            int(loc.getBlockX()) == int(terminal.get("x")) and
            int(loc.getBlockY()) == int(terminal.get("y")) and
            int(loc.getBlockZ()) == int(terminal.get("z"))
        )
    except Exception:
        return False


def _research_lab_status(controller, sender):
    root = _research_root(controller)
    pods = root.get("lab_pods", {})
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
    terminal = root.get("lab_terminal")
    if isinstance(terminal, dict):
        send_message(
            sender,
            AnomalyConfig.PREFIX +
            u"&7Терминал: &f{0} {1} {2} {3}".format(
                to_unicode(terminal.get("world") or u"?"),
                terminal.get("x"), terminal.get("y"), terminal.get("z")
            )
        )
    else:
        send_message(sender, AnomalyConfig.PREFIX + u"&7Терминал: &cне задан")
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


def _research_lab_pair(controller):
    pod1 = _research_pod_occupant(controller, "1")
    pod2 = _research_pod_occupant(controller, "2")
    if pod1 is None or pod2 is None:
        return None, None, u"Для запуска в обеих колбах должен находиться испытуемый."

    r1 = controller.record(pod1)
    r2 = controller.record(pod2)

    infectious1 = isinstance(r1, dict) and safe_int(r1.get("stage"), 1, 1, 3) >= 2
    infectious2 = isinstance(r2, dict) and safe_int(r2.get("stage"), 1, 1, 3) >= 2
    healthy1 = r1 is None
    healthy2 = r2 is None

    if infectious1 and healthy2:
        return pod1, pod2, None
    if infectious2 and healthy1:
        return pod2, pod1, None

    return None, None, u"Нужен один здоровый испытуемый и один носитель с выраженной активной фазой."


def _research_lab_factor(controller, target):
    state = _research_suit_state(controller, target)
    if state["full2"]:
        return 0.0, u"Mk.II"
    if state["full1"]:
        return RESEARCH_SUIT1_CONTACT_FACTOR, u"Mk.I"
    return 1.0, u"НЕТ"


def _research_lab_fx(controller, source, target, strong=False):
    try:
        controller._play_private(
            target,
            ("BLOCK_SCULK_SENSOR_CLICKING", "AMBIENT_CAVE"),
            0.22 if not strong else 0.35
        )
    except Exception:
        pass

    particle_names = (
        ("ELECTRIC_SPARK", "ENCHANT", "END_ROD")
        if strong else
        ("SCULK_SOUL", "SOUL", "ASH")
    )
    particle = None
    for name in particle_names:
        try:
            particle = getattr(Particle, name, None)
            if particle is not None:
                break
        except Exception:
            pass
    if particle is None:
        return

    for player in (source, target):
        try:
            loc = player.getLocation().clone().add(0.0, 1.0, 0.0)
            player.getWorld().spawnParticle(
                particle, loc, 10 if strong else 5,
                0.35, 0.65, 0.35, 0.02
            )
        except Exception:
            pass


def _research_finish_lab_session(controller):
    session = getattr(controller, "research_lab_session", None)
    if not isinstance(session, dict):
        return

    source = session.get("source")
    target = session.get("target")
    initiator = session.get("initiator")
    trials = safe_int(session.get("trials"), RESEARCH_LAB_DEFAULT_TRIALS)

    controller.research_lab_session = None
    controller.research_lab_next_fx = 0

    try:
        if source is None or target is None or not source.isOnline() or not target.isOnline():
            if initiator is not None and initiator.isOnline():
                send_message(initiator, u"&cИспытание остановлено: один из испытуемых покинул установку.")
            return
    except Exception:
        return

    factor, suit_name = _research_lab_factor(controller, target)
    chance = RESEARCH_LAB_BASE_CHANCE * factor
    reactions = 0
    for _unused in range(trials):
        if random.random() < chance:
            reactions += 1

    _research_lab_fx(controller, source, target, True)

    message = (
        u"&6[Лаборатория] &fЦикл завершён. "
        u"&7Источник: &f{0}&7; цель: &f{1}&7; защита: &f{2}&7; "
        u"зарегистрировано реакций: &f{3}/{4}&7."
    ).format(source.getName(), target.getName(), suit_name, reactions, trials)

    recipients = []
    for player in (initiator, source, target):
        if player is not None and player not in recipients:
            recipients.append(player)
    for player in recipients:
        try:
            if player.isOnline():
                send_message(player, message)
        except Exception:
            pass

    log_action(
        u"Research terminal trial: source={0}, target={1}, suit={2}, reactions={3}/{4}.".format(
            source.getName(), target.getName(), suit_name, reactions, trials
        )
    )


def _research_start_lab_session(controller, initiator):
    now = now_ts()
    last = safe_int(getattr(controller, "research_lab_last_start", 0), 0)
    if now - last < RESEARCH_LAB_TERMINAL_COOLDOWN:
        send_message(initiator, u"&7Лабораторный терминал ещё завершает предыдущий цикл.")
        return True

    if isinstance(getattr(controller, "research_lab_session", None), dict):
        send_message(initiator, u"&eЛабораторное испытание уже выполняется.")
        return True

    source, target, error = _research_lab_pair(controller)
    if error is not None:
        send_message(initiator, u"&c" + error)
        return True

    controller.research_lab_last_start = now
    controller.research_lab_next_fx = now
    controller.research_lab_session = {
        "started": now,
        "ends": now + RESEARCH_LAB_DURATION_SECONDS,
        "source": source,
        "target": target,
        "initiator": initiator,
        "trials": RESEARCH_LAB_DEFAULT_TRIALS
    }

    send_message(
        initiator,
        u"&6[Лаборатория] &fИспытательный цикл запущен. Не открывайте камеры до завершения."
    )
    try:
        send_message(source, u"&7Лабораторная аппаратура начинает цикл наблюдения.")
        send_message(target, u"&7Лабораторная аппаратура начинает цикл наблюдения.")
    except Exception:
        pass

    _research_lab_fx(controller, source, target, False)
    return True


def _research_lab_tick(controller):
    session = getattr(controller, "research_lab_session", None)
    if not isinstance(session, dict):
        return
    now = now_ts()
    source = session.get("source")
    target = session.get("target")

    try:
        if source is None or target is None or not source.isOnline() or not target.isOnline():
            _research_finish_lab_session(controller)
            return
    except Exception:
        _research_finish_lab_session(controller)
        return

    if now >= safe_int(session.get("ends"), now):
        _research_finish_lab_session(controller)
        return

    next_fx = safe_int(getattr(controller, "research_lab_next_fx", 0), 0)
    if now >= next_fx:
        controller.research_lab_next_fx = now + 2
        _research_lab_fx(controller, source, target, False)


def _research_lab_test(controller, sender, trials):
    source, target, error = _research_lab_pair(controller)
    if error is not None:
        send_message(sender, AnomalyConfig.PREFIX + u"&c" + error)
        return True

    trials = safe_int(trials, RESEARCH_LAB_DEFAULT_TRIALS)
    trials = max(1, min(RESEARCH_LAB_MAX_TRIALS, trials))
    factor, suit_name = _research_lab_factor(controller, target)
    chance = RESEARCH_LAB_BASE_CHANCE * factor

    reactions = 0
    for _unused in range(trials):
        if random.random() < chance:
            reactions += 1

    send_message(
        sender,
        AnomalyConfig.PREFIX +
        u"&7Контрольный опыт: источник=&f{0}&7, цель=&f{1}&7, защита=&f{2}&7, реакций=&f{3}/{4}&7.".format(
            source.getName(), target.getName(), suit_name, reactions, trials
        )
    )
    send_message(sender, u"&8Опыт безопасный: состояние игроков и история заражений не изменяются.")
    return True


# ---------------------------------------------------------------------------
# Resonator Mk.I (prebuilt, story-locked)
# ---------------------------------------------------------------------------


def _research_is_resonator(controller, item):
    if item is None:
        return False
    try:
        meta = item.getItemMeta()
        if meta is None:
            return False
        key = _research_resonator_key(controller)
        if key is None or _ResearchPDT is None:
            return False
        raw = meta.getPersistentDataContainer().get(key, _ResearchPDT.STRING)
        return to_unicode(raw or u"").lower() == RESEARCH_RESONATOR_VERSION
    except Exception:
        return False


def _research_resonator_ready(controller, player):
    if not _research_is_unlocked(controller, "resonator1"):
        return False
    if not hasattr(controller, "research_resonator_cooldowns"):
        controller.research_resonator_cooldowns = {}
    uid = controller.uid(player)
    now = now_ts()
    if now < safe_int(controller.research_resonator_cooldowns.get(uid), 0):
        return False
    controller.research_resonator_cooldowns[uid] = now + RESEARCH_RESONATOR_COOLDOWN
    return True


def _research_resonator_feedback(controller, user, text):
    send_message(user, u"&d[Резонатор] &f" + text)
    try:
        sound = controller._sound("BLOCK_AMETHYST_BLOCK_RESONATE")
        if sound is None:
            sound = controller._sound("BLOCK_AMETHYST_BLOCK_CHIME")
        if sound is not None:
            user.playSound(user.getLocation(), sound, 0.65, random.uniform(0.85, 1.15))
    except Exception:
        pass


def _research_scan_player(controller, user, target):
    if not _research_resonator_ready(controller, user):
        return
    record = controller.record(target)
    if record is None:
        text = u"{0}: фон стабилен, выраженный отклик не обнаружен.".format(target.getName())
    else:
        stage = safe_int(record.get("stage"), 1, 1, 3)
        if stage <= 1:
            level = u"слабое нестабильное отклонение"
        elif stage == 2:
            level = u"устойчивый выраженный отклик"
        else:
            level = u"сильный насыщенный отклик"
        text = u"{0}: {1}.".format(target.getName(), level)
    _research_resonator_feedback(controller, user, text)


def _research_scan_environment(controller, user):
    if not _research_resonator_ready(controller, user):
        return
    try:
        anomaly = controller.manager.anomaly_at_location(user.getLocation())
    except Exception:
        anomaly = None
    if anomaly is None:
        _research_resonator_feedback(controller, user, u"Окружающий фон стабилен.")
    else:
        _research_resonator_feedback(
            controller, user,
            u"Окружающая среда даёт сильный устойчивый отклик. Источник локализован рядом."
        )


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def _research_on_interact(controller, event):
    try:
        if _ResearchAction is None or not _research_primary_hand(event):
            return
        player = event.getPlayer()
        action = event.getAction()

        if action == _ResearchAction.RIGHT_CLICK_BLOCK:
            block = event.getClickedBlock()
            if _research_block_matches_terminal(controller, block):
                _research_start_lab_session(controller, player)
                return

        item = event.getItem()
        if _research_is_resonator(controller, item):
            if action in (_ResearchAction.RIGHT_CLICK_AIR, _ResearchAction.RIGHT_CLICK_BLOCK):
                _research_scan_environment(controller, player)
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-interact",
            u"Research interaction handler failed",
            exc,
            120
        )


def _research_on_interact_entity(controller, event):
    try:
        if not _research_primary_hand(event):
            return
        player = event.getPlayer()
        target = event.getRightClicked()
        if target is None or not isinstance(target, Player):
            return
        item = player.getInventory().getItemInMainHand()
        if not _research_is_resonator(controller, item):
            return
        _research_scan_player(controller, player, target)
    except Exception as exc:
        controller.manager.log_error_throttled(
            "research-interact-entity",
            u"Resonator player scan failed",
            exc,
            120
        )


# ---------------------------------------------------------------------------
# CONTACT transmission override + admin controls
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

            state = _research_suit_state(self, target)

            # Mk.II is a perfect CONTACT barrier while all four pieces survive.
            # Exposure itself wears the seal down; once a part breaks the next
            # normal infection cycle can affect the player.
            if state["full2"]:
                _research_damage_mk2(self, target, nearest_distance)
                continue

            chance = self._contact_chance(nearest_distance)
            if state["full1"]:
                chance *= RESEARCH_SUIT1_CONTACT_FACTOR

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
                        u"&7/anomaly infection suit give <игрок> [1|2] | status <игрок> | recipe [1|2]"
                    )
                    return True

                action = to_unicode(args[1]).lower()

                if action == "recipe":
                    version = RESEARCH_SUIT2_VERSION if len(args) >= 3 and args[2] == "2" else RESEARCH_SUIT1_VERSION
                    return _research_print_recipe(self, sender, version)

                if action in ("give", "status"):
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите онлайн-игрока.")
                        return True
                    player = self._online(args[2])
                    if player is None:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                        return True

                    if action == "give":
                        version = RESEARCH_SUIT2_VERSION if len(args) >= 4 and args[3] == "2" else RESEARCH_SUIT1_VERSION
                        return _research_give_set(self, sender, player, version)

                    state = _research_suit_state(self, player)
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7{0}: H={1} C={2} L={3} B={4}; Mk.I=&f{5}&7; Mk.II=&f{6}&7.".format(
                            player.getName(),
                            state["helmet"] or "-",
                            state["chest"] or "-",
                            state["legs"] or "-",
                            state["boots"] or "-",
                            u"ДА" if state["full1"] else u"НЕТ",
                            u"ДА" if state["full2"] else u"НЕТ"
                        )
                    )
                    return True

            if sub == "lab":
                if len(args) < 2:
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7/anomaly infection lab set <1|2> | terminal set | status"
                    )
                    return True
                action = to_unicode(args[1]).lower()
                if action == "set":
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите колбу 1 или 2.")
                        return True
                    return _research_set_pod(self, sender, to_unicode(args[2]))
                if action == "terminal":
                    if len(args) >= 3 and to_unicode(args[2]).lower() == "set":
                        return _research_set_terminal(self, sender)
                    return _research_lab_status(self, sender)
                if action == "status":
                    return _research_lab_status(self, sender)

            if sub == "labtest":
                trials = args[1] if len(args) >= 2 else RESEARCH_LAB_DEFAULT_TRIALS
                return _research_lab_test(self, sender, trials)

            if sub == "research":
                if len(args) < 2 or to_unicode(args[1]).lower() == "status":
                    root = _research_root(self)
                    unlocked = root.get("unlocked", {})
                    send_message(
                        sender,
                        AnomalyConfig.PREFIX +
                        u"&7Research: suit1=&f{0}&7 suit2=&f{1}&7 resonator1=&f{2}&7.".format(
                            int(bool(unlocked.get("suit1"))),
                            int(bool(unlocked.get("suit2"))),
                            int(bool(unlocked.get("resonator1")))
                        )
                    )
                    return True
                if to_unicode(args[1]).lower() == "unlock" and len(args) >= 3:
                    key = to_unicode(args[2]).lower()
                    if key not in ("suit2", "resonator1"):
                        send_message(
                            sender,
                            AnomalyConfig.PREFIX +
                            u"&cДоступно: suit2, resonator1."
                        )
                        return True
                    _research_set_unlocked(self, key, True)
                    if key == "suit2":
                        count = _research_register_suit2_recipes(self)
                        send_message(
                            sender,
                            AnomalyConfig.PREFIX +
                            u"&aMk.II открыт. Зарегистрировано рецептов: {0}/4.".format(count)
                        )
                    else:
                        ok = _research_register_resonator_recipe(self)
                        send_message(
                            sender,
                            AnomalyConfig.PREFIX +
                            (u"&aРезонатор Mk.I открыт и рецепт зарегистрирован."
                             if ok else
                             u"&eРезонатор открыт, но рецепт не удалось зарегистрировать.")
                        )
                    return True

            if sub == "resonator":
                if len(args) >= 2 and to_unicode(args[1]).lower() == "give":
                    if len(args) < 3:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cУкажите онлайн-игрока.")
                        return True
                    player = self._online(args[2])
                    if player is None:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cИгрок должен быть онлайн.")
                        return True
                    item = _research_create_resonator(self)
                    if item is None:
                        send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось создать резонатор.")
                        return True
                    leftovers = player.getInventory().addItem(item)
                    _research_drop_leftovers(player, leftovers)
                    send_message(sender, AnomalyConfig.PREFIX + u"&aРезонатор выдан.")
                    return True
                send_message(
                    sender,
                    AnomalyConfig.PREFIX +
                    u"&7/anomaly infection resonator give <игрок>"
                )
                return True

        return _research_base_admin(self, sender, args)

    AnomalyInfectionController._contact_spread = _research_contact_spread
    AnomalyInfectionController._admin = _research_admin

    if infection_controller is not None:
        _research_root(infection_controller)
        infection_controller.research_lab_session = None
        infection_controller.research_lab_next_fx = 0
        infection_controller.research_lab_last_start = 0
        infection_controller.research_resonator_cooldowns = {}

        _research_register_recipes(infection_controller)

        if PlayerInteractEvent is not None:
            infection_controller._register_event(
                PlayerInteractEvent,
                lambda event: _research_on_interact(infection_controller, event),
                EventPriority.NORMAL
            )
        if PlayerInteractEntityEvent is not None:
            infection_controller._register_event(
                PlayerInteractEntityEvent,
                lambda event: _research_on_interact_entity(infection_controller, event),
                EventPriority.NORMAL
            )

        def _research_repeating_tick():
            try:
                _research_lab_tick(infection_controller)
            except Exception as exc:
                infection_controller.manager.log_error_throttled(
                    "research-lab-tick",
                    u"Research lab animation tick failed",
                    exc,
                    120
                )

        infection_controller._schedule(_research_repeating_tick, 20, 20)

    log_action(
        u"Research extension installed: Suit Mk.I, degradable 100% CONTACT Suit Mk.II, "
        u"physical lab lever terminal, locked Resonator Mk.I."
    )
except Exception as _research_install_error:
    try:
        log_error(u"Cannot install anomaly research extension", _research_install_error)
    except Exception:
        pass
