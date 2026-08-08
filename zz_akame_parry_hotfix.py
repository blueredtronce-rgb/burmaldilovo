# -*- coding: utf-8 -*-
"""
Temporary test-cg hotfix for Akame parry stun duration.

The current akame.py applies Slowness III + Blindness II for 16 ticks (0.8 s)
after a successful parry. This compatibility hotfix extends that exact pair to
20 ticks (1.0 s) without changing parry stance duration or cooldown.

After server testing this should be folded directly into akame.py and this file
can be removed.
"""

import pyspigot as ps

listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

from org.bukkit import NamespacedKey, Registry
from org.bukkit.entity import Player, LivingEntity, Projectile
from org.bukkit.event.entity import EntityDamageByEntityEvent
from org.bukkit.potion import PotionEffect


AKAME_NAMES = set([u"lokolo556", u"blueredtronce"])
PARRY_STUN_TICKS = 20


def _effect(key):
    try:
        return Registry.EFFECT.get(NamespacedKey.minecraft(key))
    except Exception:
        return None


E_SLOWNESS = _effect("slowness")
E_BLINDNESS = _effect("blindness")


def _is_akame(player):
    try:
        return isinstance(player, Player) and player.getName().lower() in AKAME_NAMES
    except Exception:
        return False


def _resolve_attacker(damager):
    if isinstance(damager, Projectile) or hasattr(damager, "getShooter"):
        try:
            shooter = damager.getShooter()
            if isinstance(shooter, LivingEntity):
                return shooter
        except Exception:
            return None
    if isinstance(damager, LivingEntity):
        return damager
    return None


def _is_original_parry_stun(attacker):
    """Recognize the exact debuff pair currently emitted by akame.py."""
    if attacker is None or E_SLOWNESS is None or E_BLINDNESS is None:
        return False
    try:
        slow = attacker.getPotionEffect(E_SLOWNESS)
        blind = attacker.getPotionEffect(E_BLINDNESS)
        if slow is None or blind is None:
            return False
        # akame.py: Slowness III (amp 2), Blindness II (amp 1), 16 ticks.
        if slow.getAmplifier() != 2 or blind.getAmplifier() != 1:
            return False
        # Run one tick after the hit, so the original 16 ticks are normally 15.
        # Keep a little tolerance while refusing unrelated long-duration debuffs.
        return slow.getDuration() <= 16 and blind.getDuration() <= 16
    except Exception:
        return False


def _set_parry_stun(attacker):
    try:
        attacker.removePotionEffect(E_SLOWNESS)
        attacker.removePotionEffect(E_BLINDNESS)
        attacker.addPotionEffect(PotionEffect(
            E_SLOWNESS, PARRY_STUN_TICKS, 2, True, False, True
        ))
        attacker.addPotionEffect(PotionEffect(
            E_BLINDNESS, PARRY_STUN_TICKS, 1, True, False, True
        ))
    except Exception:
        pass


def on_damage_by(event):
    victim = event.getEntity()
    if not _is_akame(victim):
        return

    attacker = _resolve_attacker(event.getDamager())
    if attacker is None:
        return

    # akame.py handles the actual parry in the damage event. Check on the next
    # tick, after all listeners have finished, and only touch its exact debuff
    # signature. This avoids changing ordinary hits or unrelated stuns.
    def verify_and_extend():
        try:
            if attacker.isValid() and _is_original_parry_stun(attacker):
                _set_parry_stun(attacker)
        except Exception:
            pass

    scheduler.runTaskLater(verify_and_extend, 1)


listener_mgr.registerListener(on_damage_by, EntityDamageByEntityEvent)

print("[akame_parry_hotfix] Loaded: parry stun = 1.0 s (20 ticks)")
