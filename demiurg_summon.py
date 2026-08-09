# -*- coding: utf-8 -*-

import os
import json
import codecs
import time

import pyspigot as ps

from java.lang import System
from org.bukkit import Bukkit, Material, Location
from org.bukkit.entity import Player
from org.bukkit.event.player import PlayerDropItemEvent, PlayerJoinEvent
from org.bukkit.event.block import BlockFadeEvent


listener_mgr = ps.listener_manager()
scheduler = ps.scheduler


# ============================================================
# CONFIG
# ============================================================

DEMIURG_NAMES = set([u"blueredtronce"])

DATA_DIR = os.path.join(
    "plugins",
    "PySpigot",
    "scripts",
    "data"
)

DATA_FILE = os.path.join(
    DATA_DIR,
    "demiurg_summons.json"
)

# После броска алмаза следим за ним 5 секунд,
# чтобы он успел физически упасть на середину алтаря.
DIAMOND_WATCH_TICKS = 100
CHECK_INTERVAL = 5

# Защита от почти одновременного двойного срабатывания.
ALTAR_DEBOUNCE_MS = 5000


# ============================================================
# DATA
# ============================================================

_data = {
    "pending": []
}

_processed_items = set()
_recent_altars = {}


def ensure_data_dir():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
    except Exception as ex:
        Bukkit.getLogger().warning(
            "[demiurg_summon] Cannot create data dir: " + str(ex)
        )


def save_data():
    ensure_data_dir()

    try:
        f = codecs.open(DATA_FILE, "w", "utf-8")
        f.write(
            json.dumps(
                _data,
                ensure_ascii=False,
                indent=2
            )
        )
        f.close()

    except Exception as ex:
        Bukkit.getLogger().warning(
            "[demiurg_summon] Data save failed: " + str(ex)
        )


def load_data():
    global _data

    ensure_data_dir()

    if not os.path.exists(DATA_FILE):
        save_data()
        return

    try:
        f = codecs.open(DATA_FILE, "r", "utf-8")
        raw = f.read()
        f.close()

        loaded = json.loads(raw)

        if (
            isinstance(loaded, dict)
            and isinstance(loaded.get("pending"), list)
        ):
            _data["pending"] = loaded["pending"]

    except Exception as ex:
        Bukkit.getLogger().warning(
            "[demiurg_summon] Data load failed: " + str(ex)
        )


# ============================================================
# UTILS
# ============================================================

def now_ms():
    return long(System.currentTimeMillis())


def is_demiurg(player):
    if not isinstance(player, Player):
        return False

    return player.getName().lower() in DEMIURG_NAMES


def find_online_demiurg():
    for player in Bukkit.getOnlinePlayers():
        if is_demiurg(player):
            return player

    return None


def altar_key(center):
    return u"%s:%d:%d:%d" % (
        center.getWorld().getName(),
        center.getBlockX(),
        center.getBlockY(),
        center.getBlockZ()
    )


def format_time(timestamp):
    try:
        return time.strftime(
            "%d.%m.%Y %H:%M:%S",
            time.localtime(float(timestamp) / 1000.0)
        )
    except Exception:
        return u"неизвестно"


# ============================================================
# ALTAR
# ============================================================

def is_valid_altar(center, require_fire=True):
    """
    Схема:

    Y + 5:
    F . F
    . . .
    F . F

    Y + 4:
    N . N
    . . .
    N . N

    Y + 1..3:
    G . G
    . . .
    G . G

    Y:
    O O O
    O O O
    O O O

    O = Obsidian
    G = Gold Block
    N = Netherrack
    F = Fire
    """

    world = center.getWorld()

    cx = center.getBlockX()
    cy = center.getBlockY()
    cz = center.getBlockZ()

    # Основание 3x3 обсидиана.
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):

            block = world.getBlockAt(
                cx + dx,
                cy,
                cz + dz
            )

            if block.getType() != Material.OBSIDIAN:
                return False

    # Четыре угла.
    for dx in (-1, 1):
        for dz in (-1, 1):

            # 3 золотых блока вверх.
            for dy in (1, 2, 3):

                block = world.getBlockAt(
                    cx + dx,
                    cy + dy,
                    cz + dz
                )

                if block.getType() != Material.GOLD_BLOCK:
                    return False

            # Незеррак.
            netherrack = world.getBlockAt(
                cx + dx,
                cy + 4,
                cz + dz
            )

            if netherrack.getType() != Material.NETHERRACK:
                return False

            # Огонь.
            if require_fire:

                fire = world.getBlockAt(
                    cx + dx,
                    cy + 5,
                    cz + dz
                )

                if fire.getType() != Material.FIRE:
                    return False

    return True


def find_altar_for_diamond(item):
    """
    Ищет центр алтаря только рядом с выброшенным алмазом.
    Постоянного сканирования мира нет.
    """

    loc = item.getLocation()
    world = loc.getWorld()

    ix = loc.getBlockX()
    iy = loc.getBlockY()
    iz = loc.getBlockZ()

    for cx in range(ix - 1, ix + 2):
        for cz in range(iz - 1, iz + 2):
            for cy in range(iy - 2, iy + 1):

                center = Location(
                    world,
                    cx,
                    cy,
                    cz
                )

                if not is_valid_altar(center, True):
                    continue

                # Проверяем, что алмаз лежит именно возле середины.
                dx = loc.getX() - (cx + 0.5)
                dz = loc.getZ() - (cz + 0.5)

                distance_sq = dx * dx + dz * dz

                if distance_sq > 0.64:
                    continue

                if loc.getY() < cy + 0.75:
                    continue

                if loc.getY() > cy + 2.3:
                    continue

                return center

    return None


# ============================================================
# FIRE
# ============================================================

def get_altar_from_fire(block):
    """
    FIRE находится на углу алтаря:
    X/Z ±1
    Y +5
    """

    if block.getType() != Material.FIRE:
        return None

    world = block.getWorld()

    fx = block.getX()
    fy = block.getY()
    fz = block.getZ()

    for dx in (-1, 1):
        for dz in (-1, 1):

            center = Location(
                world,
                fx - dx,
                fy - 5,
                fz - dz
            )

            if is_valid_altar(center, True):
                return center

    return None


def on_fire_fade(event):
    block = event.getBlock()

    if block.getType() != Material.FIRE:
        return

    try:
        altar = get_altar_from_fire(block)

        if altar is not None:
            event.setCancelled(True)

    except Exception as ex:
        Bukkit.getLogger().warning(
            "[demiurg_summon] Fire check failed: " + str(ex)
        )


# ============================================================
# DIAMOND
# ============================================================

def consume_one_diamond(item):
    stack = item.getItemStack()

    if stack is None:
        return False

    if stack.getType() != Material.DIAMOND:
        return False

    amount = stack.getAmount()

    if amount <= 0:
        return False

    # Даже если бросили стак — поглощается только ОДИН.
    if amount == 1:
        item.remove()

    else:
        stack.setAmount(amount - 1)
        item.setItemStack(stack)

    return True


# ============================================================
# PENDING SUMMONS
# ============================================================

def save_pending(player, center):

    entry = {
        "player": player.getName(),
        "uuid": player.getUniqueId().toString(),

        "world": center.getWorld().getName(),

        "x": center.getBlockX(),
        "y": center.getBlockY(),
        "z": center.getBlockZ(),

        "time": now_ms()
    }

    _data["pending"].append(entry)

    save_data()


# ============================================================
# SUMMON
# ============================================================

def summon(player, item, center):

    key = altar_key(center)
    current_time = now_ms()

    # Антидубль.
    last = _recent_altars.get(key)

    if last is not None:
        if current_time - last < ALTAR_DEBOUNCE_MS:
            return

    if not consume_one_diamond(item):
        return

    _recent_altars[key] = current_time

    world = center.getWorld()

    lightning_location = center.clone().add(
        0.5,
        1.0,
        0.5
    )

    # ВАЖНО:
    # strikeLightningEffect = только эффект.
    # Нет урона.
    # Нет поджигания.
    world.strikeLightningEffect(lightning_location)

    demiurg = find_online_demiurg()

    # --------------------------------------------------------
    # DEMIURG ONLINE
    # --------------------------------------------------------

    if demiurg is not None:

        player.sendMessage(u"")
        player.sendMessage(
            u"§6§l✦ Ваш голос был услышан."
        )
        player.sendMessage(
            u"§7Демиург услышал ваш зов."
        )
        player.sendMessage(u"")

        demiurg.sendMessage(u"")
        demiurg.sendMessage(
            u"§5§l✦ ЗОВ ДЕМИУРГА"
        )

        demiurg.sendMessage(
            u"§d%s §7призывает вас." %
            player.getName()
        )

        demiurg.sendMessage(
            u"§7Место: §f%s §8| §f%d %d %d" % (
                center.getWorld().getName(),
                center.getBlockX(),
                center.getBlockY(),
                center.getBlockZ()
            )
        )

        demiurg.sendMessage(u"")

    # --------------------------------------------------------
    # DEMIURG OFFLINE
    # --------------------------------------------------------

    else:

        player.sendMessage(u"")
        player.sendMessage(
            u"§8§l✦ В ответ — тишина."
        )

        player.sendMessage(
            u"§7Демиург сейчас не может ответить на ваш зов."
        )

        player.sendMessage(
            u"§7Но призыв §dне останется неуслышанным§7."
        )

        player.sendMessage(u"")

        save_pending(
            player,
            center
        )


# ============================================================
# DROP EVENT
# ============================================================

def on_drop(event):

    player = event.getPlayer()
    item = event.getItemDrop()

    stack = item.getItemStack()

    if stack is None:
        return

    if stack.getType() != Material.DIAMOND:
        return

    item_uuid = item.getUniqueId().toString()

    if item_uuid in _processed_items:
        return

    state = {
        "ticks": 0,
        "done": False
    }

    def check():

        if state["done"]:
            return

        state["ticks"] += CHECK_INTERVAL

        try:

            if not item.isValid():
                state["done"] = True
                return

            if item.isDead():
                state["done"] = True
                return

            stack_now = item.getItemStack()

            if stack_now is None:
                state["done"] = True
                return

            if stack_now.getType() != Material.DIAMOND:
                state["done"] = True
                return

            altar = find_altar_for_diamond(item)

            if altar is not None:

                _processed_items.add(item_uuid)

                state["done"] = True

                summon(
                    player,
                    item,
                    altar
                )

                return

        except Exception as ex:

            Bukkit.getLogger().warning(
                "[demiurg_summon] Diamond check failed: "
                + str(ex)
            )

            state["done"] = True
            return

        if state["ticks"] < DIAMOND_WATCH_TICKS:

            scheduler.runTaskLater(
                check,
                CHECK_INTERVAL
            )

        else:
            state["done"] = True

    scheduler.runTaskLater(
        check,
        CHECK_INTERVAL
    )


# ============================================================
# DEMIURG JOIN
# ============================================================

def on_join(event):

    player = event.getPlayer()

    if not is_demiurg(player):
        return

    def deliver():

        if not player.isOnline():
            return

        pending = list(
            _data.get(
                "pending",
                []
            )
        )

        if not pending:
            return

        player.sendMessage(u"")

        player.sendMessage(
            u"§5§l✦ ВО ВРЕМЯ ВАШЕГО ОТСУТСТВИЯ "
            u"ВАС ПРИЗЫВАЛИ"
        )

        player.sendMessage(
            u"§7Количество призывов: §f"
            + str(len(pending))
        )

        for index, entry in enumerate(pending):

            name = unicode(
                entry.get(
                    "player",
                    u"неизвестно"
                )
            )

            world = unicode(
                entry.get(
                    "world",
                    u"world"
                )
            )

            x = int(entry.get("x", 0))
            y = int(entry.get("y", 0))
            z = int(entry.get("z", 0))

            summon_time = format_time(
                entry.get(
                    "time",
                    0
                )
            )

            player.sendMessage(
                u"§d%d. %s "
                u"§8— §7%s "
                u"§8| §f%d %d %d "
                u"§8| §7%s" % (
                    index + 1,
                    name,
                    world,
                    x,
                    y,
                    z,
                    summon_time
                )
            )

        player.sendMessage(u"")

        # После того как Демиург реально увидел сообщения,
        # удаляем их из очереди.
        _data["pending"] = []

        save_data()

    scheduler.runTaskLater(
        deliver,
        20
    )


# ============================================================
# REGISTER
# ============================================================

load_data()

listener_mgr.registerListener(
    on_drop,
    PlayerDropItemEvent
)

listener_mgr.registerListener(
    on_fire_fade,
    BlockFadeEvent
)

listener_mgr.registerListener(
    on_join,
    PlayerJoinEvent
)

Bukkit.getLogger().info(
    "[demiurg_summon] Ritual loaded."
)