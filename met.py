# -*- coding: utf-8 -*-

import random

from org.bukkit import Bukkit
from org.bukkit.command import CommandSender

import pyspigot as ps


PREFIX = u"§3§l[Meteorites] §r"

CENTER_X = -4000
CENTER_Z = -4000
RADIUS = 600


def coords():
    x = random.randint(CENTER_X - RADIUS, CENTER_X + RADIUS)
    z = random.randint(CENTER_Z - RADIUS, CENTER_Z + RADIUS)
    return x, z


def allowed(sender):
    try:
        return sender.isOp() or sender.hasPermission("meteorites.admin")
    except:
        return False


def send(sender, text):
    sender.sendMessage(PREFIX + text)


def command(sender, label, args):

    if not allowed(sender):
        sender.sendMessage(u"§cUnknown command. Type \"/help\" for help.")
        return True

    if len(args) == 0:
        send(sender, u"§7Meteorites Simulation Core §av1.4.7")
        send(sender, u"§7Используйте: §f/meteor status|scan|next|coords|latveria|debug")
        return True

    sub = args[0].lower()

    # /meteor status
    if sub == "status":
        x, z = coords()

        send(sender, u"§aSYSTEM ONLINE")
        send(sender, u"§7Scheduler: §aACTIVE")
        send(sender, u"§7Impact prediction: §aENABLED")
        send(sender, u"§7Tracked meteor signatures: §e%d" % random.randint(2, 9))
        send(sender, u"§7Current predicted sector: §b%d ~ %d" % (x, z))

        if random.random() < 0.55:
            send(sender, u"§6Elevated meteor activity detected near §cLATVERIA§6.")

        return True

    # /meteor scan
    if sub == "scan":
        x, z = coords()

        send(sender, u"§7Starting atmospheric scan...")
        send(sender, u"§7Trajectory calculation: §aCOMPLETE")
        send(sender, u"§7Possible impact detected at §b%d ~ %d" % (x, z))

        chance = random.randint(61, 99)

        send(sender, u"§7Impact confidence: §e%d%%" % chance)

        if random.random() < 0.7:
            send(sender, u"§eWARNING: §6Trajectory intersects Latveria monitoring sector.")

        return True

    # /meteor next
    if sub == "next":
        x, z = coords()

        tiers = [
            u"§aCOMMON",
            u"§bRARE",
            u"§dEPIC",
            u"§6LEGENDARY"
        ]

        tier = random.choice(tiers)

        send(sender, u"§6Next meteor event generated.")
        send(sender, u"§7Predicted coordinates: §b%d ~ %d" % (x, z))
        send(sender, u"§7LootTier: %s" % tier)
        send(sender, u"§7CustomEnchantments: §aENABLED")
        send(sender, u"§7Spawn task: §eQUEUED")

        return True

    # /meteor coords
    if sub == "coords":
        x, z = coords()

        # Только координаты
        sender.sendMessage(u"§b§l%d ~ %d" % (x, z))

        return True

    # /meteor latveria
    if sub == "latveria":
        x, z = coords()

        messages = [
            u"§eMeteor activity near §cLatveria §eis above normal levels.",
            u"§6Latveria marked as §cPRIMARY IMPACT SECTOR§6.",
            u"§eMultiple atmospheric signatures detected near §cLatveria§e.",
            u"§6Trajectory model predicts possible meteor shower near §cLatveria§6.",
            u"§cWARNING: §eLatveria monitoring sector entered meteor alert state."
        ]

        send(sender, random.choice(messages))
        send(sender, u"§7Estimated impact point: §b%d ~ %d" % (x, z))
        send(sender, u"§7Probability: §e%d%%" % random.randint(73, 99))

        return True

    # /meteor debug
    if sub == "debug":
        x, z = coords()

        fake_id = random.randint(1000, 9999)
        signatures = random.randint(1, 8)

        send(sender, u"§8[DEBUG] Scheduler tick completed.")
        send(sender, u"§8[DEBUG] Active signatures: %d" % signatures)
        send(sender, u"§8[DEBUG] Meteor ID: MTR-%d" % fake_id)
        send(sender, u"§8[DEBUG] Candidate impact: %d ~ %d" % (x, z))
        send(sender, u"§8[DEBUG] Chunk validation: OK")
        send(sender, u"§8[DEBUG] Loot generator initialized.")
        send(sender, u"§8[DEBUG] Latveria proximity check: %s" %
             (u"POSITIVE" if random.random() < 0.6 else u"NEGATIVE"))

        return True

    send(sender, u"§cUnknown subcommand.")
    return True


# Регистрация через PySpigot
ps.command.registerCommand(
    command,
    "meteor",
    None,
    "meteorites.admin"
)

Bukkit.getConsoleSender().sendMessage(
    u"§3[Meteorites] §aMeteorites simulation script loaded successfully."
)