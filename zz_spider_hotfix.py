# -*- coding: utf-8 -*-
"""
Temporary Agent-Spider hotfix for test-cg.

Loads after agent_spider.py and patches its live globals without touching main/test:
- replaces the red leather helmet with player head BigBoyeDuniel;
- reads BigBoyeDuniel's ACTIVE skin property from SkinsRestorer (offline-mode safe);
- embeds that signed textures property directly into the Paper player-head profile;
- falls back to Paper/Mojang profile resolution only if SkinsRestorer data is unavailable;
- restores Web Ball and Web Grenade as ejector modes 13 and 14;
- keeps the current quest modes 0..12 unchanged;
- TEST: displays ejector mode switches through Action Bar instead of normal chat.

After this is tested, fold the same changes into agent_spider.py before merging to main.
"""

import pyspigot as ps

from java.lang import System, Byte as JByte
from java.util import ArrayList
from org.bukkit import Bukkit, Material, Sound
from org.bukkit.inventory import ItemStack
from org.bukkit.persistence import PersistentDataType
from com.destroystokyo.paper.profile import ProfileProperty

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


def _skinsrestorer_api():
    """Resolve the installed SkinsRestorer API, with classloader fallback for PySpigot."""
    try:
        from net.skinsrestorer.api import SkinsRestorerProvider
        return SkinsRestorerProvider.get()
    except Exception as direct_ex:
        try:
            plugin = Bukkit.getPluginManager().getPlugin("SkinsRestorer")
            if plugin is None:
                Bukkit.getLogger().warning("[spider_hotfix] SkinsRestorer plugin not found")
                return None
            loader = plugin.getClass().getClassLoader()
            provider_cls = loader.loadClass("net.skinsrestorer.api.SkinsRestorerProvider")
            for method in provider_cls.getDeclaredMethods():
                if method.getName() == "get" and method.getParameterTypes().length == 0:
                    return method.invoke(None)
            Bukkit.getLogger().warning("[spider_hotfix] SkinsRestorerProvider.get() not found")
        except Exception as reflect_ex:
            Bukkit.getLogger().warning(
                "[spider_hotfix] SkinsRestorer API unavailable: " + str(reflect_ex)
            )
    return None


def _profile_from_skinsrestorer():
    """Build a Paper profile from the exact SkinProperty SkinsRestorer applies in offline mode."""
    try:
        api = _skinsrestorer_api()
        if api is None:
            return None

        offline = Bukkit.getOfflinePlayer(HEAD_OWNER)
        owner_uuid = offline.getUniqueId()
        player_storage = api.getPlayerStorage()

        optional = player_storage.getSkinForPlayer(owner_uuid, HEAD_OWNER, False)
        if optional is None or not optional.isPresent():
            try:
                optional = player_storage.getSkinOfPlayer(owner_uuid)
            except Exception:
                pass

        if optional is None or not optional.isPresent():
            Bukkit.getLogger().warning(
                "[spider_hotfix] SkinsRestorer has no stored skin for " + HEAD_OWNER
            )
            return None

        skin_property = optional.get()
        value = skin_property.getValue()
        signature = skin_property.getSignature()
        if value is None or len(str(value)) == 0:
            Bukkit.getLogger().warning(
                "[spider_hotfix] SkinsRestorer returned empty texture value for " + HEAD_OWNER
            )
            return None

        profile = Bukkit.createProfileExact(owner_uuid, HEAD_OWNER)
        profile.clearProperties()
        if signature is None or len(str(signature)) == 0:
            profile.setProperty(ProfileProperty("textures", value))
        else:
            profile.setProperty(ProfileProperty("textures", value, signature))

        Bukkit.getLogger().info(
            "[spider_hotfix] loaded " + HEAD_OWNER + " texture from SkinsRestorer"
        )
        return profile
    except Exception as ex:
        Bukkit.getLogger().warning(
            "[spider_hotfix] failed to read SkinsRestorer skin for " + HEAD_OWNER + ": " + str(ex)
        )
        return None


def _profile_from_paper_fallback():
    """Fallback for premium/Mojang-backed accounts when SR data is unavailable."""
    try:
        profile = Bukkit.createProfile(HEAD_OWNER)
        try:
            complete = profile.isComplete()
        except Exception:
            complete = False
        if not complete:
            try:
                profile.complete(True)
            except Exception:
                pass
        return profile
    except Exception as ex:
        Bukkit.getLogger().warning(
            "[spider_hotfix] Paper fallback profile failed for " + HEAD_OWNER + ": " + str(ex)
        )
        return None


def _get_head_profile():
    if _HEAD_PROFILE[0] is not None:
        return _HEAD_PROFILE[0]

    profile = _profile_from_skinsrestorer()
    if profile is None:
        profile = _profile_from_paper_fallback()

    if profile is not None:
        _HEAD_PROFILE[0] = profile
    return profile


def _apply_head_profile(meta):
    profile = _get_head_profile()
    if profile is not None:
        try:
            meta.setPlayerProfile(profile)
            return True
        except Exception as ex:
            Bukkit.getLogger().warning("[spider_hotfix] setPlayerProfile failed: " + str(ex))
    try:
        meta.setOwningPlayer(Bukkit.getOfflinePlayer(HEAD_OWNER))
    except Exception:
        pass
    return False


def _install():
    g = _get_spider_globals()
    if g is None:
        Bukkit.getLogger().warning("[spider_hotfix] agent_spider is not registered yet")
        return False

    required = (
        "KEY_MASK", "KEY_EJECTOR", "MODE_INFO", "player_mode", "wearing_mask",
        "is_silenced_by_demiurg", "ultimate_lock", "uid", "check_cd",
        "_try_consume_ammo", "do_web_ball", "launch_web", "set_cd", "CD_GRENADE"
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

    # Preserve all modern modes and append the two accidentally lost legacy modes.
    g["MODE_INFO"][13] = (u"Паутинный шар", u"§f")
    g["MODE_INFO"][14] = (u"Паутинная граната", u"§a")
    g["MODE_MAX"] = 14

    # TEST: mode selection no longer enters normal chat (and therefore bypasses
    # ChatLagFix/ChatPatches). It is shown in the vanilla Action Bar instead.
    def set_mode_actionbar_hotfix(player, mode):
        mode = mode % (g["MODE_MAX"] + 1)
        g["player_mode"][g["uid"](player)] = mode
        name, color = g["MODE_INFO"][mode]
        text = u"§8⌬ §fРежим эжектора: " + color + name + u" §7[" + str(mode) + u"]"

        def show_again():
            try:
                # Do not replay stale text if the player scrolled again during the delay.
                if g["player_mode"].get(g["uid"](player), 0) == mode and player.isOnline():
                    player.sendActionBar(text)
            except Exception:
                pass

        try:
            player.sendActionBar(text)
        except Exception as ex:
            Bukkit.getLogger().warning("[spider_hotfix] actionbar failed: " + str(ex))
        scheduler.runTaskLater(show_again, 2)
        try:
            player.playSound(player.getLocation(), Sound.UI_BUTTON_CLICK, 0.6, 1.7)
        except Exception:
            pass

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
    g["set_mode"] = set_mode_actionbar_hotfix
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
        "[spider_hotfix] installed: SR head + Web Ball/Grenade + ActionBar mode test"
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
