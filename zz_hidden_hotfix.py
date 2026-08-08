# -*- coding: utf-8 -*-
"""
Temporary test-cg hotfix for hidden.py.

Fixes two visibility gaps without touching main:
- Hidden players are hidden from EVERY other player, including OP viewers.
- Visibility is reconciled again after join so Leaf/Paper/TAB refreshes cannot
  re-add a hidden player to the client player list after PlayerJoinEvent.

After testing, fold this logic directly into hidden.py and remove this file.
"""

import pyspigot as ps

listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

from java.lang import System
from org.bukkit import Bukkit
from org.bukkit.event.player import PlayerJoinEvent


HIDDEN_SESSIONS_PROPERTY = u"SmartY_Hidden_ActiveSessions"


def _uid(player):
    try:
        return str(player.getUniqueId())
    except Exception:
        return None


def _plugin():
    try:
        pm = Bukkit.getPluginManager()
        p = pm.getPlugin("PySpigot")
        if p is not None:
            return p
        for candidate in pm.getPlugins():
            if "pyspigot" in str(candidate.getName()).lower():
                return candidate
    except Exception:
        pass
    return None


def _active_sessions():
    try:
        sessions = System.getProperties().get(HIDDEN_SESSIONS_PROPERTY)
        return sessions if sessions is not None else []
    except Exception:
        return []


def _hide(viewer, target, plugin):
    if viewer is None or target is None or viewer == target:
        return
    try:
        viewer.hidePlayer(plugin, target)
        return
    except TypeError:
        try:
            viewer.hidePlayer(target)
            return
        except Exception:
            pass
    except Exception:
        pass


def _find_online(uuid_str):
    for player in Bukkit.getOnlinePlayers():
        if _uid(player) == uuid_str:
            return player
    return None


def reconcile_hidden_visibility():
    """Force every active Hidden session out of every other client's world/TAB."""
    plugin = _plugin()
    if plugin is None:
        return

    try:
        sessions = list(_active_sessions())
    except Exception:
        sessions = []

    for hidden_uuid in sessions:
        target = _find_online(str(hidden_uuid))
        if target is None:
            continue
        for viewer in Bukkit.getOnlinePlayers():
            # Deliberately NO isOp() exception: Hidden means hidden from everyone.
            if viewer != target:
                _hide(viewer, target, plugin)


def _schedule_reconcile():
    # Player info/TAB packets can be refreshed after PlayerJoinEvent. Re-apply
    # hidePlayer over the next few seconds so a later server/plugin refresh
    # cannot make a Hidden player reappear.
    for delay in (1, 5, 20, 60):
        scheduler.runTaskLater(reconcile_hidden_visibility, delay)


def on_player_join(event):
    _schedule_reconcile()


listener_mgr.registerListener(on_player_join, PlayerJoinEvent)

# Also repair already-online Hidden sessions when this script is hot-loaded.
_schedule_reconcile()

Bukkit.getLogger().info(
    "[hidden_hotfix] Loaded: hide Hidden sessions from all viewers + delayed TAB re-hide"
)
