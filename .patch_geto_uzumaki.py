from pathlib import Path

TARGET = Path("geto.py")
MARKER = "# GETO_UZUMAKI_EXTRACTION_V1"
OVERLAY = r'''# =============================================================================
#  ДУХОВНАЯ ИЗВЛЕКАЕМОСТЬ: УЗУМАКИ
#  Добавлено 2026-08-07.
#  ПКМ яйцом в воздухе — извлечь особенность моба.
#  Shift+ПКМ яйцом по блоку — извлечь; обычный ПКМ по блоку по-прежнему призывает.
# =============================================================================

from org.bukkit.event.player import (
    PlayerCommandPreprocessEvent, PlayerItemDamageEvent, PlayerItemConsumeEvent
)
from org.bukkit.event.entity import EntityExplodeEvent
from org.bukkit.entity import LargeFireball, SmallFireball
from org.bukkit.enchantments import Enchantment

UZ_DURATION = 60 * 20
UZ_COOLDOWN = 150 * 20

KEY_UZ_MILK = NamespacedKey.fromString("geto:uzumaki_milk")
KEY_UZ_GOAT = NamespacedKey.fromString("geto:uzumaki_goat_hoe")

E_HUNGER = _effect("hunger")
E_POISON = _effect("poison")
E_WITHER = _effect("wither")
E_JUMP = _effect("jump_boost")
E_SLOW_FALLING = _effect("slow_falling")
E_WATER_BREATHING = _effect("water_breathing")
E_DOLPHINS_GRACE = _effect("dolphins_grace")
E_SLOWNESS = _effect("slowness")

ATTR_SCALE_UZ = _attr("SCALE")

uz_active = {}
uz_projectiles = {}
uz_reflect_guard = set()

_ZOMBIE_TYPES = set([
    "ZOMBIE", "DROWNED", "HUSK", "ZOMBIE_VILLAGER", "ZOMBIFIED_PIGLIN"
])
_SKELETON_TYPES = set(["SKELETON", "STRAY", "BOGGED"])
_PIGLIN_TYPES = set(["PIGLIN", "PIGLIN_BRUTE", "VINDICATOR"])
_FISH_TYPES = set([
    "COD", "TROPICAL_FISH", "DOLPHIN", "TADPOLE", "SQUID", "PUFFERFISH",
    "NAUTILUS", "GLOW_SQUID", "SALMON"
])

_UZ_SUPPORTED = set([
    "CREEPER", "SPIDER", "ENDERMAN", "WITCH", "PHANTOM", "SLIME",
    "MAGMA_CUBE", "GHAST", "BLAZE", "VEX", "CAVE_SPIDER", "BREEZE",
    "GUARDIAN", "WITHER_SKELETON", "CHICKEN", "COW", "SHEEP", "HORSE",
    "CAT", "ARMADILLO", "BAT", "BEE", "GOAT", "RABBIT", "AXOLOTL",
    "IRON_GOLEM"
])
_UZ_SUPPORTED.update(_ZOMBIE_TYPES)
_UZ_SUPPORTED.update(_SKELETON_TYPES)
_UZ_SUPPORTED.update(_PIGLIN_TYPES)
_UZ_SUPPORTED.update(_FISH_TYPES)


def _uz_state(player):
    st = uz_active.get(uid(player))
    if st is None:
        return None
    if st.get("end_tick", 0) <= now_tick():
        return None
    return st


def _uz_mob(player):
    st = _uz_state(player)
    return st.get("mob") if st is not None else None


def _uz_is_axe(item):
    if item is None:
        return False
    try:
        return item.getType().name().endswith("_AXE")
    except Exception:
        return False


def _uz_marked(item, key):
    if item is None or item.getType() == Material.AIR:
        return False
    try:
        meta = item.getItemMeta()
        if meta is None:
            return False
        return meta.getPersistentDataContainer().has(key, PersistentDataType.BYTE)
    except Exception:
        return False


def _uz_remove_marked(player, key):
    try:
        inv = player.getInventory()
        for i in range(inv.getSize()):
            it = inv.getItem(i)
            if _uz_marked(it, key):
                inv.setItem(i, None)
    except Exception:
        pass


def _uz_make_milk():
    it = ItemStack(Material.MILK_BUCKET, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§f§lБесконечное молоко")
    meta.setLore(java_list([
        u"§7Эффект экстракции Коровы.",
        u"§8Исчезнет после окончания Узумаки."
    ]))
    meta.getPersistentDataContainer().set(KEY_UZ_MILK, PersistentDataType.BYTE, JByte(1))
    it.setItemMeta(meta)
    return it


def _uz_ensure_milk(player):
    if _uz_mob(player) != "COW":
        return
    try:
        inv = player.getInventory()
        for i in range(inv.getSize()):
            if _uz_marked(inv.getItem(i), KEY_UZ_MILK):
                return
        inv.addItem(_uz_make_milk())
    except Exception:
        pass


def _uz_make_goat_hoe():
    it = ItemStack(Material.WOODEN_HOE, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§f§lРоговой толчок")
    meta.setLore(java_list([
        u"§7Один удар.",
        u"§7Отдача IV.",
        u"§8Исчезнет после использования или окончания Узумаки."
    ]))
    meta.getPersistentDataContainer().set(KEY_UZ_GOAT, PersistentDataType.BYTE, JByte(1))
    try:
        kb = Registry.ENCHANTMENT.get(NamespacedKey.minecraft("knockback"))
        if kb is not None:
            meta.addEnchant(kb, 4, True)
    except Exception:
        try:
            meta.addEnchant(Enchantment.KNOCKBACK, 4, True)
        except Exception:
            pass
    it.setItemMeta(meta)
    return it


def _uz_consume_one_egg(player, item):
    try:
        amount = item.getAmount()
        if amount <= 1:
            player.getInventory().setItemInMainHand(ItemStack(Material.AIR))
        else:
            item.setAmount(amount - 1)
    except Exception:
        try:
            item.setAmount(item.getAmount() - 1)
        except Exception:
            pass


def _uz_effect_name(mob):
    if mob in _ZOMBIE_TYPES: return u"Голод при ударе"
    if mob in _SKELETON_TYPES: return u"+15% урона снарядами"
    if mob == "CREEPER": return u"Одноразовый взрыв"
    if mob == "SPIDER": return u"Ползание по стенам"
    if mob == "ENDERMAN": return u"Неуязвимость к снарядам"
    if mob == "WITCH": return u"Очищение эффектов каждые 5 секунд"
    if mob == "PHANTOM": return u"Нерушимые элитры"
    if mob in ("SLIME", "MAGMA_CUBE"): return u"Прыгучесть III и иммунитет к падению"
    if mob == "GHAST": return u"Огненные шары гаста"
    if mob == "BLAZE": return u"Тройной залп ифрита"
    if mob in _PIGLIN_TYPES: return u"Следующий удар топором пробивает щит и +50% урона"
    if mob == "VEX": return u"Спектатор на 5 секунд"
    if mob == "CAVE_SPIDER": return u"Яд I при ударе"
    if mob == "BREEZE": return u"Рывок на 5 блоков"
    if mob == "GUARDIAN": return u"Отражение 7% урона"
    if mob == "WITHER_SKELETON": return u"Иссушение I при ударе"
    if mob == "CHICKEN": return u"Плавное падение"
    if mob == "COW": return u"Бесконечное ведро молока"
    if mob == "SHEEP": return u"Иммунитет к заморозке"
    if mob == "HORSE": return u"Скорость I"
    if mob == "CAT": return u"Криперы боятся в радиусе 10 блоков"
    if mob == "ARMADILLO": return u"Сопротивление II в неподвижности"
    if mob == "BAT": return u"Полёт ценой половины сердца"
    if mob == "BEE": return u"Одноразовый яд + тошнота"
    if mob == "GOAT": return u"Одноразовая мотыга с Отдачей IV"
    if mob == "RABBIT": return u"Рост 1 блок + Прыгучесть I"
    if mob == "AXOLOTL": return u"Регенерация I"
    if mob in _FISH_TYPES: return u"Дельфинья грация II + Водное дыхание"
    if mob == "IRON_GOLEM": return u"Сопротивление I + Замедление I + Сила I, без щитов"
    return u"Неизвестная экстракция"


def _uz_restore_vex(player, old_mode):
    try:
        if player is None or not player.isOnline():
            return
        if player.getGameMode() == GameMode.SPECTATOR:
            player.setGameMode(old_mode)
            player.sendMessage(u"§7Эффект Вредины закончился.")
    except Exception:
        pass


def _uz_finish(player_uuid, apply_cd=True):
    st = uz_active.pop(player_uuid, None)
    if st is None:
        return
    try:
        p = Bukkit.getPlayer(JUUID.fromString(player_uuid))
    except Exception:
        p = None
    if p is not None:
        mob = st.get("mob")
        if mob == "COW": _uz_remove_marked(p, KEY_UZ_MILK)
        if mob == "GOAT": _uz_remove_marked(p, KEY_UZ_GOAT)
        if mob == "BAT":
            try:
                if p.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
                    p.setFlying(False)
                    p.setAllowFlight(False)
            except Exception:
                pass
        if mob == "RABBIT" and ATTR_SCALE_UZ is not None:
            try:
                old_scale = st.get("old_scale")
                if old_scale is not None:
                    p.getAttribute(ATTR_SCALE_UZ).setBaseValue(old_scale)
            except Exception:
                pass
        if apply_cd:
            set_cd(p, "extract", UZ_COOLDOWN)
        try:
            p.sendMessage(u"§7Духовная Извлекаемость закончилась." +
                          (u" §8КД: 2:30." if not is_free_cd(p) else u""))
        except Exception:
            pass


def _uz_activate(player, mob):
    u = uid(player)
    st = {
        "mob": mob, "end_tick": now_tick() + UZ_DURATION, "used": False,
        "last_move_tick": now_tick(), "last_loc": player.getLocation().clone(),
        "breeze_cd": 0, "creeper_guard_until": 0,
    }
    uz_active[u] = st
    add_effect(player, E_NAUSEA, 3 * 20, 0)
    add_effect(player, E_WEAKNESS, 3 * 20, 0)

    if mob in ("SLIME", "MAGMA_CUBE"):
        add_effect(player, E_JUMP, UZ_DURATION, 2)
    elif mob == "CHICKEN": add_effect(player, E_SLOW_FALLING, UZ_DURATION, 0)
    elif mob == "HORSE": add_effect(player, E_SPEED, UZ_DURATION, 0)
    elif mob == "AXOLOTL": add_effect(player, E_REGEN, UZ_DURATION, 0)
    elif mob in _FISH_TYPES:
        add_effect(player, E_DOLPHINS_GRACE, UZ_DURATION, 1)
        add_effect(player, E_WATER_BREATHING, UZ_DURATION, 0)
    elif mob == "IRON_GOLEM":
        add_effect(player, E_RESISTANCE, UZ_DURATION, 0)
        add_effect(player, E_SLOWNESS, UZ_DURATION, 0)
        add_effect(player, E_STRENGTH, UZ_DURATION, 0)
    elif mob == "COW": _uz_ensure_milk(player)
    elif mob == "GOAT":
        try: player.getInventory().addItem(_uz_make_goat_hoe())
        except Exception: pass
    elif mob == "RABBIT":
        add_effect(player, E_JUMP, UZ_DURATION, 0)
        if ATTR_SCALE_UZ is not None:
            try:
                attr = player.getAttribute(ATTR_SCALE_UZ)
                st["old_scale"] = attr.getBaseValue()
                attr.setBaseValue(0.55)
            except Exception: pass
    elif mob == "BAT":
        try:
            player.setHealth(min(player.getHealth(), 1.0))
            player.setAllowFlight(True)
            player.setFlying(True)
        except Exception: pass
    elif mob == "VEX":
        try:
            old_mode = player.getGameMode()
            st["vex_old_mode"] = old_mode
            player.setGameMode(GameMode.SPECTATOR)
            scheduler.runTaskLater(lambda: _uz_restore_vex(player, old_mode), 5 * 20)
        except Exception: pass

    player.sendMessage(u"§5§l✦ Духовная Извлекаемость: Узумаки")
    player.sendMessage(u"§7Сущность: §f" + mob.replace("_", " ").title())
    player.sendMessage(u"§7Эффект: §f" + _uz_effect_name(mob) + u" §8(60 сек.)")
    if mob == "CREEPER": player.sendMessage(u"§8/geto поглотить — взрыв (один раз).")
    elif mob == "GHAST": player.sendMessage(u"§8/geto поглотить — запустить огненный шар.")
    elif mob == "BLAZE": player.sendMessage(u"§8/geto поглотить — тройной огненный залп.")
    elif mob == "BREEZE": player.sendMessage(u"§8/geto поглотить — рывок 5 блоков (КД 6 сек.).")
    if mob == "WITCH": scheduler.runTaskLater(lambda: _uz_witch_clean(u), 5 * 20)
    scheduler.runTaskLater(lambda: _uz_finish(u, True), UZ_DURATION)


def _uz_try_extract(player, egg_item):
    owner = get_egg_owner(egg_item)
    if owner is None or owner != uid(player):
        player.sendMessage(u"§cЭто яйцо принадлежит другому магу.")
        return True
    et = get_egg_entity_type(egg_item)
    if et is None:
        player.sendMessage(u"§cЯйцо повреждено.")
        return True
    mob = et.name()
    if _uz_state(player) is not None:
        _uz_consume_one_egg(player, egg_item)
        player.sendMessage(u"§4§lНесовместимость экстракций.")
        try: player.setHealth(0.0)
        except Exception: player.damage(10000.0)
        return True
    cd = get_cd(player, "extract")
    if cd > 0:
        secs = (cd + 19) // 20
        player.sendMessage(u"§cДуховная Извлекаемость перезаряжается: §f%d§c сек." % secs)
        return True
    if mob not in _UZ_SUPPORTED:
        player.sendMessage(u"§eУ этой сущности нет доступной экстракции. §7Яйцо можно использовать для обычного призыва.")
        return True
    _uz_consume_one_egg(player, egg_item)
    _uz_activate(player, mob)
    return True


_uz_legacy_create_personal_egg = create_personal_egg
def create_personal_egg(entity_type, owner_uuid):
    it = _uz_legacy_create_personal_egg(entity_type, owner_uuid)
    try:
        meta = it.getItemMeta()
        display_name = entity_type.name().replace("_", " ").title()
        meta.setLore(java_list([
            u"§7Персональная сущность Сугуру Гето.", u"§8Тип: §f" + display_name, u"",
            u"§dПКМ в воздух §8— извлечь особенность на 60 сек.",
            u"§dShift+ПКМ по блоку §8— извлечь особенность.",
            u"§8ПКМ по блоку — выпустить существо.", u"§8Не выбрасывается, не передаётся."
        ]))
        it.setItemMeta(meta)
    except Exception: pass
    return it


_uz_legacy_release_summon = _release_summon
def _release_summon(player, egg_item, click_loc):
    try:
        if player.isSneaking(): return True
    except Exception: pass
    return _uz_legacy_release_summon(player, egg_item, click_loc)


def _uz_on_interact(event):
    try:
        if event.getHand() != EquipmentSlot.HAND: return
        p = event.getPlayer()
        if not is_geto(p): return
        if _uz_mob(p) == "IRON_GOLEM":
            held = event.getItem()
            if held is not None and held.getType() == Material.SHIELD:
                event.setCancelled(True)
                p.sendActionBar(u"§cВо время экстракции Железного голема щит недоступен.")
                return
        item = event.getItem()
        if item is None or not is_geto_egg(item): return
        action = event.getAction()
        extract_click = (action == Action.RIGHT_CLICK_AIR)
        if action == Action.RIGHT_CLICK_BLOCK and p.isSneaking(): extract_click = True
        if not extract_click: return
        event.setCancelled(True)
        _uz_try_extract(p, item)
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] interact: " + str(ex))


def _uz_command_action(event):
    try:
        p = event.getPlayer()
        if not is_geto(p): return
        msg = event.getMessage().strip().lower()
        if msg not in (u"/geto поглотить", u"/geto absorb", u"/geto consume"): return
        st = _uz_state(p)
        if st is None: return
        mob = st.get("mob")
        if mob == "CREEPER":
            event.setCancelled(True)
            if st.get("used"):
                p.sendMessage(u"§cВзрыв Крипера уже использован.")
                return
            st["used"] = True
            st["creeper_guard_until"] = now_tick() + 3
            loc = p.getLocation()
            try: p.getWorld().createExplosion(loc, 3.0, False, False, p)
            except Exception:
                try: p.getWorld().createExplosion(loc, 3.0, False, False)
                except Exception: pass
            try: p.setHealth(max(0.0, p.getHealth() - 2.0))
            except Exception: pass
            return
        if mob == "GHAST":
            event.setCancelled(True)
            try:
                fb = p.launchProjectile(LargeFireball)
                fb.setVelocity(p.getEyeLocation().getDirection().normalize().multiply(1.0))
                try:
                    fb.setYield(1.0); fb.setIsIncendiary(False)
                except Exception: pass
                uz_projectiles[uid(fb)] = "ghast"
                p.getWorld().playSound(p.getLocation(), Sound.ENTITY_GHAST_SHOOT, 1.0, 1.0)
            except Exception as ex: p.sendMessage(u"§cНе удалось выпустить шар: §f" + str(ex))
            return
        if mob == "BLAZE":
            event.setCancelled(True)
            try:
                base_dir = p.getEyeLocation().getDirection().normalize()
                for angle in (-0.10, 0.0, 0.10):
                    fb = p.launchProjectile(SmallFireball)
                    d = base_dir.clone()
                    try: d.rotateAroundY(angle)
                    except Exception: d.setX(d.getX() + angle)
                    fb.setVelocity(d.normalize().multiply(1.1))
                    try: fb.setIsIncendiary(False)
                    except Exception: pass
                    uz_projectiles[uid(fb)] = "blaze"
                p.getWorld().playSound(p.getLocation(), Sound.ENTITY_BLAZE_SHOOT, 1.0, 1.0)
            except Exception as ex: p.sendMessage(u"§cНе удалось выполнить залп: §f" + str(ex))
            return
        if mob == "BREEZE":
            event.setCancelled(True)
            now = now_tick()
            if st.get("breeze_cd", 0) > now:
                secs = (st["breeze_cd"] - now + 19) // 20
                p.sendMessage(u"§cРывок перезаряжается: §f%d§c сек." % secs)
                return
            st["breeze_cd"] = now + 6 * 20
            try:
                world = p.getWorld(); start = p.getLocation(); direction = start.getDirection().normalize(); dest = start.clone()
                for i in range(1, 11):
                    test = start.clone().add(direction.clone().multiply(i * 0.5))
                    b1 = world.getBlockAt(test.getBlockX(), test.getBlockY(), test.getBlockZ())
                    b2 = world.getBlockAt(test.getBlockX(), test.getBlockY() + 1, test.getBlockZ())
                    if b1.getType().isSolid() or b2.getType().isSolid(): break
                    dest = test
                p.teleport(dest); p.setFallDistance(0.0)
                world.spawnParticle(Particle.CLOUD, start.clone().add(0, 1, 0), 20, 0.3, 0.4, 0.3, 0.04)
            except Exception: pass
            return
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] command action: " + str(ex))


def _uz_on_damage_any(event):
    try:
        ent = event.getEntity()
        if not isinstance(ent, Player) or not is_geto(ent): return
        st = _uz_state(ent)
        if st is None: return
        mob = st.get("mob"); cause = event.getCause(); C = EntityDamageEvent.DamageCause
        if mob == "ENDERMAN" and cause == C.PROJECTILE:
            event.setCancelled(True); return
        if mob in ("SLIME", "MAGMA_CUBE") and cause == C.FALL:
            event.setCancelled(True); ent.setFallDistance(0.0); return
        if mob == "SHEEP":
            try:
                if cause == C.FREEZE:
                    event.setCancelled(True); ent.setFreezeTicks(0); return
            except Exception: pass
        if mob == "CREEPER" and st.get("creeper_guard_until", 0) >= now_tick():
            try:
                if cause in (C.BLOCK_EXPLOSION, C.ENTITY_EXPLOSION):
                    event.setCancelled(True); return
            except Exception: pass
    except Exception: pass


def _uz_on_damage_by(event):
    try:
        damager = event.getDamager(); victim = event.getEntity()
        try: proj_kind = uz_projectiles.get(uid(damager))
        except Exception: proj_kind = None
        if proj_kind is not None and isinstance(victim, LivingEntity):
            if proj_kind == "ghast": victim.setFireTicks(max(victim.getFireTicks(), 80))
            elif proj_kind == "blaze":
                event.setDamage(min(event.getDamage(), 3.0)); victim.setFireTicks(max(victim.getFireTicks(), 40))
        shooter = None
        try:
            if hasattr(damager, "getShooter"): shooter = damager.getShooter()
        except Exception: shooter = None
        if isinstance(shooter, Player) and is_geto(shooter) and _uz_mob(shooter) in _SKELETON_TYPES:
            event.setDamage(event.getDamage() * 1.15)
        if isinstance(damager, Player) and is_geto(damager):
            st = _uz_state(damager)
            if st is not None and isinstance(victim, LivingEntity):
                mob = st.get("mob")
                if mob in _ZOMBIE_TYPES: add_effect(victim, E_HUNGER, 5 * 20, 1)
                elif mob == "CAVE_SPIDER": add_effect(victim, E_POISON, 3 * 20, 0)
                elif mob == "WITHER_SKELETON": add_effect(victim, E_WITHER, 3 * 20, 0)
                elif mob == "BEE" and not st.get("used"):
                    st["used"] = True; add_effect(victim, E_POISON, 5 * 20, 0); add_effect(victim, E_NAUSEA, 5 * 20, 0)
                elif mob == "GOAT":
                    hand = damager.getInventory().getItemInMainHand()
                    if _uz_marked(hand, KEY_UZ_GOAT):
                        try:
                            vec = victim.getLocation().toVector().subtract(damager.getLocation().toVector())
                            if vec.lengthSquared() < 0.01: vec = damager.getLocation().getDirection()
                            vec.normalize().multiply(2.0); vec.setY(0.45); victim.setVelocity(vec)
                        except Exception: pass
                        damager.getInventory().setItemInMainHand(ItemStack(Material.AIR)); st["used"] = True
                elif mob in _PIGLIN_TYPES and not st.get("used"):
                    hand = damager.getInventory().getItemInMainHand()
                    if _uz_is_axe(hand):
                        st["used"] = True; raw = event.getDamage() * 1.50
                        if isinstance(victim, Player):
                            try:
                                if victim.isBlocking():
                                    event.setCancelled(True); victim.setCooldown(Material.SHIELD, 40); victim.damage(raw, damager); return
                            except Exception: pass
                        event.setDamage(raw)
        if isinstance(victim, Player) and is_geto(victim) and _uz_mob(victim) == "GUARDIAN":
            attacker = damager
            try:
                if hasattr(damager, "getShooter"):
                    s = damager.getShooter()
                    if isinstance(s, LivingEntity): attacker = s
            except Exception: pass
            if isinstance(attacker, LivingEntity) and not attacker.equals(victim):
                a_uid = uid(attacker)
                if a_uid not in uz_reflect_guard:
                    uz_reflect_guard.add(a_uid)
                    try: attacker.damage(max(0.0, event.getDamage() * 0.07))
                    finally: uz_reflect_guard.discard(a_uid)
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] damage: " + str(ex))


def _uz_on_item_damage(event):
    try:
        p = event.getPlayer()
        if is_geto(p) and _uz_mob(p) == "PHANTOM" and event.getItem().getType() == Material.ELYTRA:
            event.setCancelled(True)
    except Exception: pass


def _uz_on_consume(event):
    try:
        p = event.getPlayer(); item = event.getItem()
        if _uz_mob(p) != "COW" or not _uz_marked(item, KEY_UZ_MILK): return
        def restore_milk():
            try:
                if _uz_mob(p) != "COW": return
                p.getInventory().removeItem(ItemStack(Material.BUCKET, 1)); _uz_ensure_milk(p)
            except Exception: pass
        scheduler.runTaskLater(restore_milk, 1)
    except Exception: pass


def _uz_on_explode(event):
    try:
        e = event.getEntity()
        if e is None: return
        if uz_projectiles.pop(uid(e), None) == "ghast":
            try: event.blockList().clear()
            except Exception: pass
    except Exception: pass


def _uz_witch_clean(player_uuid):
    try:
        st = uz_active.get(player_uuid)
        if st is None or st.get("mob") != "WITCH" or st.get("end_tick", 0) <= now_tick(): return
        p = Bukkit.getPlayer(JUUID.fromString(player_uuid))
        if p is None or not p.isOnline(): return
        for pe in list(p.getActivePotionEffects()):
            try: p.removePotionEffect(pe.getType())
            except Exception: pass
        p.sendActionBar(u"§5Узумаки: §fэффекты очищены.")
        scheduler.runTaskLater(lambda: _uz_witch_clean(player_uuid), 5 * 20)
    except Exception: pass


def _uz_tick():
    try:
        now = now_tick()
        for p in Bukkit.getOnlinePlayers():
            if not is_geto(p): continue
            st = _uz_state(p)
            if st is None: continue
            mob = st.get("mob")
            if mob == "SPIDER":
                try:
                    loc = p.getLocation(); x = loc.getBlockX(); y = loc.getBlockY(); z = loc.getBlockZ(); world = p.getWorld(); touching = False
                    for dx, dz in ((1,0),(-1,0),(0,1),(0,-1)):
                        b1 = world.getBlockAt(x + dx, y, z + dz); b2 = world.getBlockAt(x + dx, y + 1, z + dz)
                        if b1.getType().isSolid() or b2.getType().isSolid(): touching = True; break
                    if touching:
                        v = p.getVelocity()
                        if v.getY() < 0.22: v.setY(0.22); p.setVelocity(v)
                        p.setFallDistance(0.0)
                except Exception: pass
            elif mob == "COW": _uz_ensure_milk(p)
            elif mob == "SHEEP":
                try: p.setFreezeTicks(0)
                except Exception: pass
            elif mob == "CAT":
                try:
                    for e in p.getWorld().getNearbyEntities(p.getLocation(), 10.0, 6.0, 10.0):
                        if e.getType().name() != "CREEPER": continue
                        try:
                            if hasattr(e, "setTarget"): e.setTarget(None)
                            away = e.getLocation().toVector().subtract(p.getLocation().toVector())
                            if away.lengthSquared() < 0.01: away = Vector(1.0, 0.0, 0.0)
                            away.normalize().multiply(0.45); away.setY(0.12); e.setVelocity(away)
                        except Exception: pass
                except Exception: pass
            elif mob == "ARMADILLO":
                try:
                    loc = p.getLocation(); last = st.get("last_loc")
                    if last is None or not last.getWorld().equals(loc.getWorld()) or last.distanceSquared(loc) > 0.01:
                        st["last_move_tick"] = now; st["last_loc"] = loc.clone()
                    elif now - st.get("last_move_tick", now) >= 5:
                        add_effect(p, E_RESISTANCE, 10, 1)
                except Exception: pass
            elif mob == "BAT":
                try:
                    if p.getHealth() > 1.0: p.setHealth(1.0)
                    if p.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR) and not p.getAllowFlight(): p.setAllowFlight(True)
                except Exception: pass
            elif mob == "IRON_GOLEM":
                try: p.setCooldown(Material.SHIELD, 10)
                except Exception: pass
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] tick: " + str(ex))
    scheduler.runTaskLater(_uz_tick, 2)


_uz_legacy_reset_state = _geto_reset_state
def _uz_reset_state(target_player):
    try: _uz_finish(uid(target_player), False)
    except Exception: pass
    _uz_legacy_reset_state(target_player)

try: _reset_reg.put("geto", _uz_reset_state)
except Exception: pass

listener_mgr.registerListener(_uz_on_interact, PlayerInteractEvent)
listener_mgr.registerListener(_uz_command_action, PlayerCommandPreprocessEvent)
listener_mgr.registerListener(_uz_on_damage_any, EntityDamageEvent)
listener_mgr.registerListener(_uz_on_damage_by, EntityDamageByEntityEvent)
listener_mgr.registerListener(_uz_on_item_damage, PlayerItemDamageEvent)
listener_mgr.registerListener(_uz_on_consume, PlayerItemConsumeEvent)
listener_mgr.registerListener(_uz_on_explode, EntityExplodeEvent)
scheduler.runTaskLater(_uz_tick, 2)
Bukkit.getLogger().info("[geto] Uzumaki extraction module loaded.")
# GETO_UZUMAKI_EXTRACTION_V1
'''

text = TARGET.read_text(encoding="utf-8")
if MARKER not in text:
    TARGET.write_text(text.rstrip() + "\n\n" + OVERLAY + "\n", encoding="utf-8")
