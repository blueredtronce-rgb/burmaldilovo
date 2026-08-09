# -*- coding: utf-8 -*-

from org.bukkit import Bukkit, Material
from org.bukkit.command import Command, TabCompleter
from java.lang import Runnable
from java.util import ArrayList


WORLD_NAME = "world"

BLOCKS = [
    (-2397, 16, 509),
    (-2396, 16, 509)
]

MODE_DELAYS = {
    "1": 40,    # 2 sec
    "2": 100    # 5 sec
}


def get_pyspigot_plugin():
    try:
        plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
        if plugin:
            return plugin

        for item in Bukkit.getPluginManager().getPlugins():
            if "pyspigot" in str(item.getName()).lower():
                return item
    except Exception:
        pass

    return None


def get_command_map():
    server = Bukkit.getServer()

    try:
        if hasattr(server, "getCommandMap"):
            command_map = server.getCommandMap()
            if command_map is not None:
                return command_map
    except Exception:
        pass

    try:
        field = server.getClass().getDeclaredField("commandMap")
        field.setAccessible(True)
        return field.get(server)
    except Exception:
        return None


class RestoreRunnable(Runnable):
    def __init__(self, world):
        self.world = world

    def run(self):
        try:
            for x, y, z in BLOCKS:
                self.world.getBlockAt(x, y, z).setType(
                    Material.OXIDIZED_CUT_COPPER
                )
        except Exception as exc:
            Bukkit.getLogger().warning(
                "[HHURA] Restore error: " + str(exc)
            )


def execute_hhura(sender, label, args):
    args = list(args)

    if len(args) != 1 or str(args[0]) not in MODE_DELAYS:
        sender.sendMessage("Usage: /hhura <1|2>")
        return True

    mode = str(args[0])
    delay = MODE_DELAYS[mode]

    world = Bukkit.getWorld(WORLD_NAME)

    if world is None:
        sender.sendMessage(
            "World '%s' not found." % WORLD_NAME
        )
        return True

    try:
        # Open
        for x, y, z in BLOCKS:
            world.getBlockAt(x, y, z).setType(Material.AIR)

        plugin = get_pyspigot_plugin()

        if plugin is None:
            sender.sendMessage("PySpigot plugin not found.")
            return True

        Bukkit.getScheduler().runTaskLater(
            plugin,
            RestoreRunnable(world),
            delay
        )

    except Exception as exc:
        sender.sendMessage(
            "HHURA error: " + str(exc)
        )

    return True


def tab_hhura(sender, alias, args):
    result = ArrayList()

    try:
        args = list(args)

        if len(args) <= 1:
            prefix = str(args[0]).lower() if args else ""

            for value in ["1", "2"]:
                if value.startswith(prefix):
                    result.add(value)

    except Exception:
        pass

    return result


class PyBukkitCommand(Command, TabCompleter):

    def __init__(
        self,
        name,
        description,
        usage,
        aliases,
        executor,
        completer
    ):
        Command.__init__(
            self,
            name,
            description,
            usage,
            aliases
        )

        self.cmd_name = name
        self.executor = executor
        self.completer = completer

    def execute(self, sender, commandLabel, args):
        try:
            return self.executor(
                sender,
                commandLabel,
                list(args)
            )
        except Exception as exc:
            Bukkit.getLogger().warning(
                "[HHURA] Command error: " + str(exc)
            )
            return True

    def tabComplete(self, *args):
        try:
            if self.completer:
                result = self.completer(*args)

                if result is not None:
                    return result
        except Exception:
            pass

        return ArrayList()

    def onTabComplete(self, *args):
        return self.tabComplete(*args)


registered = False


def unregister_command():
    command_map = get_command_map()

    if command_map is None:
        return

    try:
        known = command_map.getKnownCommands()
    except Exception:
        known = None

    if known is None:
        try:
            current_class = command_map.getClass()

            while current_class is not None:
                try:
                    field = current_class.getDeclaredField(
                        "knownCommands"
                    )
                    field.setAccessible(True)
                    known = field.get(command_map)
                    break
                except Exception:
                    current_class = current_class.getSuperclass()
        except Exception:
            pass

    if known is None:
        return

    for key in [
        "hhura",
        "hhura:hhura"
    ]:
        try:
            old_command = known.get(key)

            if old_command is not None:
                try:
                    old_command.unregister(command_map)
                except Exception:
                    pass

            known.remove(key)

        except Exception:
            pass


def register_command():
    global registered

    command_map = get_command_map()

    if command_map is None:
        Bukkit.getLogger().warning(
            "[HHURA] CommandMap not found."
        )
        return

    unregister_command()

    command = PyBukkitCommand(
        "hhura",
        "HHURA door controller",
        "/hhura <1|2>",
        [],
        execute_hhura,
        tab_hhura
    )

    try:
        command_map.register(
            "hhura",
            command
        )

        registered = True

        try:
            Bukkit.getServer().syncCommands()
        except Exception:
            pass

        Bukkit.getLogger().info(
            "[HHURA] Command /hhura registered."
        )

    except Exception as exc:
        Bukkit.getLogger().warning(
            "[HHURA] Registration error: " + str(exc)
        )


def on_enable():
    register_command()


def on_disable():
    global registered

    unregister_command()

    try:
        Bukkit.getServer().syncCommands()
    except Exception:
        pass

    registered = False


def start(script=None):
    on_enable()


def stop(script=None):
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()