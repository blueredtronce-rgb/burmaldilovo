# -*- coding: utf-8 -*-
"""
Teleport Bells for PySpigot / Paper 1.21.11

Each configured bell has:
- a unique id;
- one placed bell block;
- its own teleport destination;
- its own nickname whitelist.

Admin commands:
  /bell create <id>
  /bell delete <id>
  /bell give <id> [player]
  /bell setdest <id>
  /bell setdest <id> <x> <y> <z> [world]
  /bell add <id> <nickname>
  /bell remove <id> <nickname>
  /bell info <id>
  /bell list

Flow:
1. /bell create citybar
2. /bell setdest citybar          (stand at destination)
3. /bell add citybar PlayerName
4. /bell give citybar
5. Place the issued bell. Its block coordinates are saved automatically.
6. Allowed players right-click that exact bell and are teleported.

Ordinary bells do nothing. Non-whitelisted players can ring a teleport bell normally
and receive no hint that it has a hidden function.
"""

import os
import re
import json
import codecs

import pyspigot as ps

cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

try:
    unicode
except NameError:
    unicode = str

from org.bukkit import Bukkit, Material, Location, NamespacedKey
from org.bukkit.entity import Player
from org.bukkit.event.block import Action, BlockBreakEvent, BlockPlaceEvent
from org.bukkit.event.player import PlayerInteractEvent, PlayerCommandSendEvent
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.persistence import PersistentDataType
from java.util import ArrayList


# =============================================================================
# CONSTANTS
# =============================================================================

PLUGIN_TAG = u"§6[TeleportBells]§r "
ADMIN_PERMISSION = "burmaldilovo.teleportbells.admin"

DATA_DIR = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE = os.path.join(DATA_DIR, "teleport_bells.json")

KEY_BELL_ID = NamespacedKey.fromString("burmaldilovo:teleport_bell_id")

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PLAYER_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

_data = {
    "version": 1,
    "bells": {}
}


# =============================================================================
# UTILITIES
# =============================================================================

def java_list(values):
    result = ArrayList()
    for value in values:
        result.add(value)
    return result


def send(sender, text):
    try:
        sender.sendMessage(PLUGIN_TAG + text)
    except Exception:
        Bukkit.getLogger().info("[TeleportBells] " + unicode(text))


def log_info(text):
    Bukkit.getLogger().info("[TeleportBells] " + unicode(text))


def log_warn(text):
    Bukkit.getLogger().warning("[TeleportBells] " + unicode(text))


def is_admin(sender):
    # Console and command blocks are trusted server-side senders.
    if not isinstance(sender, Player):
        return True
    try:
        if sender.isOp():
            return True
    except Exception:
        pass
    try:
        return sender.hasPermission(ADMIN_PERMISSION)
    except Exception:
        return False


def normalize_id(value):
    if value is None:
        return None
    value = unicode(value).strip().lower()
    if not ID_RE.match(value):
        return None
    return value


def normalize_player_name(value):
    if value is None:
        return None
    value = unicode(value).strip()
    if not PLAYER_RE.match(value):
        return None
    return value.lower()


def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def default_bell_entry():
    return {
        "allowed_names": [],
        "destination": None,
        "block": None
    }


def sanitize_loaded_data(raw):
    result = {"version": 1, "bells": {}}
    if not isinstance(raw, dict):
        return result
    bells = raw.get("bells")
    if not isinstance(bells, dict):
        return result

    for raw_id, raw_entry in bells.items():
        bell_id = normalize_id(raw_id)
        if bell_id is None or not isinstance(raw_entry, dict):
            continue

        entry = default_bell_entry()

        names = raw_entry.get("allowed_names", [])
        if isinstance(names, list):
            clean_names = []
            seen = set()
            for name in names:
                normalized = normalize_player_name(name)
                if normalized is not None and normalized not in seen:
                    seen.add(normalized)
                    clean_names.append(normalized)
            entry["allowed_names"] = clean_names

        destination = raw_entry.get("destination")
        if isinstance(destination, dict):
            try:
                entry["destination"] = {
                    "world": unicode(destination.get("world")),
                    "x": float(destination.get("x")),
                    "y": float(destination.get("y")),
                    "z": float(destination.get("z")),
                    "yaw": float(destination.get("yaw", 0.0)),
                    "pitch": float(destination.get("pitch", 0.0))
                }
            except Exception:
                entry["destination"] = None

        block = raw_entry.get("block")
        if isinstance(block, dict):
            try:
                entry["block"] = {
                    "world": unicode(block.get("world")),
                    "x": int(block.get("x")),
                    "y": int(block.get("y")),
                    "z": int(block.get("z"))
                }
            except Exception:
                entry["block"] = None

        result["bells"][bell_id] = entry

    return result


def load_data():
    global _data
    ensure_data_dir()

    if not os.path.exists(DATA_FILE):
        _data = {"version": 1, "bells": {}}
        save_data()
        return

    try:
        handle = codecs.open(DATA_FILE, "r", "utf-8")
        raw_text = handle.read()
        handle.close()
        _data = sanitize_loaded_data(json.loads(raw_text))
        log_info("Loaded {0} teleport bell(s).".format(len(_data["bells"])))
    except Exception as ex:
        log_warn("Could not load teleport_bells.json: " + str(ex))
        _data = {"version": 1, "bells": {}}


def save_data():
    ensure_data_dir()
    tmp_path = DATA_FILE + ".tmp"
    try:
        handle = codecs.open(tmp_path, "w", "utf-8")
        handle.write(json.dumps(_data, ensure_ascii=False, indent=2, sort_keys=True))
        handle.close()

        # Linux/Jython: os.rename atomically replaces only when destination is absent,
        # so remove the old tiny config after the temp file is fully written.
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(tmp_path, DATA_FILE)
        return True
    except Exception as ex:
        log_warn("Could not save teleport_bells.json: " + str(ex))
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def loc_to_destination(loc):
    return {
        "world": unicode(loc.getWorld().getName()),
        "x": float(loc.getX()),
        "y": float(loc.getY()),
        "z": float(loc.getZ()),
        "yaw": float(loc.getYaw()),
        "pitch": float(loc.getPitch())
    }


def destination_to_loc(data):
    if not isinstance(data, dict):
        return None
    world = Bukkit.getWorld(data.get("world"))
    if world is None:
        return None
    try:
        return Location(
            world,
            float(data.get("x")),
            float(data.get("y")),
            float(data.get("z")),
            float(data.get("yaw", 0.0)),
            float(data.get("pitch", 0.0))
        )
    except Exception:
        return None


def block_to_dict(block):
    return {
        "world": unicode(block.getWorld().getName()),
        "x": int(block.getX()),
        "y": int(block.getY()),
        "z": int(block.getZ())
    }


def same_block(block, data):
    if not isinstance(data, dict):
        return False
    try:
        return (
            unicode(block.getWorld().getName()) == unicode(data.get("world")) and
            int(block.getX()) == int(data.get("x")) and
            int(block.getY()) == int(data.get("y")) and
            int(block.getZ()) == int(data.get("z"))
        )
    except Exception:
        return False


def bell_id_at_block(block):
    if block is None or block.getType() != Material.BELL:
        return None
    for bell_id, entry in _data.get("bells", {}).items():
        if same_block(block, entry.get("block")):
            return bell_id
    return None


# =============================================================================
# SPECIAL BELL ITEM
# =============================================================================

def create_bell_item(bell_id):
    item = ItemStack(Material.BELL, 1)
    meta = item.getItemMeta()
    meta.setDisplayName(u"§6§lКолокол перехода §8[§e" + bell_id + u"§8]")
    meta.setLore(java_list([
        u"§7Служебный колокол телепортации.",
        u"§7ID: §f" + bell_id,
        u"",
        u"§8После установки координаты блока",
        u"§8привязываются к этому ID автоматически."
    ]))
    meta.getPersistentDataContainer().set(KEY_BELL_ID, PersistentDataType.STRING, bell_id)
    item.setItemMeta(meta)
    return item


def item_bell_id(item):
    if item is None or item.getType() != Material.BELL:
        return None
    try:
        meta = item.getItemMeta()
        if meta is None:
            return None
        pdc = meta.getPersistentDataContainer()
        if not pdc.has(KEY_BELL_ID, PersistentDataType.STRING):
            return None
        value = pdc.get(KEY_BELL_ID, PersistentDataType.STRING)
        return normalize_id(value)
    except Exception:
        return None


def give_item_safely(player, item):
    leftovers = player.getInventory().addItem(item)
    if leftovers is not None and not leftovers.isEmpty():
        for leftover in leftovers.values():
            player.getWorld().dropItemNaturally(player.getLocation(), leftover)


# =============================================================================
# EVENT HANDLERS
# =============================================================================

def on_bell_place(event):
    try:
        item = event.getItemInHand()
        bell_id = item_bell_id(item)
        if bell_id is None:
            return

        player = event.getPlayer()
        if not is_admin(player):
            event.setCancelled(True)
            return

        entry = _data.get("bells", {}).get(bell_id)
        if entry is None:
            event.setCancelled(True)
            send(player, u"§cЭтот колокол имеет неизвестный ID: §f" + bell_id)
            return

        block = event.getBlockPlaced()
        if block is None or block.getType() != Material.BELL:
            return

        old_block = entry.get("block")
        entry["block"] = block_to_dict(block)
        if not save_data():
            entry["block"] = old_block
            event.setCancelled(True)
            send(player, u"§cНе удалось сохранить привязку колокола.")
            return

        b = entry["block"]
        send(player, u"§aКолокол §e{0} §aпривязан: §f{1} {2} {3} §7({4})".format(
            bell_id, b["x"], b["y"], b["z"], b["world"]
        ))
    except Exception as ex:
        log_warn("BlockPlaceEvent error: " + str(ex))


def on_bell_break(event):
    try:
        block = event.getBlock()
        bell_id = bell_id_at_block(block)
        if bell_id is None:
            return

        player = event.getPlayer()
        if not is_admin(player):
            event.setCancelled(True)
            return

        entry = _data["bells"].get(bell_id)
        if entry is None:
            return

        old_block = entry.get("block")
        entry["block"] = None
        if not save_data():
            entry["block"] = old_block
            event.setCancelled(True)
            send(player, u"§cНе удалось сохранить отвязку колокола.")
            return

        # Preserve the hidden ID when an admin moves the bell.
        try:
            event.setDropItems(False)
        except Exception:
            pass
        give_item_safely(player, create_bell_item(bell_id))
        send(player, u"§7Колокол §e" + bell_id + u" §7отвязан и возвращён в инвентарь.")
    except Exception as ex:
        log_warn("BlockBreakEvent error: " + str(ex))


def on_bell_interact(event):
    try:
        hand = event.getHand()
        if hand is not None and hand != EquipmentSlot.HAND:
            return

        if event.getAction() != Action.RIGHT_CLICK_BLOCK:
            return

        block = event.getClickedBlock()
        bell_id = bell_id_at_block(block)
        if bell_id is None:
            return

        player = event.getPlayer()
        entry = _data["bells"].get(bell_id)
        if entry is None:
            return

        # Secret behavior: unauthorized players simply ring the bell as usual.
        player_name = unicode(player.getName()).lower()
        allowed = entry.get("allowed_names", [])
        if player_name not in allowed:
            return

        destination_data = entry.get("destination")
        destination = destination_to_loc(destination_data)
        if destination is None:
            send(player, u"§cДля этого колокола не настроена доступная точка телепортации.")
            return

        # One tick delay lets the normal bell ring/animation happen before teleport.
        def do_teleport():
            try:
                if player.isOnline():
                    fresh_destination = destination_to_loc(entry.get("destination"))
                    if fresh_destination is not None:
                        player.teleport(fresh_destination)
            except Exception as ex:
                log_warn("Teleport error for bell {0}: {1}".format(bell_id, ex))

        scheduler.runTaskLater(do_teleport, 1)
    except Exception as ex:
        log_warn("PlayerInteractEvent error: " + str(ex))


def on_command_send(event):
    try:
        player = event.getPlayer()
        if is_admin(player):
            return
        commands = event.getCommands()
        commands.remove("bell")
    except Exception:
        pass


# =============================================================================
# COMMANDS
# =============================================================================

def send_help(sender):
    send(sender, u"§e/bell create <id> §7— создать колокол")
    send(sender, u"§e/bell give <id> [игрок] §7— выдать специальный колокол")
    send(sender, u"§e/bell setdest <id> §7— поставить точку назначения на текущую позицию")
    send(sender, u"§e/bell setdest <id> <x> <y> <z> [world] §7— задать координаты вручную")
    send(sender, u"§e/bell add <id> <ник> §7— разрешить игроку телепорт")
    send(sender, u"§e/bell remove <id> <ник> §7— убрать игрока")
    send(sender, u"§e/bell info <id> §7— информация")
    send(sender, u"§e/bell list §7— список")
    send(sender, u"§e/bell delete <id> §7— удалить настройку")


def require_bell(sender, raw_id):
    bell_id = normalize_id(raw_id)
    if bell_id is None:
        send(sender, u"§cНекорректный ID. Разрешены A-Z, a-z, 0-9, _ и -, максимум 32 символа.")
        return None, None
    entry = _data.get("bells", {}).get(bell_id)
    if entry is None:
        send(sender, u"§cКолокол §f" + bell_id + u" §cне существует. Сначала: §f/bell create " + bell_id)
        return None, None
    return bell_id, entry


def cmd_bell(sender, label, args):
    if not is_admin(sender):
        # Do not reveal the hidden admin system to normal players.
        try:
            sender.sendMessage(u"§cНеизвестная команда.")
        except Exception:
            pass
        return True

    args = list(args)
    if len(args) == 0 or unicode(args[0]).lower() in (u"help", u"помощь", u"?"):
        send_help(sender)
        return True

    sub = unicode(args[0]).lower()

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------
    if sub in (u"create", u"создать"):
        if len(args) < 2:
            send(sender, u"§cИспользование: §f/bell create <id>")
            return True
        bell_id = normalize_id(args[1])
        if bell_id is None:
            send(sender, u"§cНекорректный ID. Разрешены A-Z, a-z, 0-9, _ и -, максимум 32 символа.")
            return True
        if bell_id in _data["bells"]:
            send(sender, u"§cКолокол с ID §f" + bell_id + u" §cуже существует.")
            return True
        _data["bells"][bell_id] = default_bell_entry()
        if save_data():
            send(sender, u"§aСоздан колокол §e" + bell_id + u"§a.")
            send(sender, u"§7Дальше: §f/bell setdest " + bell_id + u"§7, §f/bell add " + bell_id + u" <ник>§7, §f/bell give " + bell_id)
        else:
            del _data["bells"][bell_id]
            send(sender, u"§cНе удалось сохранить колокол.")
        return True

    # -------------------------------------------------------------------------
    # LIST
    # -------------------------------------------------------------------------
    if sub in (u"list", u"список"):
        ids = sorted(_data.get("bells", {}).keys())
        if not ids:
            send(sender, u"§7Колоколов пока нет.")
            return True
        send(sender, u"§6Колокола (§f" + str(len(ids)) + u"§6):")
        for bell_id in ids:
            entry = _data["bells"][bell_id]
            block_mark = u"§aпоставлен" if entry.get("block") else u"§cне поставлен"
            dest_mark = u"§aточка есть" if entry.get("destination") else u"§cнет точки"
            send(sender, u"§8- §e{0} §7| {1} §7| {2} §7| игроков: §f{3}".format(
                bell_id, block_mark, dest_mark, len(entry.get("allowed_names", []))
            ))
        return True

    if len(args) < 2:
        send_help(sender)
        return True

    bell_id, entry = require_bell(sender, args[1])
    if bell_id is None:
        return True

    # -------------------------------------------------------------------------
    # DELETE
    # -------------------------------------------------------------------------
    if sub in (u"delete", u"del", u"удалить"):
        old_entry = entry
        del _data["bells"][bell_id]
        if save_data():
            send(sender, u"§aНастройка колокола §e" + bell_id + u" §aудалена. Сам блок в мире не удаляется.")
        else:
            _data["bells"][bell_id] = old_entry
            send(sender, u"§cНе удалось сохранить удаление.")
        return True

    # -------------------------------------------------------------------------
    # GIVE
    # -------------------------------------------------------------------------
    if sub in (u"give", u"выдать"):
        target = None
        if len(args) >= 3:
            target = Bukkit.getPlayer(unicode(args[2]))
            if target is None or not target.isOnline():
                send(sender, u"§cИгрок §f" + unicode(args[2]) + u" §cне найден онлайн.")
                return True
        elif isinstance(sender, Player):
            target = sender
        else:
            send(sender, u"§cИз консоли/командного блока укажите игрока: §f/bell give <id> <player>")
            return True

        give_item_safely(target, create_bell_item(bell_id))
        send(sender, u"§aКолокол §e{0} §aвыдан игроку §f{1}§a.".format(bell_id, target.getName()))
        if target != sender:
            send(target, u"§7Вам выдан служебный колокол §e" + bell_id + u"§7.")
        return True

    # -------------------------------------------------------------------------
    # SET DESTINATION
    # -------------------------------------------------------------------------
    if sub in (u"setdest", u"dest", u"точка"):
        old_destination = entry.get("destination")

        if len(args) == 2:
            if not isinstance(sender, Player):
                send(sender, u"§cИз консоли/командного блока укажите координаты: §f/bell setdest <id> <x> <y> <z> <world>")
                return True
            entry["destination"] = loc_to_destination(sender.getLocation())
        elif len(args) >= 5:
            try:
                x = float(args[2])
                y = float(args[3])
                z = float(args[4])
            except Exception:
                send(sender, u"§cX, Y и Z должны быть числами.")
                return True

            if len(args) >= 6:
                world_name = unicode(args[5])
                world = Bukkit.getWorld(world_name)
            elif isinstance(sender, Player):
                world = sender.getWorld()
            else:
                world = None

            if world is None:
                send(sender, u"§cМир не найден. Укажите его после координат.")
                return True

            yaw = 0.0
            pitch = 0.0
            if isinstance(sender, Player):
                yaw = float(sender.getLocation().getYaw())
                pitch = float(sender.getLocation().getPitch())

            entry["destination"] = {
                "world": unicode(world.getName()),
                "x": x,
                "y": y,
                "z": z,
                "yaw": yaw,
                "pitch": pitch
            }
        else:
            send(sender, u"§cИспользование: §f/bell setdest <id> §7или §f/bell setdest <id> <x> <y> <z> [world]")
            return True

        if save_data():
            d = entry["destination"]
            send(sender, u"§aТочка §e{0} §aустановлена: §f{1:.2f} {2:.2f} {3:.2f} §7({4})".format(
                bell_id, d["x"], d["y"], d["z"], d["world"]
            ))
        else:
            entry["destination"] = old_destination
            send(sender, u"§cНе удалось сохранить точку.")
        return True

    # -------------------------------------------------------------------------
    # ALLOW / REMOVE NICKNAME
    # -------------------------------------------------------------------------
    if sub in (u"add", u"allow", u"добавить"):
        if len(args) < 3:
            send(sender, u"§cИспользование: §f/bell add <id> <nickname>")
            return True
        nickname = normalize_player_name(args[2])
        if nickname is None:
            send(sender, u"§cНекорректный ник Minecraft.")
            return True
        allowed = entry.setdefault("allowed_names", [])
        if nickname in allowed:
            send(sender, u"§7Игрок §f" + nickname + u" §7уже имеет доступ к §e" + bell_id + u"§7.")
            return True
        allowed.append(nickname)
        allowed.sort()
        if save_data():
            send(sender, u"§aИгрок §f" + nickname + u" §aдобавлен к колоколу §e" + bell_id + u"§a.")
        else:
            allowed.remove(nickname)
            send(sender, u"§cНе удалось сохранить список доступа.")
        return True

    if sub in (u"remove", u"deny", u"убрать"):
        if len(args) < 3:
            send(sender, u"§cИспользование: §f/bell remove <id> <nickname>")
            return True
        nickname = normalize_player_name(args[2])
        if nickname is None:
            send(sender, u"§cНекорректный ник Minecraft.")
            return True
        allowed = entry.setdefault("allowed_names", [])
        if nickname not in allowed:
            send(sender, u"§7Игрок §f" + nickname + u" §7не имеет доступа к §e" + bell_id + u"§7.")
            return True
        allowed.remove(nickname)
        if save_data():
            send(sender, u"§aИгрок §f" + nickname + u" §aубран из колокола §e" + bell_id + u"§a.")
        else:
            allowed.append(nickname)
            allowed.sort()
            send(sender, u"§cНе удалось сохранить список доступа.")
        return True

    # -------------------------------------------------------------------------
    # INFO
    # -------------------------------------------------------------------------
    if sub in (u"info", u"инфо"):
        send(sender, u"§6Колокол: §e" + bell_id)

        b = entry.get("block")
        if b:
            send(sender, u"§7Блок: §f{0} {1} {2} §8({3})".format(b["x"], b["y"], b["z"], b["world"]))
        else:
            send(sender, u"§7Блок: §cне установлен")

        d = entry.get("destination")
        if d:
            send(sender, u"§7Телепорт: §f{0:.2f} {1:.2f} {2:.2f} §8({3})".format(d["x"], d["y"], d["z"], d["world"]))
        else:
            send(sender, u"§7Телепорт: §cне настроен")

        names = entry.get("allowed_names", [])
        if names:
            send(sender, u"§7Доступ: §f" + u", ".join(names))
        else:
            send(sender, u"§7Доступ: §cникого")
        return True

    send(sender, u"§cНеизвестная подкоманда. §7/bell help")
    return True


# =============================================================================
# REGISTRATION
# =============================================================================

load_data()

# Same PySpigot 0.9.1 registration style used by the character scripts in this repo.
cmd_mgr.registerCommand(cmd_bell, "bell")

listener_mgr.registerListener(on_bell_place, BlockPlaceEvent)
listener_mgr.registerListener(on_bell_break, BlockBreakEvent)
listener_mgr.registerListener(on_bell_interact, PlayerInteractEvent)
listener_mgr.registerListener(on_command_send, PlayerCommandSendEvent)

log_info("Teleport Bells enabled. Commands: /bell")
