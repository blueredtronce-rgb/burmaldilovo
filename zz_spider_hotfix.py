# -*- coding: utf-8 -*-
"""
Temporary Agent-Spider hotfix for test-cg.

Loads after agent_spider.py and patches its live globals without touching main/test:
- replaces the red leather helmet with player head BigBoyeDuniel;
- resolves and embeds BigBoyeDuniel's actual Mojang/Paper texture profile;
- restores Web Ball and Web Grenade as ejector modes 13 and 14;
- keeps the current quest modes 0..12 unchanged.

After this is tested, fold the same changes into agent_spider.py before merging to main.
"""

import pyspigot as ps

from java.lang import System, Byte as JByte
from java.util import ArrayList
from org.bukkit import Bukkit, Material
from org.bukkit.inventory import ItemStack
from org.bukkit.persistence import PersistentDataType

scheduler = ps.scheduler

HEAD_OWNER = u"BigBoyeDuniel"
REGISTRY_KEY = "pyspigot.character_kits"
_HEAD_PROFILE = [None]


def _java_list(values):
    result = ArrayList()
    for value in values:
        result.add(value)
    return result


def _function_globals(fn):
    try:
        return fn.func_globals
    except Exception:
        try:
            return fn.__globals__
        except Exception:
            return None


def _get_spider_globals():
    registry = System.getProperties().get(REGISTRY_KEY)
    if registry is None:
        return None
    entry = registry.get("spider")
    if entry is None:
        return None
    try:
        kit_fn = entry[0]
    except Exception:
        kit_fn = entry
    return _function_globals(kit_fn)


def _get_head_profile():
    """Return a cached Paper PlayerProfile with UUID + actual skin texture."""
    if _HEAD_PROFILE[0] is not None:
        return _HEAD_PROFILE[0]
    try:
        # Paper 1.21.11 createProfile(name) creates a profile shell. complete(True)
        # performs the profile lookup and fills UUID/name/textures.
        profile = Bukkit.createProfile(HEAD_OWNER)
        try:
            complete = profile.isComplete()
        except Exception:
            complete = False
        if not complete:
            ok = profile.complete(True)
            if not ok:
                Bukkit.getLogger().warning(
                    "[spider_hotfix] could not complete skin profile for " + HEAD_OWNER
                )
        _HEAD_PROFILE[0] = profile
        return profile
    except Exception as ex:
        Bukkit.getLogger().warning(
            "[spider_hotfix] failed to resolve skin profile for " + HEAD_OWNER + ": " + str(ex)
        )
        return None


def _apply_head_profile(meta):
    profile = _get_head_profile()
    if profile is not None:
        try:
            # SkullMeta#setPlayerProfile stores the supplied profile including textures.
            meta.setPlayerProfile(profile)
            return True
        except Exception as ex:
            Bukkit.getLogger().warning("[spider_hotfix] setPlayerProfile failed: " + str(ex))
    # Last-resort fallback: still provide an owned player head.
    try:
        meta.setOwningPlayer(Bukkit.getOfflinePlayer(HEAD_OWNER))
        return False
    except Exception:
        return False


def _install():
    g = _get_spider_globals()
    if g is None:
        Bukkit.getLogger().warning("[spider_hotfix] agent_spider is not registered yet")
        return False

    required = (
        "KEY_MASK", "KEY_EJECTOR", "MODE_INFO", "wearing_mask", "is_silenced_by_demiurg",
        "ultimate_lock", "uid", "check_cd", "_try_consume_ammo", "do_web_ball",
        "launch_web", "set_cd", "CD_GRENADE"
    )
    for key in required:
        if key not in g:
            Bukkit.getLogger().warning("[spider_hotfix] missing spider global: " + key)
            return False

    key_mask = g["KEY_MASK"]
    key_ejector = g["KEY_EJECTOR"]

    def _set_flag(meta, key):
        meta.getPersistentDataContainer().set(key, PersistentDataType.BYTE, JByte(1))

    def create_mask_hotfix():
        item = ItemStack(Material.PLAYER_HEAD, 1)
        meta = item.getItemMeta()
        meta.setDisplayName(u"§c§lМаска Агент-Паука")
        meta.setLore(_java_list([
            u"§7Маска Агент-Паука.",
            u"§7Внешность: §f" + HEAD_OWNER,
            u"",
            u"§8Не даёт очков брони.",
            u"§8Обязательна для использования способностей.",
        ]))
        _apply_head_profile(meta)
        _set_flag(meta, key_mask)
        item.setItemMeta(meta)
        return item

    def create_ejector_hotfix():
        item = ItemStack(Material.PRISMARINE_SHARD, 1)
        meta = item.getItemMeta()
        meta.setDisplayName(u"§f§lЭжектор паутины")
        meta.setLore(_java_list([
            u"§7Компактный механизм выброса паутины",
            u"§7с 15 боевыми режимами.",
            u"",
            u"§8Режим: §bПолёт на паутине §7[0]",
            u"§8Shift + Колесо мыши — смена режима",
            u"§8ПКМ — выстрел",
        ]))
        try:
            meta.setUnbreakable(True)
        except Exception:
            pass
        _set_flag(meta, key_ejector)
        item.setItemMeta(meta)
        return item

    def update_ejector_lore_hotfix(player):
        inv = player.getInventory()
        for i in range(9):
            item = inv.getItem(i)
            if item is None or item.getType() == Material.AIR:
                continue
            meta = item.getItemMeta()
            if meta is None or not meta.getPersistentDataContainer().has(key_ejector, PersistentDataType.BYTE):
                continue
            mode = g["get_mode"](player)
            name, color = g["MODE_INFO"][mode]
            meta.setLore(_java_list([
                u"§7Компактный механизм выброса паутины",
                u"§7с 15 боевыми режимами.",
                u"",
                u"§8Режим: " + color + name + u" §7[" + str(mode) + u"]",
                u"§8Shift + Колесо мыши — смена режима",
                u"§8ПКМ — выстрел",
            ]))
            item.setItemMeta(meta)

    g["MODE_INFO"][13] = (u"Паутинный шар", u"§f")
    g["MODE_INFO"][14] = (u"Паутинная граната", u"§a")
    g["MODE_MAX"] = 14

    original_fire = g["fire_ejector"]

    def fire_ejector_hotfix(player, mode):
        if mode <= 12:
            return original_fire(player, mode)

        if not g["wearing_mask"](player):
            player.sendMessage(u"§cДля активации эжектора нужна маска.")
            return
        if g["is_silenced_by_demiurg"](player):
            player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
            return
        if g["uid"](player) in g["ultimate_lock"]:
            return

        if mode == 13:
            if not g["check_cd"](player, "ball", u"«Паутинный шар»"):
                return
            if not g["_try_consume_ammo"](player, u"эжектора"):
                return
            g["do_web_ball"](player)
            return

        if mode == 14:
            if not g["check_cd"](player, "grenade", u"«Паутинная граната»"):
                return
            if not g["_try_consume_ammo"](player, u"эжектора"):
                return
            g["launch_web"](player, 14, 1.6)
            g["set_cd"](player, "grenade", g["CD_GRENADE"])
            return

    def mirror_mask_hotfix(owner_uuid):
        item = ItemStack(Material.PLAYER_HEAD, 1)
        meta = item.getItemMeta()
        meta.setDisplayName(u"§cМаска Агент-Паука")
        _apply_head_profile(meta)
        item.setItemMeta(meta)
        return item

    g["create_mask"] = create_mask_hotfix
    g["create_ejector"] = create_ejector_hotfix
    g["update_ejector_lore"] = update_ejector_lore_hotfix
    g["fire_ejector"] = fire_ejector_hotfix
    g["_spider_mirror_mask"] = mirror_mask_hotfix

    try:
        mirror_cat = System.getProperties().get("archer.mirror_catalog")
        if mirror_cat is not None:
            entry = mirror_cat.get("spider:mask")
            if entry is not None:
                entry.put("factory", mirror_mask_hotfix)
    except Exception:
        pass

    Bukkit.getLogger().info(
        "[spider_hotfix] installed: textured BigBoyeDuniel head + Web Ball + Web Grenade"
    )
    return True


def _try_install(attempt=[0]):
    if _install():
        return
    attempt[0] += 1
    if attempt[0] < 10:
        scheduler.runTaskLater(_try_install, 20)
    else:
        Bukkit.getLogger().warning("[spider_hotfix] failed to install after 10 attempts")


scheduler.runTaskLater(_try_install, 1)
