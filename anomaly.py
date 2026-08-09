# -*- coding: utf-8 -*-
"""
SmartY-Anomalies v1.0.0
Production PySpigot/Jython 2.7 anomaly system for Paper/Leaf 1.21.x.

Design invariants:
- Never force-load chunks.
- Never import town.py/economy.py; use published JVM managers.
- Journal original BlockData before every world mutation.
- Require CoreProtect API confirmation for both sides of every block mutation.
- Restore only blocks still matching anomaly-applied BlockData.
- Atomic JSON saves with backup and fail-closed load behavior.
- Admin-only discovery/notifications; ordinary players can only use the
  deliberately hidden /anomaly info while standing inside an active zone.
"""

import json
import math
import os
import random
import re
import sys
import time
import traceback

try:
    unicode
except NameError:
    unicode = str

try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

try:
    from org.bukkit import Bukkit, ChatColor, Location, Material, Particle, World
    from org.bukkit.block import BlockFace
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.entity import Player, LivingEntity
    from org.bukkit.event import EventPriority, HandlerList, Listener
    from org.bukkit.event.player import PlayerBedEnterEvent, PlayerCommandSendEvent, PlayerCommandPreprocessEvent
    from org.bukkit.event.entity import CreatureSpawnEvent
    from org.bukkit.event.world import ChunkLoadEvent
    from org.bukkit.event.block import BlockPlaceEvent, BlockBreakEvent
    from org.bukkit.inventory import InventoryHolder
    from org.bukkit.plugin import EventExecutor
    from org.bukkit.boss import BarColor, BarStyle
    BUKKIT_AVAILABLE = True
except ImportError:
    Bukkit = None
    ChatColor = None
    Location = None
    Material = None
    Particle = None
    World = None
    BlockFace = None
    class Command(object):
        pass
    class TabCompleter(object):
        pass
    Player = object
    LivingEntity = object
    EventPriority = None
    HandlerList = None
    Listener = object
    PlayerBedEnterEvent = None
    PlayerCommandSendEvent = None
    PlayerCommandPreprocessEvent = None
    CreatureSpawnEvent = None
    ChunkLoadEvent = None
    BlockPlaceEvent = None
    BlockBreakEvent = None
    InventoryHolder = object
    EventExecutor = object
    BarColor = None
    BarStyle = None
    BUKKIT_AVAILABLE = False

try:
    from org.bukkit.potion import PotionEffect, PotionEffectType
except ImportError:
    PotionEffect = None
    PotionEffectType = None

try:
    from java.lang import Runnable, String as JavaString, StringBuilder, System
    JAVA_AVAILABLE = True
except ImportError:
    Runnable = object
    JavaString = str
    StringBuilder = None
    System = None
    JAVA_AVAILABLE = False

try:
    from java.util import ArrayList
except ImportError:
    ArrayList = list

try:
    from java.nio.file import Files, Paths, StandardCopyOption
    JAVA_NIO_AVAILABLE = True
except ImportError:
    Files = None
    Paths = None
    StandardCopyOption = None
    JAVA_NIO_AVAILABLE = False


def get_script_dir():
    if "__file__" in globals() and __file__:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            pass
    cwd = os.getcwd()
    guess = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.exists(guess):
        return guess
    return cwd


def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if JAVA_AVAILABLE and hasattr(value, "getBytes"):
        try:
            return unicode(value.getBytes("UTF-8"), "utf-8")
        except Exception:
            pass
    if isinstance(value, str):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return value.decode("cp1251")
            except Exception:
                try:
                    return unicode(value, "utf-8", "ignore")
                except Exception:
                    return unicode(value)
    return unicode(str(value))


def to_java_string(value):
    text = to_unicode(value)
    if not JAVA_AVAILABLE:
        return text
    if isinstance(text, JavaString):
        return text
    if StringBuilder is not None:
        try:
            builder = StringBuilder()
            for ch in text:
                builder.appendCodePoint(ord(ch))
            return builder.toString()
        except Exception:
            pass
    try:
        return JavaString(text)
    except Exception:
        return text


def colorize(value):
    text = to_unicode(value)
    if not text:
        return u""
    if BUKKIT_AVAILABLE and ChatColor is not None:
        try:
            return to_unicode(ChatColor.translateAlternateColorCodes('&', to_java_string(text)))
        except Exception:
            pass
    return re.sub(r'&([0-9a-fk-or])', u'', text, flags=re.IGNORECASE)


def send_message(target, value):
    text = colorize(value)
    if BUKKIT_AVAILABLE and target is not None:
        try:
            target.sendMessage(to_java_string(text))
            return
        except Exception:
            pass
    try:
        print("[SmartY-Anomalies] " + to_unicode(text))
    except Exception:
        pass


def log_info(value):
    if BUKKIT_AVAILABLE and Bukkit is not None:
        try:
            send_message(Bukkit.getConsoleSender(), u"&5[SmartY-Anomalies] &7" + to_unicode(value))
            return
        except Exception:
            pass
    try:
        print("[SmartY-Anomalies] " + to_unicode(value))
    except Exception:
        pass


def build_java_list(values):
    if not BUKKIT_AVAILABLE:
        return values
    result = ArrayList()
    for value in values:
        result.add(to_java_string(value))
    return result


def reject_json_constant(value):
    raise ValueError("non-finite JSON number: {0}".format(value))


def safe_int(value, default=0, minimum=None, maximum=None):
    try:
        result = int(value)
        if minimum is not None and result < minimum:
            return default
        if maximum is not None and result > maximum:
            return default
        return result
    except Exception:
        return default


def safe_float(value, default=0.0, minimum=None, maximum=None):
    try:
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            return default
        if minimum is not None and result < minimum:
            return default
        if maximum is not None and result > maximum:
            return default
        return result
    except Exception:
        return default


def now_ts():
    return int(time.time())


def dist_sq_2d(x1, z1, x2, z2):
    dx = float(x1) - float(x2)
    dz = float(z1) - float(z2)
    return dx * dx + dz * dz


def chunk_coord(block_coord):
    return int(math.floor(float(block_coord) / 16.0))


def get_pyspigot_plugin():
    if not BUKKIT_AVAILABLE:
        return None
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


class AnomalyConfig(object):
    PLUGIN_NAME = u"SmartY-Anomalies"
    VERSION = u"1.0.0"
    PREFIX = u"&5&l[Аномалии]&r "

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "anomalies.json")
    SPAWN_LOG_FILE = os.path.join(DATA_DIR, "anomaly-spawn.log")
    ACTION_LOG_FILE = os.path.join(DATA_DIR, "anomaly-actions.log")
    ERROR_LOG_FILE = os.path.join(DATA_DIR, "anomaly-errors.log")
    TOWNS_FILE = os.path.join(DATA_DIR, "cities.json")

    COREPROTECT_PLUGIN_NAME = "CoreProtect"
    COREPROTECT_MIN_API_VERSION = 10
    COREPROTECT_REQUIRED_FOR_MUTATION = True
    COREPROTECT_APPLY_ACTOR = "SmartYAnomaly"
    COREPROTECT_RESTORE_ACTOR = "SmartYRestore"

    ADMIN_PERMISSION = "server.anomaly.admin"

    # Autospawn runs once every five minutes. Zero means no global cap.
    AUTO_CHECK_TICKS = 20 * 3600
    STAGE_CHECK_TICKS = 20 * 60
    DISTORTION_TICKS = 20
    PARTICLE_TICKS = 20
    PLAYER_EFFECT_TICKS = 20
    STABILIZE_TICKS = 5
    DIRTY_FLUSH_SECONDS = 10
    DIRTY_FLUSH_TICKS = 20 * 10

    MAX_ACTIVE = 0
    ANOMALY_MIN_DISTANCE = 250.0
    TOWN_MIN_DISTANCE = 300.0
    EXPLORER_MIN_FROM_TOWN = 300.0
    EXPLORER_POINT_MIN = 0.0
    EXPLORER_POINT_MAX = 50.0
    # A loaded city normally keeps only its nearby terrain loaded.  Safety
    # checks still reject buildings, containers and artificial terrain.
    CITY_POINT_MIN = 180.0
    CITY_POINT_MAX = 320.0
    RECENT_PLAYER_COOLDOWN = 0
    CITY_COOLDOWN = 0

    STAGE_SECONDS = 96 * 3600
    STAGE1_RADIUS = 25
    STAGE2_RADIUS = 35
    STAGE1_SURFACE_TARGET = 250
    STAGE2_ADDITIONAL_TARGET = 260
    STAGE2_SURFACE_TARGET_TOTAL = 510

    BLINDNESS_MIN_SECONDS = 55
    BLINDNESS_MAX_SECONDS = 95
    BLINDNESS_DURATION_TICKS = 60

    SAFETY_CONTAINER_RADIUS = 40
    SAFETY_SAMPLE_RADIUS = 25
    SAFETY_SAMPLE_STEP = 4
    SAFETY_MAX_ARTIFICIAL_RATIO = 0.10
    SAFETY_MAX_ARTIFICIAL_ABSOLUTE_MIN = 6

    DISTORTION_MAX_PER_CYCLE = 2
    PARTICLE_BURSTS_PER_CYCLE = 3
    PARTICLE_MAX_HEIGHT = 20
    PARTICLE_RISE_BLOCKS_PER_SECOND = 2
    VEIN_CHANCE = 0.08

    STABILIZE_SECONDS = 30
    REWARD_AMOUNT = 5000.0

    TOWN_STATE_PROPERTY = "SmartY_TownState"
    ECONOMY_PROPERTIES = ("PySpigot_EconomyManager", "SmartY_EconomyManager")
    MANAGER_PROPERTY = "SmartY_AnomalyManager"
    COMMAND_PROPERTY = "SmartY_AnomalyCommand"

    DEFAULT_STATE = {
        "schema_version": 1,
        "auto_spawn": False,
        "next_id": 1,
        "anomalies": {},
        "recent_players": {},
        "city_last_event": {},
        "spawn_rotation": {"skip_city_id": None, "skip_player_uuid": None}
    }


def append_utf8_log(path, category, value):
    """Append one durable UTF-8 line without depending on Bukkit logging."""
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)
        line = u"{0} [{1}] {2}\n".format(
            time.strftime("%Y-%m-%d %H:%M:%S"), to_unicode(category),
            to_unicode(value).replace(u"\r", u" ").replace(u"\n", u" | ")
        )
        with open(path, "ab") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        return True
    except Exception:
        return False


def log_action(value):
    append_utf8_log(AnomalyConfig.ACTION_LOG_FILE, "ACTION", value)
    log_info(value)


def log_error(value, exc=None):
    detail = to_unicode(value)
    if exc is not None:
        detail += u": " + to_unicode(exc)
        try:
            detail += u" | " + to_unicode(traceback.format_exc())
        except Exception:
            pass
    append_utf8_log(AnomalyConfig.ERROR_LOG_FILE, "ERROR", detail)
    log_info(u"ERROR: " + detail)


REPLACEABLE_GROUND_NAMES = set([
    "GRASS_BLOCK", "DIRT", "COARSE_DIRT", "PODZOL", "MYCELIUM",
    "ROOTED_DIRT", "STONE", "DEEPSLATE", "TUFF", "ANDESITE",
    "DIORITE", "GRANITE", "SAND", "RED_SAND", "GRAVEL", "CLAY",
    "MUD", "MUDDY_MANGROVE_ROOTS", "SNOW_BLOCK", "PACKED_ICE",
    "BLUE_ICE", "CALCITE", "DRIPSTONE_BLOCK", "MOSS_BLOCK"
])

NATURAL_EXACT_NAMES = set(list(REPLACEABLE_GROUND_NAMES) + [
    "AIR", "CAVE_AIR", "VOID_AIR", "WATER", "LAVA", "SNOW",
    "SHORT_GRASS", "TALL_GRASS", "GRASS", "FERN", "LARGE_FERN",
    "DEAD_BUSH", "VINE", "GLOW_LICHEN", "MOSS_CARPET", "SEAGRASS",
    "TALL_SEAGRASS", "KELP", "KELP_PLANT", "LILY_PAD", "BAMBOO",
    "BAMBOO_SAPLING", "CACTUS", "SUGAR_CANE", "BROWN_MUSHROOM",
    "RED_MUSHROOM", "MUSHROOM_STEM", "BROWN_MUSHROOM_BLOCK",
    "RED_MUSHROOM_BLOCK", "AZALEA", "FLOWERING_AZALEA",
    "BIG_DRIPLEAF", "BIG_DRIPLEAF_STEM", "SMALL_DRIPLEAF",
    "SWEET_BERRY_BUSH", "POWDER_SNOW", "SCULK", "SCULK_VEIN"
])

WET_SURFACE_NAMES = set([
    "WATER", "LAVA", "KELP", "KELP_PLANT", "SEAGRASS",
    "TALL_SEAGRASS", "LILY_PAD", "BUBBLE_COLUMN"
])

DISTORTION_MATERIAL_NAMES = [
    "SCULK", "SCULK", "SCULK", "SCULK",
    "TUFF", "TUFF",
    "DEEPSLATE", "DEEPSLATE",
    "BLACKSTONE", "BLACKSTONE"
]


def material_name(material):
    if material is None:
        return ""
    try:
        return str(material.name())
    except Exception:
        return str(material)


def is_replaceable_ground(material):
    return material_name(material) in REPLACEABLE_GROUND_NAMES


def is_natural_scene_material(material):
    name = material_name(material)
    if name in NATURAL_EXACT_NAMES:
        return True
    suffixes = (
        "_LEAVES", "_LOG", "_WOOD", "_SAPLING", "_FLOWER", "_TULIP",
        "_CORAL", "_CORAL_BLOCK", "_CORAL_FAN", "_WALL_CORAL_FAN"
    )
    for suffix in suffixes:
        if name.endswith(suffix):
            return True
    if name in ("OAK_ROOTS", "MANGROVE_ROOTS", "HANGING_ROOTS"):
        return True
    return False


def atomic_replace_file(source_path, target_path):
    """
    Replace target with source.

    Uses Java NIO on Jython/Windows because os.rename() cannot replace
    an existing destination there.
    """
    if JAVA_NIO_AVAILABLE:
        source = Paths.get(to_java_string(source_path))
        target = Paths.get(to_java_string(target_path))

        try:
            Files.move(
                source,
                target,
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE
            )
            return
        except Exception:
            # Some Windows/filesystem combinations do not support
            # ATOMIC_MOVE. REPLACE_EXISTING is still required.
            Files.move(
                source,
                target,
                StandardCopyOption.REPLACE_EXISTING
            )
            return

    if hasattr(os, "replace"):
        os.replace(source_path, target_path)
        return

    # Last-resort fallback for old Python/Jython environments.
    if os.path.exists(target_path):
        os.remove(target_path)

    os.rename(source_path, target_path)

class JsonStorage(object):
    def __init__(self, path):
        self.path = path
        self.backup_path = path + ".bak"
        self.loaded_ok = False
        self.primary_valid = False

    def ensure_dir(self):
        folder = os.path.dirname(self.path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

    def normalize(self, data):
        result = {
            "schema_version": 1,
            "auto_spawn": False,
            "next_id": 1,
            "anomalies": {},
            "recent_players": {},
            "city_last_event": {},
            "spawn_rotation": {"skip_city_id": None, "skip_player_uuid": None}
        }
        if isinstance(data, dict):
            for key in result.keys():
                if key in data:
                    result[key] = data[key]
        if not isinstance(result.get("anomalies"), dict):
            result["anomalies"] = {}
        if not isinstance(result.get("recent_players"), dict):
            result["recent_players"] = {}
        if not isinstance(result.get("city_last_event"), dict):
            result["city_last_event"] = {}
        if not isinstance(result.get("spawn_rotation"), dict):
            result["spawn_rotation"] = {}
        result["spawn_rotation"].setdefault("skip_city_id", None)
        result["spawn_rotation"].setdefault("skip_player_uuid", None)
        result["next_id"] = max(1, safe_int(result.get("next_id"), 1))
        result["auto_spawn"] = bool(result.get("auto_spawn", False))
        return result

    def _read(self, path):
        with open(path, "r") as handle:
            data = json.load(handle, parse_constant=reject_json_constant)
        if not isinstance(data, dict):
            raise ValueError("anomaly database root must be an object")
        return self.normalize(data)

    def load(self):
        self.loaded_ok = False
        self.primary_valid = False
        self.ensure_dir()
        if not os.path.exists(self.path):
            if os.path.exists(self.backup_path):
                try:
                    data = self._read(self.backup_path)
                    self.loaded_ok = True
                    log_info(u"Loaded anomaly data from backup because primary file is missing.")
                    return data
                except Exception as exc:
                    log_error(u"Cannot read anomaly backup", exc)
                    return self.normalize({})
            self.loaded_ok = True
            return self.normalize({})
        try:
            data = self._read(self.path)
            self.loaded_ok = True
            self.primary_valid = True
            return data
        except UnicodeDecodeError:
            try:
                with open(self.path, "rb") as handle:
                    raw = handle.read()
                data = json.loads(raw.decode("utf-8"), parse_constant=reject_json_constant)
                data = self.normalize(data)
                self.loaded_ok = True
                self.primary_valid = True
                return data
            except Exception as exc:
                log_error(u"Cannot read anomalies.json as UTF-8", exc)
        except Exception as exc:
            log_error(u"Cannot read anomalies.json", exc)

        if os.path.exists(self.backup_path):
            try:
                data = self._read(self.backup_path)
                self.loaded_ok = True
                log_info(u"Loaded anomaly data from backup; primary file is damaged.")
                return data
            except Exception as exc:
                log_error(u"Cannot read anomaly backup", exc)
        return self.normalize({})

    def save(self, data):
        if not self.loaded_ok:
            log_error(u"Refusing to overwrite anomaly data that failed to load")
            return False
        temp_path = self.path + ".tmp"
        try:
            self.ensure_dir()
            payload = self.normalize(data)
            with open(temp_path, "w") as handle:
                handle.write(json.dumps(
                    payload, indent=2, ensure_ascii=True,
                    sort_keys=True, allow_nan=False
                ))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass

            if self.primary_valid and os.path.exists(self.path):
                backup_tmp = self.backup_path + ".tmp"
                try:
                    with open(self.path, "rb") as source:
                        with open(backup_tmp, "wb") as target:
                            target.write(source.read())
                            target.flush()
                            try:
                                os.fsync(target.fileno())
                            except Exception:
                                pass

                    atomic_replace_file(backup_tmp, self.backup_path)

                except Exception as exc:
                    log_error(u"Cannot update anomaly backup", exc)

            atomic_replace_file(temp_path, self.path)

            self.primary_valid = True
            return True
        except Exception as exc:
            log_error(u"Cannot save anomalies.json", exc)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False


class CallbackRunnable(Runnable):
    def __init__(self, callback):
        self.callback = callback

    def run(self):
        try:
            self.callback()
        except Exception as exc:
            log_error(u"Scheduled anomaly task failed", exc)


class EmptyListener(Listener):
    pass


class CallbackExecutor(EventExecutor):
    def __init__(self, callback):
        self.callback = callback

    def execute(self, listener, event):
        try:
            self.callback(event)
        except Exception as exc:
            log_error(u"Anomaly event failed", exc)


class AnomalyManager(object):
    def __init__(self):
        self.storage = JsonStorage(AnomalyConfig.DATA_FILE)
        self.data = self.storage.load()
        self.plugin = get_pyspigot_plugin()
        self.listeners = []
        self.task_ids = []
        self.command = None
        self.command_map = None
        self.active = False
        self.blindness_next = {}
        self.bossbars = {}
        self.cleanup_session = None
        self.next_auto_spawn_at = 0
        self.last_auto_spawn_at = 0
        self.auto_spawn_notes = []
        self.coreprotect_api = None
        self.coreprotect_api_version = 0
        self.coreprotect_status_text = u"не проверен"
        self.last_coreprotect_retry_at = 0
        self.last_coreprotect_unavailable_log_at = 0
        self.error_throttle = {}
        self.last_dirty_flush = 0
        self.dirty = False
        self.normalize_runtime_data()

    def normalize_runtime_data(self):
        self.data = self.storage.normalize(self.data)
        for anomaly_id, anomaly in self.data.get("anomalies", {}).items():
            if not isinstance(anomaly, dict):
                continue
            anomaly.setdefault("id", anomaly_id)
            anomaly.setdefault("status", "ACTIVE")
            anomaly.setdefault("stage", 1)
            anomaly.setdefault("radius", AnomalyConfig.STAGE1_RADIUS)
            anomaly.setdefault("created_at", now_ts())
            anomaly.setdefault("stage_started_at", anomaly.get("created_at", now_ts()))
            anomaly.setdefault("source_type", "UNKNOWN")
            anomaly.setdefault("source_player_uuid", None)
            anomaly.setdefault("source_player_name", None)
            anomaly.setdefault("city_id", None)
            anomaly.setdefault("city_name", None)
            anomaly.setdefault("reporter_uuid", None)
            anomaly.setdefault("reporter_name", None)
            anomaly.setdefault("blocks", [])
            if not isinstance(anomaly.get("blocks"), list):
                anomaly["blocks"] = []
            anomaly.setdefault("player_touched_columns", {})
            if not isinstance(anomaly.get("player_touched_columns"), dict):
                anomaly["player_touched_columns"] = {}
            anomaly.setdefault("stabilization_started_at", 0)
            anomaly.setdefault("stabilization_total", len(anomaly.get("blocks", [])))
            anomaly.setdefault("fixed_at", 0)
            reward = anomaly.setdefault("reward", {})
            if not isinstance(reward, dict):
                reward = {}
                anomaly["reward"] = reward
            reward.setdefault("operation_id", "anomaly_reward_v1:{0}".format(anomaly_id))
            reward.setdefault("state", "NOT_READY")
            reward.setdefault("amount", AnomalyConfig.REWARD_AMOUNT)
            reward.setdefault("prepared_at", 0)
            reward.setdefault("before_balance", None)
            reward.setdefault("expected_balance", None)
            reward.setdefault("paid_at", 0)
            reward.setdefault("last_error", None)
            for record in anomaly.get("blocks", []):
                if isinstance(record, dict):
                    record.setdefault("state", "APPLIED")
                    record.setdefault("kind", "surface")

    def start(self):
        if not BUKKIT_AVAILABLE or self.plugin is None:
            log_info(u"PySpigot/Bukkit is unavailable; anomaly runtime was not started.")
            return
        self.active = True
        self.unregister_previous_command()
        self.register_command()
        self.register_events()
        self.initialize_coreprotect()
        self.schedule_tasks()
        self.reconcile_planned_records()
        self.resume_active_anomalies()
        self.resume_bossbars()
        self.recover_prepared_rewards()
        if JAVA_AVAILABLE and System is not None:
            try:
                System.getProperties().put(AnomalyConfig.MANAGER_PROPERTY, self)
            except Exception:
                pass
        log_action(u"Started {0} v{1}.".format(AnomalyConfig.PLUGIN_NAME, AnomalyConfig.VERSION))

    def log_error_throttled(self, key, value, exc=None, seconds=60):
        now = now_ts()
        if now - safe_int(self.error_throttle.get(key), 0) < int(seconds):
            return
        self.error_throttle[key] = now
        log_error(value, exc)

    def initialize_coreprotect(self):
        self.last_coreprotect_retry_at = now_ts()
        self.coreprotect_api = None
        self.coreprotect_api_version = 0
        try:
            plugin = Bukkit.getPluginManager().getPlugin(
                AnomalyConfig.COREPROTECT_PLUGIN_NAME
            )
            if plugin is None or not plugin.isEnabled():
                self.coreprotect_status_text = u"плагин не найден или выключен"
                log_error(u"CoreProtect unavailable; anomaly block mutations are locked")
                return False
            api = plugin.getAPI()
            if api is None or not api.isEnabled():
                self.coreprotect_status_text = u"API выключен"
                log_error(u"CoreProtect API disabled; anomaly block mutations are locked")
                return False
            version = safe_int(api.APIVersion(), 0)
            if version < AnomalyConfig.COREPROTECT_MIN_API_VERSION:
                self.coreprotect_status_text = u"несовместимый API v{0}".format(version)
                log_error(u"CoreProtect API v{0} is below required v{1}; mutations are locked".format(
                    version, AnomalyConfig.COREPROTECT_MIN_API_VERSION
                ))
                return False
            self.coreprotect_api = api
            self.coreprotect_api_version = version
            self.coreprotect_status_text = u"готов, API v{0}".format(version)
            log_action(u"CoreProtect integration ready: API v{0}".format(version))
            return True
        except Exception as exc:
            self.coreprotect_status_text = u"ошибка подключения"
            log_error(u"CoreProtect initialization failed; mutations are locked", exc)
            return False

    def get_coreprotect_api(self):
        api = self.coreprotect_api
        try:
            if api is not None and api.isEnabled():
                return api
        except Exception:
            pass
        if now_ts() - self.last_coreprotect_retry_at >= 60:
            self.initialize_coreprotect()
        return self.coreprotect_api

    def coreprotect_ready_for_mutation(self, context):
        if not AnomalyConfig.COREPROTECT_REQUIRED_FOR_MUTATION:
            return True
        if self.get_coreprotect_api() is not None:
            return True
        now = now_ts()
        if now - self.last_coreprotect_unavailable_log_at >= 60:
            self.last_coreprotect_unavailable_log_at = now
            log_error(u"World mutation paused in {0}: CoreProtect is unavailable".format(context))
        return False

    def coreprotect_log_transition(self, block, before_data, after_data,
                                   actor, record, operation):
        """Queue both sides of a block transition before mutating the world."""
        api = self.get_coreprotect_api()
        if api is None:
            message = u"CoreProtect unavailable for {0} at {1}:{2},{3},{4}".format(
                operation, block.getWorld().getName(), block.getX(), block.getY(), block.getZ()
            )
            log_error(message)
            return not AnomalyConfig.COREPROTECT_REQUIRED_FOR_MUTATION
        try:
            before = Bukkit.createBlockData(to_java_string(before_data))
            after = Bukkit.createBlockData(to_java_string(after_data))
            location = block.getLocation()
            removed = bool(api.logRemoval(
                to_java_string(actor), location, before.getMaterial(), before
            ))
            placed = bool(api.logPlacement(
                to_java_string(actor), location, after.getMaterial(), after
            ))
            if not removed or not placed:
                log_error(u"CoreProtect rejected {0} for {1}:{2},{3},{4} "
                          u"(removal={5}, placement={6})".format(
                              operation, block.getWorld().getName(), block.getX(),
                              block.getY(), block.getZ(), removed, placed
                          ))
                self.coreprotect_api = None
                self.last_coreprotect_retry_at = now_ts()
                return False
            record["coreprotect_{0}_logged_at".format(operation)] = now_ts()
            record["coreprotect_{0}_actor".format(operation)] = actor
            return True
        except Exception as exc:
            log_error(u"CoreProtect logging failed for {0} at {1}:{2},{3},{4}".format(
                operation, block.getWorld().getName(), block.getX(), block.getY(), block.getZ()
            ), exc)
            self.coreprotect_api = None
            self.last_coreprotect_retry_at = now_ts()
            return False

    def coreprotect_status(self, sender):
        ready = self.initialize_coreprotect()
        send_message(sender, AnomalyConfig.PREFIX +
                     (u"&aCoreProtect: " if ready else u"&cCoreProtect: ") +
                     self.coreprotect_status_text)
        send_message(sender, u"&7Изменения мира без подтверждения CoreProtect: &f{0}".format(
            u"запрещены" if AnomalyConfig.COREPROTECT_REQUIRED_FOR_MUTATION else u"разрешены"
        ))
        send_message(sender, u"&7Создание: &f{0}&7; восстановление: &f{1}".format(
            AnomalyConfig.COREPROTECT_APPLY_ACTOR,
            AnomalyConfig.COREPROTECT_RESTORE_ACTOR
        ))

    def resume_active_anomalies(self):
        """Active zones and their smoke are reconstructed from the JSON journal."""
        resumed = len([a for a in self.active_anomalies() if a.get("status") == "ACTIVE"])
        stabilizing = len([a for a in self.active_anomalies() if a.get("status") == "STABILIZING"])
        removing = len([
            a for a in self.data.get("anomalies", {}).values()
            if isinstance(a, dict) and a.get("status") == "REMOVING"
        ])
        log_action(u"Recovered {0} active, {1} stabilizing and {2} quietly removing anomalies from data.".format(
            resumed, stabilizing, removing
        ))

    def stop(self):
        self.active = False
        self.flush_dirty(force=True)
        self.remove_all_bossbars()
        self.unregister_events()
        self.cancel_tasks()
        self.unregister_command()
        if JAVA_AVAILABLE and System is not None:
            try:
                props = System.getProperties()
                if props.get(AnomalyConfig.MANAGER_PROPERTY) is self:
                    props.remove(AnomalyConfig.MANAGER_PROPERTY)
            except Exception:
                pass
        log_action(u"Stopped {0}.".format(AnomalyConfig.PLUGIN_NAME))

    def shutdown_from_replacement(self):
        try:
            self.stop()
        except Exception:
            pass

    def flush_dirty(self, force=False):
        if not self.dirty:
            return True
        now = now_ts()
        if not force and now - self.last_dirty_flush < AnomalyConfig.DIRTY_FLUSH_SECONDS:
            return True
        if self.storage.save(self.data):
            self.dirty = False
            self.last_dirty_flush = now
            return True
        return False

    # command registration -------------------------------------------------

    def get_command_map(self):
        try:
            server = Bukkit.getServer()
            if hasattr(server, "getCommandMap"):
                return server.getCommandMap()
        except Exception:
            pass
        try:
            server = Bukkit.getServer()
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            return field.get(server)
        except Exception:
            return None

    def sync_commands(self):
        try:
            Bukkit.getServer().syncCommands()
        except Exception:
            pass

    def purge_command_object(self, command_obj, command_map=None):
        if command_obj is None:
            return
        if command_map is None:
            command_map = self.get_command_map()
        if command_map is None:
            return
        try:
            command_obj.unregister(command_map)
        except Exception:
            pass
        known = None
        try:
            if hasattr(command_map, "getKnownCommands"):
                known = command_map.getKnownCommands()
        except Exception:
            known = None
        if known is None:
            try:
                field = command_map.getClass().getDeclaredField("knownCommands")
                field.setAccessible(True)
                known = field.get(command_map)
            except Exception:
                known = None
        if known is not None:
            try:
                for key in list(known.keySet()):
                    try:
                        if known.get(key) is command_obj:
                            known.remove(key)
                    except Exception:
                        pass
            except Exception:
                pass

    def unregister_previous_command(self):
        if not JAVA_AVAILABLE or System is None:
            return
        try:
            old = System.getProperties().get(AnomalyConfig.COMMAND_PROPERTY)
            if old is not None:
                self.purge_command_object(old, self.get_command_map())
                System.getProperties().remove(AnomalyConfig.COMMAND_PROPERTY)
                self.sync_commands()
        except Exception:
            pass

    def register_command(self):
        self.command_map = self.get_command_map()
        if self.command_map is None:
            raise RuntimeError("Bukkit command map unavailable")
        self.command = AnomalyCommand(self)
        try:
            self.command_map.register("pyspigot", self.command)
        except Exception as exc:
            raise RuntimeError("Cannot register /anomaly: {0}".format(exc))
        if JAVA_AVAILABLE and System is not None:
            try:
                System.getProperties().put(AnomalyConfig.COMMAND_PROPERTY, self.command)
            except Exception:
                pass
        self.sync_commands()

    def unregister_command(self):
        if self.command is not None:
            self.purge_command_object(self.command, self.command_map)
        if JAVA_AVAILABLE and System is not None:
            try:
                props = System.getProperties()
                if props.get(AnomalyConfig.COMMAND_PROPERTY) is self.command:
                    props.remove(AnomalyConfig.COMMAND_PROPERTY)
            except Exception:
                pass
        self.command = None
        self.sync_commands()

    # event/task lifecycle -------------------------------------------------

    def register_event(self, event_class, callback, priority=None, ignore_cancelled=False):
        if event_class is None:
            return
        if priority is None:
            priority = EventPriority.NORMAL
        listener = EmptyListener()
        executor = CallbackExecutor(callback)
        Bukkit.getPluginManager().registerEvent(
            event_class, listener, priority, executor, self.plugin,
            bool(ignore_cancelled)
        )
        self.listeners.append(listener)

    def register_events(self):
        self.register_event(PlayerBedEnterEvent, self.on_bed_enter, EventPriority.HIGH, False)
        self.register_event(CreatureSpawnEvent, self.on_creature_spawn, EventPriority.HIGH, False)
        self.register_event(ChunkLoadEvent, self.on_chunk_load, EventPriority.HIGH, False)
        self.register_event(BlockPlaceEvent, self.on_player_block_change, EventPriority.HIGHEST, False)
        self.register_event(BlockBreakEvent, self.on_player_block_change, EventPriority.HIGHEST, False)
        self.register_event(PlayerCommandPreprocessEvent, self.on_command_preprocess, EventPriority.HIGHEST, False)
        self.register_event(PlayerCommandSendEvent, self.on_command_send, EventPriority.NORMAL, False)

    def unregister_events(self):
        for listener in self.listeners:
            try:
                HandlerList.unregisterAll(listener)
            except Exception:
                pass
        self.listeners = []

    def schedule(self, callback, delay_ticks, period_ticks):
        task = Bukkit.getScheduler().runTaskTimer(
            self.plugin, CallbackRunnable(callback),
            int(delay_ticks), int(period_ticks)
        )
        try:
            self.task_ids.append(int(task.getTaskId()))
        except Exception:
            pass

    def schedule_tasks(self):
        self.next_auto_spawn_at = now_ts() + int(AnomalyConfig.AUTO_CHECK_TICKS / 20)
        self.schedule(self.player_effect_cycle, 20, AnomalyConfig.PLAYER_EFFECT_TICKS)
        self.schedule(self.distortion_cycle, 40, AnomalyConfig.DISTORTION_TICKS)
        self.schedule(self.particle_cycle, 40, AnomalyConfig.PARTICLE_TICKS)
        self.schedule(self.stage_cycle, AnomalyConfig.STAGE_CHECK_TICKS, AnomalyConfig.STAGE_CHECK_TICKS)
        self.schedule(self.auto_spawn_cycle, AnomalyConfig.AUTO_CHECK_TICKS, AnomalyConfig.AUTO_CHECK_TICKS)
        self.schedule(self.cleanup_all_cycle, 20, 20)
        self.schedule(self.stabilization_cycle, AnomalyConfig.STABILIZE_TICKS, AnomalyConfig.STABILIZE_TICKS)
        self.schedule(self.flush_dirty, AnomalyConfig.DIRTY_FLUSH_TICKS, AnomalyConfig.DIRTY_FLUSH_TICKS)

    def cancel_tasks(self):
        for task_id in self.task_ids:
            try:
                Bukkit.getScheduler().cancelTask(int(task_id))
            except Exception:
                pass
        self.task_ids = []

    # permission/secrecy ---------------------------------------------------

    def is_admin(self, sender):
        if sender is None:
            return True
        try:
            if sender.isOp():
                return True
        except Exception:
            pass
        try:
            return bool(sender.hasPermission(AnomalyConfig.ADMIN_PERMISSION))
        except Exception:
            return False

    def send_unknown_command(self, sender):
        send_message(sender, u"&cUnknown command. Type \"/help\" for help.")

    def on_command_send(self, event):
        player = event.getPlayer()
        if self.is_admin(player):
            return
        try:
            commands = event.getCommands()
            for name in list(commands):
                low = str(name).lower()
                if low == "anomaly" or low.endswith(":anomaly"):
                    commands.remove(name)
        except Exception as exc:
            self.log_error_throttled("command-visibility", u"Command visibility handler failed", exc)

    def on_command_preprocess(self, event):
        try:
            player = event.getPlayer()
            if self.is_admin(player):
                return
            raw = to_unicode(event.getMessage()).strip()
            if not raw.startswith("/"):
                return
            parts = raw[1:].split()
            if not parts:
                return
            root = parts[0].lower()
            if root not in ("anomaly", "pyspigot:anomaly"):
                return
            event.setCancelled(True)
            if len(parts) == 2 and parts[1].lower() == "info":
                self.public_info(player)
            else:
                self.send_unknown_command(player)
        except Exception as exc:
            self.log_error_throttled("command-preprocess", u"Command preprocess handler failed", exc)

    def on_player_block_change(self, event):
        try:
            block = event.getBlock()
            location = block.getLocation()
            if self.anomaly_at_location(location) is not None:
                event.setCancelled(True)
        except Exception as exc:
            self.log_error_throttled("block-protection", u"Block protection event failed", exc)

    def notify_admins(self, message):
        log_action(message)
        try:
            for player in Bukkit.getOnlinePlayers():
                if self.is_admin(player):
                    send_message(player, AnomalyConfig.PREFIX + message)
        except Exception as exc:
            self.log_error_throttled("notify-admins", u"Cannot notify online admins", exc)

    def get_town_state(self):
        if not JAVA_AVAILABLE or System is None:
            return None
        try:
            state = System.getProperties().get(AnomalyConfig.TOWN_STATE_PROPERTY)
            if state is None:
                return None
            if hasattr(state, "is_active") and not state.is_active():
                return None
            return state
        except Exception:
            return None

    def get_city_records(self):
        state = self.get_town_state()
        if state is not None:
            try:
                return list(state.data.get("cities", {}).values())
            except Exception:
                pass
        try:
            if os.path.exists(AnomalyConfig.TOWNS_FILE):
                with open(AnomalyConfig.TOWNS_FILE, "r") as handle:
                    data = json.load(handle, parse_constant=reject_json_constant)
                if isinstance(data, dict) and isinstance(data.get("cities", {}), dict):
                    return list(data.get("cities", {}).values())
        except Exception:
            pass
        return []

    def city_home(self, city):
        home = city.get("home") if isinstance(city, dict) else None
        if not isinstance(home, dict):
            return None
        world_name = to_unicode(home.get("world")).strip()
        if not world_name:
            return None
        return {
            "world": world_name,
            "x": safe_float(home.get("x"), 0.0),
            "y": safe_float(home.get("y"), 0.0),
            "z": safe_float(home.get("z"), 0.0)
        }

    def find_city_by_name(self, name):
        target = to_unicode(name).strip().lower()
        for city in self.get_city_records():
            names = [
                to_unicode(city.get("name")).strip().lower(),
                to_unicode(city.get("id")).strip().lower()
            ]
            for alias in city.get("aliases", []) or []:
                names.append(to_unicode(alias).strip().lower())
            if target in names:
                return city
        return None

    def get_economy_manager(self):
        if not JAVA_AVAILABLE or System is None:
            return None
        try:
            props = System.getProperties()
            for key in AnomalyConfig.ECONOMY_PROPERTIES:
                economy = props.get(key)
                if economy is None:
                    continue
                try:
                    if hasattr(economy, "is_active") and not economy.is_active():
                        continue
                except Exception:
                    continue
                return economy
        except Exception:
            pass
        return None

    def non_closed_anomalies(self):
        result = []
        for anomaly in self.data.get("anomalies", {}).values():
            if isinstance(anomaly, dict) and anomaly.get("status") != "FIXED":
                result.append(anomaly)
        return result

    def active_anomalies(self):
        result = []
        for anomaly in self.data.get("anomalies", {}).values():
            if isinstance(anomaly, dict) and anomaly.get("status") in ("ACTIVE", "STABILIZING"):
                result.append(anomaly)
        return result

    def get_anomaly(self, anomaly_id):
        key = to_unicode(anomaly_id).strip().upper()
        return self.data.get("anomalies", {}).get(key)

    def anomaly_contains_location(self, anomaly, location):
        if anomaly is None or location is None:
            return False
        try:
            if to_unicode(location.getWorld().getName()) != to_unicode(anomaly.get("world")):
                return False
            radius = safe_float(anomaly.get("radius"), 0.0, 1.0)
            return dist_sq_2d(
                location.getX(), location.getZ(),
                anomaly.get("x"), anomaly.get("z")
            ) <= radius * radius
        except Exception:
            return False

    def anomaly_at_location(self, location):
        for anomaly in self.active_anomalies():
            if self.anomaly_contains_location(anomaly, location):
                return anomaly
        return None

    def nearest_anomaly(self, location, max_distance=100.0):
        if location is None:
            return None
        best = None
        best_d2 = float(max_distance) * float(max_distance)
        try:
            world_name = to_unicode(location.getWorld().getName())
            x = location.getX()
            z = location.getZ()
        except Exception:
            return None
        for anomaly in self.active_anomalies():
            if to_unicode(anomaly.get("world")) != world_name:
                continue
            d2 = dist_sq_2d(x, z, anomaly.get("x"), anomaly.get("z"))
            if d2 <= best_d2:
                best = anomaly
                best_d2 = d2
        return best

    def latest_active_anomaly(self):
        candidates = [
            anomaly for anomaly in self.data.get("anomalies", {}).values()
            if isinstance(anomaly, dict) and
            anomaly.get("status") in ("ACTIVE", "STABILIZING")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda anomaly: safe_int(anomaly.get("created_at"), 0))

    def on_bed_enter(self, event):
        try:
            player = event.getPlayer()
            if self.anomaly_at_location(player.getLocation()) is not None:
                event.setCancelled(True)
        except Exception as exc:
            self.log_error_throttled("bed-protection", u"Bed protection event failed", exc)

    def on_creature_spawn(self, event):
        try:
            if not hasattr(event, "getSpawnReason"):
                return
            try:
                entity = event.getEntity()
                if not isinstance(entity, LivingEntity):
                    return
            except Exception:
                return
            reason = str(event.getSpawnReason())
            if reason not in ("NATURAL", "CHUNK_GEN"):
                return
            if self.anomaly_at_location(event.getLocation()) is not None:
                event.setCancelled(True)
        except Exception as exc:
            self.log_error_throttled("creature-protection", u"Creature spawn protection failed", exc)

    def on_chunk_load(self, event):
        try:
            if not event.isNewChunk():
                return
            chunk = event.getChunk()
            for entity in chunk.getEntities():
                try:
                    if isinstance(entity, Player):
                        continue
                    if not isinstance(entity, LivingEntity):
                        continue
                    if self.anomaly_at_location(entity.getLocation()) is not None:
                        entity.remove()
                except Exception:
                    continue
        except Exception as exc:
            self.log_error_throttled("chunk-protection", u"Chunk protection handler failed", exc)

    def player_effect_cycle(self):
        if not self.active or PotionEffect is None or PotionEffectType is None:
            return
        now = now_ts()
        online = set()
        try:
            players = list(Bukkit.getOnlinePlayers())
        except Exception:
            players = []
        for player in players:
            try:
                uuid_key = str(player.getUniqueId())
                online.add(uuid_key)
                anomaly = self.anomaly_at_location(player.getLocation())
                if anomaly is None:
                    self.blindness_next.pop(uuid_key, None)
                    continue
                next_at = safe_int(self.blindness_next.get(uuid_key), 0)
                if next_at <= 0:
                    self.blindness_next[uuid_key] = now + random.randint(
                        AnomalyConfig.BLINDNESS_MIN_SECONDS,
                        AnomalyConfig.BLINDNESS_MAX_SECONDS
                    )
                    continue
                if now < next_at:
                    continue
                effect = PotionEffect(
                    PotionEffectType.BLINDNESS,
                    AnomalyConfig.BLINDNESS_DURATION_TICKS,
                    0, False, False, False
                )
                player.addPotionEffect(effect, True)
                self.blindness_next[uuid_key] = now + random.randint(
                    AnomalyConfig.BLINDNESS_MIN_SECONDS,
                    AnomalyConfig.BLINDNESS_MAX_SECONDS
                )
            except Exception as exc:
                self.log_error_throttled(
                    "player-effect-{0}".format(uuid_key if 'uuid_key' in locals() else "unknown"),
                    u"Player effect cycle failed", exc
                )
                continue
        for uuid_key in list(self.blindness_next.keys()):
            if uuid_key not in online:
                self.blindness_next.pop(uuid_key, None)

    def particle_cycle(self):
        if not self.active or Particle is None:
            return
        for anomaly in self.active_anomalies():
            if anomaly.get("status") != "ACTIVE":
                continue
            try:
                world = Bukkit.getWorld(to_java_string(anomaly.get("world")))
                if world is None:
                    continue
                radius = max(3, safe_int(anomaly.get("radius"), AnomalyConfig.STAGE1_RADIUS))
                phase = (now_ts() * AnomalyConfig.PARTICLE_RISE_BLOCKS_PER_SECOND)
                for index in range(AnomalyConfig.PARTICLE_BURSTS_PER_CYCLE):
                    distance = radius * math.sqrt(random.random()) * 0.95
                    angle = random.random() * math.pi * 2.0
                    x = int(round(float(anomaly.get("x")) + math.cos(angle) * distance))
                    z = int(round(float(anomaly.get("z")) + math.sin(angle) * distance))
                    if not self.chunk_loaded(world, x, z):
                        continue
                    ground_y = int(world.getHighestBlockYAt(x, z)) + 1
                    rise = (phase + index * 7) % (AnomalyConfig.PARTICLE_MAX_HEIGHT + 1)
                    world.spawnParticle(
                        Particle.CAMPFIRE_SIGNAL_SMOKE,
                        float(x) + 0.5, float(ground_y + rise), float(z) + 0.5,
                        1, 0.0, 0.0, 0.0, 0.0
                    )
            except Exception as exc:
                self.log_error_throttled(
                    "particles-{0}".format(anomaly.get("id")),
                    u"Particle cycle failed for {0}".format(anomaly.get("id")), exc
                )
                continue

    def world_is_normal(self, world):
        if world is None:
            return False
        try:
            return world.getEnvironment() == World.Environment.NORMAL
        except Exception:
            return False

    def chunk_loaded(self, world, x, z):
        try:
            return bool(world.isChunkLoaded(chunk_coord(x), chunk_coord(z)))
        except Exception:
            return False

    def all_chunks_loaded_for_radius(self, world, x, z, radius):
        min_cx = chunk_coord(float(x) - float(radius))
        max_cx = chunk_coord(float(x) + float(radius))
        min_cz = chunk_coord(float(z) - float(radius))
        max_cz = chunk_coord(float(z) + float(radius))
        for cx in range(min_cx, max_cx + 1):
            for cz in range(min_cz, max_cz + 1):
                try:
                    if not world.isChunkLoaded(cx, cz):
                        return False
                except Exception:
                    return False
        return True

    def has_container_near(self, world, x, z, radius):
        radius_sq = float(radius) * float(radius)
        min_cx = chunk_coord(float(x) - float(radius))
        max_cx = chunk_coord(float(x) + float(radius))
        min_cz = chunk_coord(float(z) - float(radius))
        max_cz = chunk_coord(float(z) + float(radius))
        for cx in range(min_cx, max_cx + 1):
            for cz in range(min_cz, max_cz + 1):
                try:
                    if not world.isChunkLoaded(cx, cz):
                        return True
                    chunk = world.getChunkAt(cx, cz)
                    for state in chunk.getTileEntities():
                        try:
                            loc = state.getLocation()
                            if dist_sq_2d(loc.getX(), loc.getZ(), x, z) > radius_sq:
                                continue
                            inventory = False
                            try:
                                inventory = isinstance(state, InventoryHolder)
                            except Exception:
                                pass
                            if not inventory and hasattr(state, "getInventory"):
                                inventory = True
                            if inventory:
                                return True
                        except Exception:
                            continue
                except Exception:
                    return True
        return False

    def surface_scene_material(self, world, x, z):
        try:
            if not self.chunk_loaded(world, x, z):
                return None
            y = int(world.getHighestBlockYAt(int(x), int(z)))
            return world.getBlockAt(int(x), y, int(z)).getType()
        except Exception:
            return None

    def landscape_is_natural(self, world, center_x, center_z):
        artificial = 0
        wet = 0
        samples = 0
        radius = AnomalyConfig.SAFETY_SAMPLE_RADIUS
        step = AnomalyConfig.SAFETY_SAMPLE_STEP
        radius_sq = radius * radius
        for dx in range(-radius, radius + 1, step):
            for dz in range(-radius, radius + 1, step):
                if dx * dx + dz * dz > radius_sq:
                    continue
                mat = self.surface_scene_material(world, center_x + dx, center_z + dz)
                if mat is None:
                    return False
                samples += 1
                if material_name(mat) in WET_SURFACE_NAMES:
                    wet += 1
                if not is_natural_scene_material(mat):
                    artificial += 1
        if wet > 0:
            return False
        allowed = max(
            AnomalyConfig.SAFETY_MAX_ARTIFICIAL_ABSOLUTE_MIN,
            int(math.ceil(samples * AnomalyConfig.SAFETY_MAX_ARTIFICIAL_RATIO))
        )
        return artificial <= allowed

    def min_distance_from_towns_ok(self, world_name, x, z):
        threshold = AnomalyConfig.TOWN_MIN_DISTANCE * AnomalyConfig.TOWN_MIN_DISTANCE
        for city in self.get_city_records():
            home = self.city_home(city)
            if home is None or to_unicode(home.get("world")) != to_unicode(world_name):
                continue
            if dist_sq_2d(x, z, home.get("x"), home.get("z")) < threshold:
                return False
        return True

    def min_distance_from_anomalies_ok(self, world_name, x, z):
        threshold = AnomalyConfig.ANOMALY_MIN_DISTANCE * AnomalyConfig.ANOMALY_MIN_DISTANCE
        for anomaly in self.active_anomalies():
            if to_unicode(anomaly.get("world")) != to_unicode(world_name):
                continue
            if dist_sq_2d(x, z, anomaly.get("x"), anomaly.get("z")) < threshold:
                return False
        return True

    def active_near_city_count(self, city):
        home = self.city_home(city)
        if home is None:
            return 0
        max_sq = AnomalyConfig.CITY_POINT_MAX * AnomalyConfig.CITY_POINT_MAX
        count = 0
        for anomaly in self.active_anomalies():
            if to_unicode(anomaly.get("world")) != to_unicode(home.get("world")):
                continue
            if dist_sq_2d(anomaly.get("x"), anomaly.get("z"), home.get("x"), home.get("z")) <= max_sq:
                count += 1
        return count

    def town_capacity_ok(self, world_name, x, z):
        return True

    def validate_center(self, world, x, z, allow_near_town=False):
        if world is None or not self.world_is_normal(world):
            return False, u"только обычный мир"
        if AnomalyConfig.MAX_ACTIVE > 0 and len(self.active_anomalies()) >= AnomalyConfig.MAX_ACTIVE:
            return False, u"достигнут глобальный лимит активных аномалий"
        if not self.all_chunks_loaded_for_radius(world, x, z, AnomalyConfig.SAFETY_CONTAINER_RADIUS):
            return False, u"не все проверяемые чанки загружены"
        world_name = to_unicode(world.getName())
        if not allow_near_town and not self.min_distance_from_towns_ok(world_name, x, z):
            return False, u"слишком близко к home города"
        if not self.min_distance_from_anomalies_ok(world_name, x, z):
            return False, u"слишком близко к другой аномалии"
        if not self.town_capacity_ok(world_name, x, z):
            return False, u"рядом с этим городом уже две активные аномалии"
        if self.has_container_near(world, x, z, AnomalyConfig.SAFETY_CONTAINER_RADIUS):
            return False, u"обнаружено хранилище ближе 40 блоков"
        if not self.landscape_is_natural(world, x, z):
            return False, u"слишком много искусственных блоков"
        return True, u"ok"

    def random_point(self, origin_x, origin_z, min_radius, max_radius):
        angle = random.random() * math.pi * 2.0
        min_sq = float(min_radius) * float(min_radius)
        max_sq = float(max_radius) * float(max_radius)
        radius = math.sqrt(random.uniform(min_sq, max_sq))
        return (
            int(round(float(origin_x) + math.cos(angle) * radius)),
            int(round(float(origin_z) + math.sin(angle) * radius))
        )

    def safe_point_around(self, world, origin_x, origin_z, min_radius, max_radius,
                          attempts, allow_near_town=False):
        last_reason = u"нет подходящей точки"
        for unused in range(int(attempts)):
            x, z = self.random_point(origin_x, origin_z, min_radius, max_radius)
            if not self.chunk_loaded(world, x, z):
                last_reason = u"кандидат находится в незагруженном чанке"
                continue
            ok, reason = self.validate_center(world, x, z, allow_near_town)
            if not ok:
                last_reason = reason
                continue
            try:
                y = int(world.getHighestBlockYAt(int(x), int(z))) + 1
            except Exception:
                y = 64
            return {"world": world, "x": x, "y": y, "z": z}, u"ok"
        return None, last_reason

    def allocate_id(self):
        next_id = max(1, safe_int(self.data.get("next_id"), 1))
        while True:
            anomaly_id = "A{0:04d}".format(next_id)
            next_id += 1
            if anomaly_id not in self.data.get("anomalies", {}):
                self.data["next_id"] = next_id
                return anomaly_id

    def create_anomaly(self, point, source_type, source_player=None, city=None):
        world = point.get("world")
        anomaly_id = self.allocate_id()
        now = now_ts()
        anomaly = {
            "id": anomaly_id, "status": "ACTIVE", "stage": 1,
            "radius": AnomalyConfig.STAGE1_RADIUS,
            "world": to_unicode(world.getName()),
            "x": int(point.get("x")), "y": int(point.get("y")), "z": int(point.get("z")),
            "created_at": now, "stage_started_at": now,
            "source_type": to_unicode(source_type),
            "source_player_uuid": None, "source_player_name": None,
            "city_id": None, "city_name": None,
            "reporter_uuid": None, "reporter_name": None,
            "blocks": [], "player_touched_columns": {},
            "stabilization_started_at": 0, "stabilization_total": 0, "fixed_at": 0,
            "reward": {
                "operation_id": "anomaly_reward_v1:{0}".format(anomaly_id),
                "state": "NOT_READY", "amount": AnomalyConfig.REWARD_AMOUNT,
                "prepared_at": 0, "before_balance": None, "expected_balance": None,
                "paid_at": 0, "last_error": None
            }
        }
        if source_player is not None:
            try:
                anomaly["source_player_uuid"] = str(source_player.getUniqueId())
                anomaly["source_player_name"] = to_unicode(source_player.getName())
            except Exception:
                pass
        if city is not None:
            anomaly["city_id"] = to_unicode(city.get("id"))
            anomaly["city_name"] = to_unicode(city.get("name"))
        self.data.setdefault("anomalies", {})[anomaly_id] = anomaly
        if not self.storage.save(self.data):
            self.data.get("anomalies", {}).pop(anomaly_id, None)
            log_error(u"Cannot create anomaly {0}: initial journal save failed".format(anomaly_id))
            return None
        self.log_anomaly_creation(anomaly)
        log_action(u"Created anomaly {0}: source={1} city={2} player={3} at {4}:{5},{6},{7}".format(
            anomaly.get("id"), anomaly.get("source_type"), anomaly.get("city_name") or "-",
            anomaly.get("source_player_name") or "-", anomaly.get("world"),
            anomaly.get("x"), anomaly.get("y"), anomaly.get("z")
        ))
        return anomaly

    def log_anomaly_creation(self, anomaly):
        line = (u"id={0} source={1} city={2} player={3} world={4} x={5} y={6} z={7}").format(
            anomaly.get("id"), anomaly.get("source_type"), anomaly.get("city_name") or "-",
            anomaly.get("source_player_name") or "-", anomaly.get("world"), anomaly.get("x"),
            anomaly.get("y"), anomaly.get("z")
        )
        if not append_utf8_log(AnomalyConfig.SPAWN_LOG_FILE, "CREATE", line):
            log_error(u"Cannot append anomaly spawn log for {0}".format(anomaly.get("id")))

    def player_far_from_all_towns(self, player):
        try:
            loc = player.getLocation()
            world_name = to_unicode(loc.getWorld().getName())
            threshold = AnomalyConfig.EXPLORER_MIN_FROM_TOWN * AnomalyConfig.EXPLORER_MIN_FROM_TOWN
            for city in self.get_city_records():
                home = self.city_home(city)
                if home is None or to_unicode(home.get("world")) != world_name:
                    continue
                if dist_sq_2d(loc.getX(), loc.getZ(), home.get("x"), home.get("z")) <= threshold:
                    return False
            return True
        except Exception:
            return False

    def recently_evented(self, player_uuid):
        last = safe_int(self.data.get("recent_players", {}).get(str(player_uuid)), 0)
        return last > 0 and now_ts() - last < AnomalyConfig.RECENT_PLAYER_COOLDOWN

    def city_event_eligible(self, city):
        home = self.city_home(city)
        if home is None:
            return False
        city_name = to_unicode(city.get("name")).strip().lower()
        if city_name in (u"атлантида", u"atlantis"):
            return False
        world = Bukkit.getWorld(to_java_string(home.get("world")))
        if world is None or not self.world_is_normal(world):
            return False
        return True

    def auto_note(self, message):
        line = u"{0}: {1}".format(time.strftime("%H:%M:%S"), to_unicode(message))
        self.auto_spawn_notes.append(line)
        self.auto_spawn_notes = self.auto_spawn_notes[-20:]
        log_action(u"Autospawn: " + line)

    def auto_status(self, sender):
        enabled = bool(self.data.get("auto_spawn"))
        seconds = max(0, safe_int(self.next_auto_spawn_at, 0) - now_ts())
        last = safe_int(self.last_auto_spawn_at, 0)
        send_message(sender, AnomalyConfig.PREFIX +
                     u"&fАвтоспавн: {0}&7; следующая проверка через &f{1} сек.&7; последняя: &f{2}"
                     .format(u"&aвключён" if enabled else u"&cвыключен", seconds,
                             time.strftime("%H:%M:%S", time.localtime(last)) if last else u"ещё не было"))
        for note in self.auto_spawn_notes[-8:]:
            send_message(sender, u"&8- &7" + note)

    def auto_spawn_cycle(self):
        self.last_auto_spawn_at = now_ts()
        self.next_auto_spawn_at = self.last_auto_spawn_at + int(AnomalyConfig.AUTO_CHECK_TICKS / 20)
        if not self.active:
            return
        if not self.data.get("auto_spawn"):
            self.auto_note(u"пропуск: автоспавн выключен")
            return
        rotation = self.data.setdefault("spawn_rotation", {})
        skipped_city = to_unicode(rotation.get("skip_city_id")).lower()
        rotation["skip_city_id"] = None
        cities = self.get_city_records()
        cities.sort(key=lambda city: to_unicode(city.get("id") or city.get("name")).lower())
        self.auto_note(u"старт проверки: городов={0}, пропускаемый город={1}".format(len(cities), skipped_city or u"-"))
        for city in cities:
            if not self.city_event_eligible(city):
                self.auto_note(u"город {0}: пропуск (исключён, не настроен или не в обычном мире)".format(city.get("name")))
                continue
            home = self.city_home(city)
            world = Bukkit.getWorld(to_java_string(home.get("world")))
            if world is None or not self.chunk_loaded(world, home.get("x"), home.get("z")):
                self.auto_note(u"город {0}: home-чанк не загружен".format(city.get("name")))
                continue
            key = to_unicode(city.get("id") or city.get("name")).lower()
            if key == skipped_city:
                self.auto_note(u"город {0}: пропущен по ротации".format(city.get("name")))
                continue
            point, reason = self.safe_point_around(world, home.get("x"), home.get("z"),
                                                   AnomalyConfig.CITY_POINT_MIN, AnomalyConfig.CITY_POINT_MAX, 60,
                                                   allow_near_town=True)
            if point is None:
                self.auto_note(u"город {0}: безопасная точка не найдена ({1})".format(city.get("name"), reason))
                continue
            anomaly = self.create_anomaly(point, "CITY", city=city)
            if anomaly is not None:
                rotation["skip_city_id"] = key
                self.storage.save(self.data)
                self.auto_note(u"создана {0} у города {1}".format(anomaly.get("id"), city.get("name")))
                return
        try:
            players = list(Bukkit.getOnlinePlayers())
        except Exception:
            players = []
        players.sort(key=lambda player: str(player.getUniqueId()))
        skipped_player = to_unicode(rotation.get("skip_player_uuid"))
        rotation["skip_player_uuid"] = None
        self.auto_note(u"переход к игрокам: онлайн={0}, пропускаемый UUID={1}".format(len(players), skipped_player or u"-"))
        for player in players:
            try:
                uuid_key = str(player.getUniqueId())
                if uuid_key == skipped_player:
                    continue
                world = player.getWorld()
                if not self.world_is_normal(world) or not self.player_far_from_all_towns(player):
                    continue
                loc = player.getLocation()
                point, reason = self.safe_point_around(world, loc.getX(), loc.getZ(),
                                                       AnomalyConfig.EXPLORER_POINT_MIN,
                                                       AnomalyConfig.EXPLORER_POINT_MAX, 18)
                if point is None:
                    continue
                anomaly = self.create_anomaly(point, "EXPLORER", source_player=player)
                if anomaly is not None:
                    rotation["skip_player_uuid"] = uuid_key
                    self.storage.save(self.data)
                    self.auto_note(u"создана {0} у игрока {1}".format(anomaly.get("id"), player.getName()))
                    return
            except Exception:
                continue
        self.storage.save(self.data)
        self.auto_note(u"проверка завершена: подходящей точки не найдено")

    def create_for_city(self, city):
        if not self.city_event_eligible(city):
            count = self.active_near_city_count(city)
            if count >= 2:
                return None, u"у города уже две активные аномалии"
            return None, u"город находится на 7-дневном кулдауне события"
        home = self.city_home(city)
        if home is None:
            return None, u"у города не настроен home"
        world = Bukkit.getWorld(to_java_string(home.get("world")))
        if world is None or not self.world_is_normal(world):
            return None, u"home города не в обычном мире"
        point, reason = self.safe_point_around(world, home.get("x"), home.get("z"),
                                               AnomalyConfig.CITY_POINT_MIN,
                                               AnomalyConfig.CITY_POINT_MAX, 40)
        if point is None:
            return None, reason
        anomaly = self.create_anomaly(point, "ADMIN_CITY", city=city)
        if anomaly is None:
            return None, u"не удалось сохранить новую аномалию"
        key = to_unicode(city.get("id") or city.get("name")).lower()
        self.data.setdefault("city_last_event", {})[key] = now_ts()
        self.storage.save(self.data)
        return anomaly, u"ok"

    def create_here(self, player):
        loc = player.getLocation()
        world = loc.getWorld()
        x = int(round(loc.getX()))
        z = int(round(loc.getZ()))
        ok, reason = self.validate_center(world, x, z)
        if not ok:
            return None, reason
        point = {"world": world, "x": x, "y": int(world.getHighestBlockYAt(x, z)) + 1, "z": z}
        anomaly = self.create_anomaly(point, "ADMIN_HERE")
        if anomaly is None:
            return None, u"не удалось сохранить новую аномалию"
        return anomaly, u"ok"

    def block_key(self, world_name, x, y, z):
        return "{0}:{1}:{2}:{3}".format(to_unicode(world_name), int(x), int(y), int(z))

    def existing_block_keys(self, anomaly):
        result = set()
        for record in anomaly.get("blocks", []):
            if isinstance(record, dict):
                result.add(self.block_key(record.get("world"), record.get("x"), record.get("y"), record.get("z")))
        return result

    def serialize_block(self, block):
        try:
            return to_unicode(block.getBlockData().getAsString())
        except Exception:
            try:
                return to_unicode(block.getType().getKey().toString())
            except Exception:
                return u"minecraft:{0}".format(material_name(block.getType()).lower())

    def create_block_data_string(self, material):
        try:
            return to_unicode(Bukkit.createBlockData(material).getAsString())
        except Exception:
            return u"minecraft:{0}".format(material_name(material).lower())

    def make_vein_data_string(self):
        try:
            data = Bukkit.createBlockData(Material.SCULK_VEIN)
            if hasattr(data, "setFace") and BlockFace is not None:
                data.setFace(BlockFace.DOWN, True)
            return to_unicode(data.getAsString())
        except Exception:
            return u"minecraft:sculk_vein"

    def find_natural_ground(self, world, x, z):
        if not self.chunk_loaded(world, x, z):
            return None
        try:
            highest = int(world.getHighestBlockYAt(int(x), int(z)))
            minimum = max(int(world.getMinHeight()) + 1, highest - 16)
        except Exception:
            return None
        for y in range(highest, minimum - 1, -1):
            block = world.getBlockAt(int(x), int(y), int(z))
            mat = block.getType()
            if material_name(mat) in WET_SURFACE_NAMES:
                return None
            if is_replaceable_ground(mat):
                return block
            if not is_natural_scene_material(mat):
                return None
        return None

    def pick_distortion_material(self):
        name = random.choice(DISTORTION_MATERIAL_NAMES)
        try:
            return getattr(Material, name)
        except Exception:
            try:
                return Material.matchMaterial(name)
            except Exception:
                return None

    def planned_surface_record(self, anomaly, existing_keys):
        world = Bukkit.getWorld(to_java_string(anomaly.get("world")))
        if world is None:
            return None, None
        stage = safe_int(anomaly.get("stage"), 1)
        applied_surface = self.surface_count(anomaly)
        if stage <= 1:
            min_radius, max_radius = 0.0, float(AnomalyConfig.STAGE1_RADIUS)
        elif applied_surface < AnomalyConfig.STAGE1_SURFACE_TARGET:
            min_radius, max_radius = 0.0, float(AnomalyConfig.STAGE1_RADIUS)
        else:
            min_radius, max_radius = float(AnomalyConfig.STAGE1_RADIUS) + 0.5, float(AnomalyConfig.STAGE2_RADIUS)
        for unused in range(160):
            x, z = self.random_point(anomaly.get("x"), anomaly.get("z"), min_radius, max_radius)
            if not self.chunk_loaded(world, x, z):
                continue
            touched_key = "{0}:{1}".format(int(x), int(z))
            if touched_key in anomaly.get("player_touched_columns", {}):
                continue
            ground = self.find_natural_ground(world, x, z)
            if ground is None:
                continue
            key = self.block_key(anomaly.get("world"), ground.getX(), ground.getY(), ground.getZ())
            if key in existing_keys:
                continue
            new_material = self.pick_distortion_material()
            if new_material is None:
                continue
            original = self.serialize_block(ground)
            anomaly_data = self.create_block_data_string(new_material)
            if original == anomaly_data:
                continue
            record = {
                "world": to_unicode(anomaly.get("world")), "x": int(ground.getX()),
                "y": int(ground.getY()), "z": int(ground.getZ()), "kind": "surface",
                "stage": stage, "original_data": original, "anomaly_data": anomaly_data,
                "state": "PLANNED", "planned_at": now_ts()
            }
            vein = None
            if random.random() < AnomalyConfig.VEIN_CHANCE:
                above = world.getBlockAt(int(ground.getX()), int(ground.getY()) + 1, int(ground.getZ()))
                above_key = self.block_key(anomaly.get("world"), above.getX(), above.getY(), above.getZ())
                if above_key not in existing_keys and material_name(above.getType()) in ("AIR", "CAVE_AIR"):
                    vein = {
                        "world": to_unicode(anomaly.get("world")), "x": int(above.getX()),
                        "y": int(above.getY()), "z": int(above.getZ()), "kind": "vein",
                        "stage": stage, "original_data": self.serialize_block(above),
                        "anomaly_data": self.make_vein_data_string(), "state": "PLANNED",
                        "planned_at": now_ts()
                    }
            return record, vein
        return None, None

    def apply_planned_record(self, record):
        world = Bukkit.getWorld(to_java_string(record.get("world")))
        if world is None:
            return False
        x, y, z = int(record.get("x")), int(record.get("y")), int(record.get("z"))
        if not self.chunk_loaded(world, x, z):
            return False
        block = world.getBlockAt(x, y, z)
        current = self.serialize_block(block)
        original = to_unicode(record.get("original_data"))
        anomaly_data = to_unicode(record.get("anomaly_data"))
        if current == anomaly_data:
            record["state"] = "APPLIED"
            return True
        if current != original:
            record["state"] = "SKIPPED_PLAYER"
            return False
        try:
            data = Bukkit.createBlockData(to_java_string(anomaly_data))
            if not self.coreprotect_log_transition(block, original, anomaly_data,
                                                   AnomalyConfig.COREPROTECT_APPLY_ACTOR, record, "apply"):
                record["state"] = "COREPROTECT_FAILED"
                return False
            block.setBlockData(data, False)
            record["state"] = "APPLIED"
            record["applied_at"] = now_ts()
            return True
        except Exception as exc:
            record["state"] = "APPLY_FAILED"
            record["last_error"] = to_unicode(exc)
            log_error(u"Cannot apply anomaly block at {0}:{1},{2},{3}".format(record.get("world"), x, y, z), exc)
            return False

    def surface_count(self, anomaly):
        return len([r for r in anomaly.get("blocks", []) if isinstance(r, dict) and r.get("kind") == "surface" and r.get("state") in ("APPLIED", "PLANNED")])

    def distortion_cycle(self):
        if not self.active or not self.coreprotect_ready_for_mutation("distortion_cycle"):
            return
        changed_any = False
        for anomaly in list(self.active_anomalies()):
            if anomaly.get("status") != "ACTIVE":
                continue
            target = AnomalyConfig.STAGE1_SURFACE_TARGET if safe_int(anomaly.get("stage"), 1) <= 1 else AnomalyConfig.STAGE2_SURFACE_TARGET_TOTAL
            current = self.surface_count(anomaly)
            if current >= target:
                continue
            remaining = min(AnomalyConfig.DISTORTION_MAX_PER_CYCLE, target - current)
            existing_keys = self.existing_block_keys(anomaly)
            planned = []
            for unused in range(remaining):
                surface, vein = self.planned_surface_record(anomaly, existing_keys)
                if surface is None:
                    break
                planned.append(surface)
                existing_keys.add(self.block_key(surface.get("world"), surface.get("x"), surface.get("y"), surface.get("z")))
                if vein is not None:
                    planned.append(vein)
                    existing_keys.add(self.block_key(vein.get("world"), vein.get("x"), vein.get("y"), vein.get("z")))
            if not planned:
                continue
            anomaly.setdefault("blocks", []).extend(planned)
            if not self.storage.save(self.data):
                del anomaly["blocks"][-len(planned):]
                continue
            for record in planned:
                self.apply_planned_record(record)
            self.dirty = True
            changed_any = True
        if changed_any:
            self.flush_dirty(force=False)

    def reconcile_planned_records(self):
        changed = False
        for anomaly in self.data.get("anomalies", {}).values():
            if not isinstance(anomaly, dict):
                continue
            for record in anomaly.get("blocks", []):
                if not isinstance(record, dict) or record.get("state") not in ("PLANNED", "APPLY_FAILED"):
                    continue
                world = Bukkit.getWorld(to_java_string(record.get("world")))
                if world is None:
                    continue
                x, y, z = int(record.get("x")), int(record.get("y")), int(record.get("z"))
                if not self.chunk_loaded(world, x, z):
                    continue
                current = self.serialize_block(world.getBlockAt(x, y, z))
                if current == to_unicode(record.get("anomaly_data")):
                    record["state"] = "APPLIED"
                    changed = True
                elif current == to_unicode(record.get("original_data")):
                    if anomaly.get("status") == "ACTIVE":
                        self.apply_planned_record(record)
                    else:
                        record["state"] = "RESTORED"
                    changed = True
                else:
                    record["state"] = "SKIPPED_PLAYER"
                    changed = True
        if changed:
            self.storage.save(self.data)

    def stage_name(self, stage):
        return u"Подозрение" if safe_int(stage, 1) <= 1 else u"Усиление"

    def stage_cycle(self):
        if not self.active:
            return
        now = now_ts()
        changed = False
        for anomaly in self.active_anomalies():
            if anomaly.get("status") != "ACTIVE" or safe_int(anomaly.get("stage"), 1) != 1:
                continue
            started = safe_int(anomaly.get("stage_started_at"), anomaly.get("created_at", now))
            if now - started < AnomalyConfig.STAGE_SECONDS:
                continue
            anomaly["stage"] = 2
            anomaly["radius"] = AnomalyConfig.STAGE2_RADIUS
            anomaly["stage_started_at"] = now
            changed = True
            self.notify_admins(u"&dАномалия &f{0}&d перешла на стадию 2 «Усиление».".format(anomaly.get("id")))
        if changed:
            self.storage.save(self.data)

    def manual_next_stage(self, anomaly):
        if anomaly.get("status") != "ACTIVE":
            return False, u"аномалия не активна"
        if safe_int(anomaly.get("stage"), 1) >= 2:
            return False, u"стадии 3 и 4 пока не реализованы"
        anomaly["stage"] = 2
        anomaly["radius"] = AnomalyConfig.STAGE2_RADIUS
        anomaly["stage_started_at"] = now_ts()
        if not self.storage.save(self.data):
            return False, u"не удалось сохранить переход стадии"
        return True, u"стадия 2 включена"

    def create_bossbar(self, anomaly):
        anomaly_id = anomaly.get("id")
        old = self.bossbars.get(anomaly_id)
        if old is not None:
            return old
        try:
            bar = Bukkit.createBossBar(to_java_string(u"Стабилизация {0}".format(anomaly_id)), BarColor.PURPLE, BarStyle.SOLID)
            bar.setProgress(0.0)
            self.bossbars[anomaly_id] = bar
            return bar
        except Exception:
            return None

    def remove_bossbar(self, anomaly_id):
        bar = self.bossbars.pop(anomaly_id, None)
        if bar is not None:
            try:
                bar.removeAll()
            except Exception:
                pass

    def remove_all_bossbars(self):
        for anomaly_id in list(self.bossbars.keys()):
            self.remove_bossbar(anomaly_id)

    def bossbar_add_admins(self, bar):
        if bar is None:
            return
        try:
            current = set([str(p.getUniqueId()) for p in bar.getPlayers()])
            for player in Bukkit.getOnlinePlayers():
                if self.is_admin(player):
                    if str(player.getUniqueId()) not in current:
                        bar.addPlayer(player)
                else:
                    try:
                        bar.removePlayer(player)
                    except Exception:
                        pass
        except Exception:
            pass

    def resume_bossbars(self):
        for anomaly in self.active_anomalies():
            if anomaly.get("status") == "STABILIZING":
                self.bossbar_add_admins(self.create_bossbar(anomaly))

    def start_stabilization(self, anomaly):
        if anomaly.get("status") != "ACTIVE":
            return False, u"аномалия не активна"
        anomaly["status"] = "STABILIZING"
        anomaly["stabilization_started_at"] = now_ts()
        anomaly["stabilization_total"] = len(anomaly.get("blocks", []))
        if not self.storage.save(self.data):
            anomaly["status"] = "ACTIVE"
            return False, u"не удалось сохранить начало стабилизации"
        self.bossbar_add_admins(self.create_bossbar(anomaly))
        if not anomaly.get("blocks"):
            self.finish_stabilization(anomaly)
        return True, u"стабилизация запущена"

    def start_quiet_removal(self, anomaly):
        if anomaly is None or anomaly.get("status") not in ("ACTIVE", "STABILIZING"):
            return False, u"аномалия не находится в удаляемом состоянии"
        anomaly["status"] = "REMOVING"
        anomaly["admin_cleanup"] = True
        anomaly["quiet_removal"] = True
        anomaly["stabilization_started_at"] = now_ts()
        anomaly["stabilization_total"] = len(anomaly.get("blocks", []))
        if not self.storage.save(self.data):
            return False, u"не удалось сохранить тихое удаление"
        self.remove_bossbar(anomaly.get("id"))
        if not anomaly.get("blocks"):
            self.finish_stabilization(anomaly)
        return True, u"аномалия скрыта; блоки восстанавливаются в загруженных чанках"

    def record_resolved(self, record):
        return record.get("state") in ("RESTORED", "SKIPPED_PLAYER")

    def unresolved_records(self, anomaly):
        return [r for r in anomaly.get("blocks", []) if isinstance(r, dict) and not self.record_resolved(r)]

    def restore_record(self, record):
        world = Bukkit.getWorld(to_java_string(record.get("world")))
        if world is None:
            return False
        x, y, z = int(record.get("x")), int(record.get("y")), int(record.get("z"))
        if not self.chunk_loaded(world, x, z):
            return False
        block = world.getBlockAt(x, y, z)
        current = self.serialize_block(block)
        original = to_unicode(record.get("original_data"))
        anomaly_data = to_unicode(record.get("anomaly_data"))
        if current == original:
            record["state"] = "RESTORED"
            return True
        if current != anomaly_data:
            record["state"] = "SKIPPED_PLAYER"
            return True
        try:
            data = Bukkit.createBlockData(to_java_string(original))
            if not self.coreprotect_log_transition(block, anomaly_data, original,
                                                   AnomalyConfig.COREPROTECT_RESTORE_ACTOR, record, "restore"):
                return False
            block.setBlockData(data, False)
            record["state"] = "RESTORED"
            record["restored_at"] = now_ts()
            return True
        except Exception:
            return False

    def stabilization_cycle(self):
        if not self.active or not self.coreprotect_ready_for_mutation("stabilization_cycle"):
            return
        changed = False
        for anomaly in list(self.data.get("anomalies", {}).values()):
            if not isinstance(anomaly, dict) or anomaly.get("status") not in ("STABILIZING", "REMOVING"):
                continue
            unresolved = self.unresolved_records(anomaly)
            total = max(1, safe_int(anomaly.get("stabilization_total"), len(anomaly.get("blocks", []))))
            if not unresolved:
                self.finish_stabilization(anomaly)
                continue
            cycles = max(1, int((AnomalyConfig.STABILIZE_SECONDS * 20) / AnomalyConfig.STABILIZE_TICKS))
            budget = max(1, int(math.ceil(float(total) / float(cycles))))
            for record in unresolved[:budget]:
                if self.restore_record(record):
                    changed = True
            resolved_count = len([r for r in anomaly.get("blocks", []) if isinstance(r, dict) and self.record_resolved(r)])
            progress = min(1.0, max(0.0, float(resolved_count) / float(total)))
            if anomaly.get("status") == "STABILIZING":
                bar = self.create_bossbar(anomaly)
                if bar is not None:
                    try:
                        bar.setProgress(progress)
                        bar.setTitle(to_java_string(u"Стабилизация {0}: {1}%".format(anomaly.get("id"), int(progress * 100))))
                    except Exception:
                        pass
                    self.bossbar_add_admins(bar)
            if not self.unresolved_records(anomaly):
                self.finish_stabilization(anomaly)
        if changed:
            self.dirty = True
            self.flush_dirty(force=False)

    def finish_stabilization(self, anomaly):
        if self.unresolved_records(anomaly):
            return False
        anomaly["status"] = "FIXED"
        anomaly["fixed_at"] = now_ts()
        if anomaly.get("admin_cleanup"):
            anomaly.setdefault("reward", {})["state"] = "CANCELLED_ADMIN"
        if not self.storage.save(self.data):
            return False
        self.remove_bossbar(anomaly.get("id"))
        if not anomaly.get("admin_cleanup"):
            self.issue_reward(anomaly)
        return True

    def reward_close_enough(self, left, right):
        try:
            return left is not None and right is not None and abs(float(left) - float(right)) < 0.005
        except Exception:
            return False

    def issue_reward(self, anomaly):
        reward = anomaly.setdefault("reward", {})
        reward.setdefault("operation_id", "anomaly_reward_v1:{0}".format(anomaly.get("id")))
        reward.setdefault("amount", AnomalyConfig.REWARD_AMOUNT)
        if reward.get("state") == "PAID":
            return True, u"уже выплачена"
        reporter_uuid = anomaly.get("reporter_uuid")
        if not reporter_uuid:
            reward["state"] = "NO_REPORTER"
            self.storage.save(self.data)
            return False, u"репортёр не назначен"
        economy = self.get_economy_manager()
        if economy is None:
            reward["state"] = "FAILED"
            self.storage.save(self.data)
            return False, u"экономика недоступна"
        try:
            current = float(economy.get_balance(str(reporter_uuid)))
            amount = safe_float(reward.get("amount"), AnomalyConfig.REWARD_AMOUNT, 0.01)
            before = current
            expected = round(before + amount, 2)
            reward["state"] = "PREPARED"
            reward["before_balance"] = before
            reward["expected_balance"] = expected
            self.storage.save(self.data)
            success, new_balance = economy.deposit_checked(str(reporter_uuid), amount, None)
            if not success or not self.reward_close_enough(new_balance, expected):
                reward["state"] = "REVIEW_REQUIRED"
                self.storage.save(self.data)
                return False, u"начисление требует ручной проверки"
            reward["state"] = "PAID"
            reward["paid_at"] = now_ts()
            self.storage.save(self.data)
            return True, u"5000$ выплачено"
        except Exception as exc:
            reward["state"] = "PREPARED"
            reward["last_error"] = to_unicode(exc)
            self.storage.save(self.data)
            return False, u"выплата оставлена на безопасном восстановлении"

    def recover_prepared_rewards(self):
        for anomaly in self.data.get("anomalies", {}).values():
            if isinstance(anomaly, dict) and anomaly.get("status") == "FIXED":
                reward = anomaly.get("reward", {})
                if isinstance(reward, dict) and reward.get("state") == "PREPARED":
                    self.issue_reward(anomaly)

    def format_age(self, seconds):
        seconds = max(0, safe_int(seconds, 0))
        hours = seconds // 3600
        days = hours // 24
        hours %= 24
        minutes = (seconds % 3600) // 60
        return u"{0}д {1}ч".format(days, hours) if days else u"{0}ч {1}м".format(hours, minutes)

    def inspect(self, sender, anomaly):
        send_message(sender, AnomalyConfig.PREFIX + u"&f{0} &7— {1}, стадия {2} «{3}»".format(
            anomaly.get("id"), anomaly.get("status"), anomaly.get("stage"), self.stage_name(anomaly.get("stage"))))
        send_message(sender, u"&7Мир/центр: &f{0} [{1}, {2}] &7R=&f{3}".format(
            anomaly.get("world"), anomaly.get("x"), anomaly.get("z"), anomaly.get("radius")))

    def admin_list(self, sender):
        anomalies = sorted(self.data.get("anomalies", {}).values(), key=lambda a: to_unicode(a.get("id")))
        send_message(sender, AnomalyConfig.PREFIX + u"&fВсе зоны: &7{0}".format(len(anomalies)))
        for anomaly in anomalies:
            send_message(sender, u"&8- &f{0} &7{1} S{2} R{3} — {4} [{5}, {6}]".format(
                anomaly.get("id"), anomaly.get("status"), anomaly.get("stage"), anomaly.get("radius"),
                anomaly.get("world"), anomaly.get("x"), anomaly.get("z")))

    def debug_all(self, sender):
        self.admin_list(sender)

    def public_info(self, sender):
        if not isinstance(sender, Player):
            self.send_unknown_command(sender)
            return True
        anomaly = self.anomaly_at_location(sender.getLocation())
        if anomaly is None:
            self.send_unknown_command(sender)
            return True
        send_message(sender, u"&8Искажение мира: &7стадия &f{0} — «{1}»&7, примерный радиус &f~{2} блоков&7.".format(
            anomaly.get("stage"), self.stage_name(anomaly.get("stage")), anomaly.get("radius")))
        return True

    def resolve_reporter(self, player_name):
        try:
            online = Bukkit.getPlayer(to_java_string(player_name))
            if online is not None:
                return str(online.getUniqueId()), to_unicode(online.getName())
        except Exception:
            pass
        return None, None

    def set_reporter(self, anomaly, player_name):
        uuid_str, resolved_name = self.resolve_reporter(player_name)
        if not uuid_str:
            return False, u"игрок не найден"
        anomaly["reporter_uuid"] = uuid_str
        anomaly["reporter_name"] = resolved_name
        if not self.storage.save(self.data):
            return False, u"не удалось сохранить репортёра"
        return True, u"репортёр назначен: {0}".format(resolved_name)

    def remove_anomaly(self, anomaly):
        if anomaly.get("status") != "FIXED":
            return False
        anomaly_id = anomaly.get("id")
        self.data.get("anomalies", {}).pop(anomaly_id, None)
        return self.storage.save(self.data)

    def online_player_by_uuid(self, uuid_key):
        try:
            for player in Bukkit.getOnlinePlayers():
                if str(player.getUniqueId()) == str(uuid_key):
                    return player
        except Exception:
            pass
        return None

    def teleport_to_anomaly_for_cleanup(self, player, anomaly):
        try:
            world = Bukkit.getWorld(to_java_string(anomaly.get("world")))
            target = Location(world, float(anomaly.get("x")) + 0.5, float(anomaly.get("y")) + 2.0, float(anomaly.get("z")) + 0.5)
            return bool(player.teleport(target))
        except Exception:
            return False

    def start_cleanup_all(self, player):
        if self.cleanup_session is not None:
            return False, u"очистка уже выполняется"
        queue = sorted([a.get("id") for a in self.non_closed_anomalies() if a.get("status") in ("ACTIVE", "STABILIZING")])
        if not queue:
            return False, u"активных аномалий нет"
        self.cleanup_session = {"player_uuid": str(player.getUniqueId()), "queue": queue, "current": None}
        return True, u"запущена очистка {0} аномалий".format(len(queue))

    def cleanup_all_cycle(self):
        session = self.cleanup_session
        if session is None:
            return
        player = self.online_player_by_uuid(session.get("player_uuid"))
        if player is None:
            self.cleanup_session = None
            return
        current_id = session.get("current")
        if current_id:
            anomaly = self.get_anomaly(current_id)
            if anomaly is None or anomaly.get("status") == "FIXED":
                session["current"] = None
                return
            self.teleport_to_anomaly_for_cleanup(player, anomaly)
            if anomaly.get("status") == "ACTIVE":
                anomaly["admin_cleanup"] = True
                self.start_stabilization(anomaly)
            return
        if session.get("queue"):
            anomaly = self.get_anomaly(session["queue"].pop(0))
            if anomaly is None:
                return
            session["current"] = anomaly.get("id")
            anomaly["admin_cleanup"] = True
            self.teleport_to_anomaly_for_cleanup(player, anomaly)
            self.start_stabilization(anomaly)
            return
        self.cleanup_session = None
        send_message(player, AnomalyConfig.PREFIX + u"&aВсе аномалии восстановлены и закрыты.")

    def admin_help(self, sender):
        for line in [u"&f/anomaly start|stop|list", u"&f/anomaly inspect <id>", u"&f/anomaly create <город> | createhere",
                     u"&f/anomaly stage <id> next", u"&f/anomaly reporter <id> <игрок>",
                     u"&f/anomaly stabilize <id|nearest>", u"&f/anomaly dismiss <latest|nearest|id>",
                     u"&f/anomaly cleanupall confirm", u"&f/anomaly save|reload", u"&f/anomaly debug [id]"]:
            send_message(sender, line)

    def handle_command(self, sender, args):
        args = [to_unicode(arg) for arg in args]
        sub = args[0].lower() if args else ""
        if not self.is_admin(sender):
            if sub == "info":
                return self.public_info(sender)
            self.send_unknown_command(sender)
            return True
        if not sub:
            self.admin_help(sender); return True
        if sub == "start":
            self.data["auto_spawn"] = True; self.storage.save(self.data); send_message(sender, AnomalyConfig.PREFIX + u"&aАвтоспавн включён."); return True
        if sub == "stop":
            self.data["auto_spawn"] = False; self.storage.save(self.data); send_message(sender, AnomalyConfig.PREFIX + u"&eАвтоспавн выключен."); return True
        if sub == "list": self.admin_list(sender); return True
        if sub == "autostatus": self.auto_status(sender); return True
        if sub == "coreprotect": self.coreprotect_status(sender); return True
        if sub in ("inspect", "debug"):
            if len(args) >= 2:
                anomaly = self.get_anomaly(args[1])
                if anomaly: self.inspect(sender, anomaly)
            else: self.debug_all(sender)
            return True
        if sub == "createhere" and isinstance(sender, Player):
            anomaly, reason = self.create_here(sender); send_message(sender, AnomalyConfig.PREFIX + (u"&aСоздано." if anomaly else u"&c" + reason)); return True
        if sub == "stage" and len(args) >= 3:
            anomaly = self.get_anomaly(args[1]); ok, msg = self.manual_next_stage(anomaly) if anomaly else (False, u"не найдено"); send_message(sender, msg); return True
        if sub == "reporter" and len(args) >= 3:
            anomaly = self.get_anomaly(args[1]); ok, msg = self.set_reporter(anomaly, args[2]) if anomaly else (False, u"не найдено"); send_message(sender, msg); return True
        if sub == "stabilize" and len(args) >= 2:
            anomaly = self.nearest_anomaly(sender.getLocation(), 100.0) if args[1].lower() == "nearest" and isinstance(sender, Player) else self.get_anomaly(args[1])
            ok, msg = self.start_stabilization(anomaly) if anomaly else (False, u"не найдено"); send_message(sender, msg); return True
        if sub == "dismiss" and len(args) >= 2:
            anomaly = self.latest_active_anomaly() if args[1].lower() == "latest" else self.get_anomaly(args[1]); ok, msg = self.start_quiet_removal(anomaly); send_message(sender, msg); return True
        if sub == "cleanupall" and len(args) >= 2 and args[1].lower() == "confirm" and isinstance(sender, Player):
            ok, msg = self.start_cleanup_all(sender); send_message(sender, msg); return True
        if sub == "save": self.storage.save(self.data); send_message(sender, u"&aСохранено."); return True
        if sub == "reload": self.data = self.storage.load(); self.normalize_runtime_data(); send_message(sender, u"&aПеречитано."); return True
        self.admin_help(sender); return True

    def tab_complete(self, sender, args):
        if not self.is_admin(sender):
            return []
        args = [to_unicode(a) for a in args]
        if len(args) <= 1:
            prefix = args[0].lower() if args else ""
            return [x for x in ("start","stop","list","autostatus","coreprotect","inspect","create","createhere","stage","reporter","stabilize","dismiss","cleanupall","save","reload","debug") if x.startswith(prefix)]
        return []


class AnomalyCommand(Command, TabCompleter):
    def __init__(self, manager):
        Command.__init__(self, "anomaly", "Server anomaly administration", "/anomaly", build_java_list([]))
        self.manager = manager
        try:
            self.setPermission(to_java_string(AnomalyConfig.ADMIN_PERMISSION))
        except Exception:
            pass
    def execute(self, sender, command_label, args):
        try:
            return bool(self.manager.handle_command(sender, list(args)))
        except Exception as exc:
            log_error(u"/anomaly execution error", exc); return True
    def tabComplete(self, sender, alias, args, location=None):
        return build_java_list(self.manager.tab_complete(sender, list(args)))


manager = None

def on_enable():
    global manager
    if JAVA_AVAILABLE and System is not None:
        try:
            old = System.getProperties().get(AnomalyConfig.MANAGER_PROPERTY)
            if old is not None and old is not manager and hasattr(old, "shutdown_from_replacement"):
                old.shutdown_from_replacement()
        except Exception:
            pass
    manager = AnomalyManager()
    manager.start()

def on_disable():
    global manager
    if manager is not None:
        manager.stop()
    manager = None

def stop(script=None):
    on_disable()

if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

# =============================================================================
# PLAYER INFECTION — event phase / test-cg
# =============================================================================
try:
    from org.bukkit import Sound as _InfSound, NamespacedKey as _InfKey
except Exception:
    _InfSound = None
    _InfKey = None

INF_PROPERTY = "SmartY_AnomalyInfectionController"
INF_FILE = os.path.join(AnomalyConfig.DATA_DIR, "anomaly-infections.json")
INF_BACKUP = INF_FILE + ".bak"
INF_ZONE_INTERVAL = 5
INF_ZONE_CHANCE = 0.25
INF_CONTACT_INTERVAL = 5
INF_CONTACT_RADIUS = 5.0
INF_STAGE1_SECONDS = 2 * 3600
INF_STAGE2_SECONDS = 4 * 3600
INF_INSOMNIA_CHANCE = 0.50
INF_COMPASS_INTERVAL = 3

def _inf_effect(name, fallback=None):
    if PotionEffectType is None:
        return None
    try:
        value = getattr(PotionEffectType, name, None)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        if _InfKey is not None and hasattr(PotionEffectType, "getByKey"):
            value = PotionEffectType.getByKey(_InfKey.minecraft(name.lower()))
            if value is not None:
                return value
    except Exception:
        pass
    if fallback:
        try:
            return getattr(PotionEffectType, fallback, None)
        except Exception:
            pass
    return None

_INF_NAUSEA = _inf_effect("NAUSEA", "CONFUSION")
_INF_DARKNESS = _inf_effect("DARKNESS")

class AnomalyInfectionController(object):
    def __init__(self, anomaly_manager):
        self.manager = anomaly_manager
        self.plugin = anomaly_manager.plugin
        self.active = False
        self.listeners = []
        self.task_ids = []
        self.data = self._load()
        self.zone_next = {}
        self.symptom_next = {}
        self.compass_next = {}
        self.contact_next = 0
        self.last_pulse_key = None
        self.old_handle = None
        self.old_tab = None
        self._normalize()

    def _default(self): return {"schema_version": 1, "players": {}}
    def _normalize(self):
        if not isinstance(self.data, dict): self.data = self._default()
        if not isinstance(self.data.get("players"), dict): self.data["players"] = {}
        for uid_key in list(self.data["players"].keys()):
            r = self.data["players"].get(uid_key)
            if not isinstance(r, dict):
                self.data["players"].pop(uid_key, None); continue
            r.setdefault("uuid", uid_key); r.setdefault("name", u"?")
            r.setdefault("infected_at", now_ts()); r["stage"] = max(1, min(3, safe_int(r.get("stage"), 1)))
            r.setdefault("stage_started_at", r.get("infected_at", now_ts())); r.setdefault("source", "UNKNOWN")
            r.setdefault("source_anomaly_id", None); r.setdefault("source_player_uuid", None)
            r.setdefault("insomnia_night_key", None); r.setdefault("insomnia_blocked", False)

    def _load_path(self, path):
        with open(path, "r") as handle: raw = json.load(handle, parse_constant=reject_json_constant)
        if not isinstance(raw, dict): raise ValueError("infection database root must be an object")
        return raw
    def _load(self):
        try:
            if os.path.exists(INF_FILE): return self._load_path(INF_FILE)
        except Exception as exc: log_error(u"Cannot read anomaly-infections.json", exc)
        try:
            if os.path.exists(INF_BACKUP): return self._load_path(INF_BACKUP)
        except Exception as exc: log_error(u"Cannot read infection backup", exc)
        return self._default()
    def _save(self):
        try:
            if not os.path.exists(AnomalyConfig.DATA_DIR): os.makedirs(AnomalyConfig.DATA_DIR)
            temp = INF_FILE + ".tmp"
            with open(temp, "w") as handle:
                handle.write(json.dumps(self.data, indent=2, ensure_ascii=True, sort_keys=True, allow_nan=False)); handle.flush()
                try: os.fsync(handle.fileno())
                except Exception: pass
            if os.path.exists(INF_FILE):
                backup_tmp = INF_BACKUP + ".tmp"
                with open(INF_FILE, "rb") as source:
                    with open(backup_tmp, "wb") as target: target.write(source.read()); target.flush()
                atomic_replace_file(backup_tmp, INF_BACKUP)
            atomic_replace_file(temp, INF_FILE); return True
        except Exception as exc:
            log_error(u"Cannot save anomaly-infections.json", exc); return False

    def start(self):
        self.active = True
        self._register_event(PlayerBedEnterEvent, self.on_bed, EventPriority.HIGHEST)
        self._schedule(self.tick, 20, 20)
        self._patch_commands()
        log_action(u"Infection system started; infected={0}.".format(len(self.data["players"])))
    def stop(self):
        self.active = False; self._unpatch_commands()
        for listener in self.listeners:
            try: HandlerList.unregisterAll(listener)
            except Exception: pass
        for task_id in self.task_ids:
            try: Bukkit.getScheduler().cancelTask(int(task_id))
            except Exception: pass
        self.listeners = []; self.task_ids = []; self._save()
    def _register_event(self, event_class, callback, priority):
        listener = EmptyListener(); executor = CallbackExecutor(callback)
        Bukkit.getPluginManager().registerEvent(event_class, listener, priority, executor, self.plugin, False)
        self.listeners.append(listener)
    def _schedule(self, callback, delay, period):
        task = Bukkit.getScheduler().runTaskTimer(self.plugin, CallbackRunnable(callback), int(delay), int(period))
        self.task_ids.append(int(task.getTaskId()))
    def uid(self, player): return str(player.getUniqueId())
    def record(self, player): return self.data["players"].get(self.uid(player))

    def infect(self, player, source="ZONE", anomaly=None, source_player=None, stage=1):
        uid_key = self.uid(player)
        if uid_key in self.data["players"]: return False
        now = now_ts(); stage = max(1, min(3, safe_int(stage, 1)))
        self.data["players"][uid_key] = {
            "uuid": uid_key, "name": to_unicode(player.getName()), "infected_at": now,
            "stage": stage, "stage_started_at": now, "source": to_unicode(source),
            "source_anomaly_id": anomaly.get("id") if isinstance(anomaly, dict) else None,
            "source_player_uuid": self.uid(source_player) if source_player is not None else None,
            "insomnia_night_key": None, "insomnia_blocked": False
        }
        self.zone_next.pop(uid_key, None); self.symptom_next[uid_key] = now + random.randint(120, 300)
        if not self._save(): self.data["players"].pop(uid_key, None); return False
        log_action(u"Player infected: {0}, source={1}.".format(player.getName(), source)); return True
    def clear(self, player):
        uid_key = self.uid(player); removed = self.data["players"].pop(uid_key, None)
        self.zone_next.pop(uid_key, None); self.symptom_next.pop(uid_key, None); self.compass_next.pop(uid_key, None)
        try: player.setCompassTarget(player.getWorld().getSpawnLocation())
        except Exception: pass
        if removed is None: return False
        self._save(); return True
    def set_stage(self, player, stage):
        stage = max(1, min(3, safe_int(stage, 1))); r = self.record(player)
        if r is None: return self.infect(player, "ADMIN", stage=stage)
        r["stage"] = stage; r["stage_started_at"] = now_ts(); r["insomnia_night_key"] = None; r["insomnia_blocked"] = False
        self.symptom_next[self.uid(player)] = now_ts() + 5; self._save(); return True

    def _sound(self, name):
        try: return getattr(_InfSound, name, None) if _InfSound is not None else None
        except Exception: return None
    def _play(self, player, names, volume=0.45, pitch=None):
        sound = self._sound(random.choice(names))
        if sound is None: return
        try: player.playSound(player.getLocation(), sound, float(volume), float(pitch if pitch is not None else random.uniform(0.55, 1.30)))
        except Exception: pass
    def _particle(self, names):
        if Particle is None: return None
        for name in names:
            try:
                value = getattr(Particle, name, None)
                if value is not None: return value
            except Exception: pass
        return None
    def _particles(self, player, public, count):
        particle = self._particle(("SCULK_SOUL", "SOUL", "ASH")) if public else self._particle(("ASH", "SOUL", "PORTAL"))
        if particle is None: return
        try:
            loc = player.getLocation().clone().add(0.0, 0.2, 0.0)
            if public: player.getWorld().spawnParticle(particle, loc, count, 0.45, 0.2, 0.45, 0.015)
            else: player.spawnParticle(particle, loc, count, 0.35, 0.1, 0.35, 0.01)
        except Exception: pass
    def _effect(self, player, effect_type, seconds):
        if PotionEffect is None or effect_type is None: return
        try: player.addPotionEffect(PotionEffect(effect_type, int(seconds * 20), 0, False, False, False), True)
        except Exception: pass
    def _puke(self, player, lo, hi):
        try: Bukkit.dispatchCommand(Bukkit.getConsoleSender(), to_java_string(u"brew puke {0} {1}".format(player.getName(), random.randint(lo, hi))))
        except Exception as exc: self.manager.log_error_throttled("infection-puke", u"Brewery puke failed", exc, 120)
    def _symptom_delay(self, stage):
        return random.randint(90, 240) if stage == 1 else (random.randint(45, 120) if stage == 2 else random.randint(30, 90))
    def _symptom(self, player, stage):
        strange = ("AMBIENT_CAVE", "BLOCK_SCULK_SENSOR_CLICKING", "ENTITY_ENDERMAN_STARE", "BLOCK_RESPAWN_ANCHOR_DEPLETE")
        sculk = ("BLOCK_SCULK_SENSOR_CLICKING", "BLOCK_SCULK_SHRIEKER_SHRIEK", "ENTITY_WARDEN_HEARTBEAT", "ENTITY_WARDEN_AMBIENT")
        if stage == 1:
            roll = random.random()
            if roll < 0.55: self._play(player, strange, 0.35)
            elif roll < 0.78: self._particles(player, False, random.randint(2,5)); self._play(player, strange, 0.25)
            else:
                self._effect(player, _INF_NAUSEA, 5); self._play(player, strange, 0.35)
                if random.random() < 0.35: self._puke(player, 1, 2)
            return
        self._play(player, sculk, 0.50)
        if random.random() < 0.70: self._play(player, strange, 0.30)
        self._particles(player, True, random.randint(5,10))
        if random.random() < (0.60 if stage == 2 else 0.78):
            self._effect(player, _INF_NAUSEA, random.randint(10,15) if stage == 2 else random.randint(12,18))
            if random.random() < (0.40 if stage == 2 else 0.55): self._puke(player, 2, 4 if stage == 2 else 5)

    def _progress_and_symptoms(self, players, now):
        for player in players:
            r = self.record(player)
            if r is None: continue
            stage = safe_int(r.get("stage"), 1, 1, 3); started = safe_int(r.get("stage_started_at"), r.get("infected_at", now))
            wait = INF_STAGE1_SECONDS if stage == 1 else INF_STAGE2_SECONDS
            if stage < 3 and now - started >= wait:
                stage += 1; r["stage"] = stage; r["stage_started_at"] = now; r["insomnia_night_key"] = None; r["insomnia_blocked"] = False
                self.symptom_next[self.uid(player)] = now + random.randint(20,60); self._save()
            due = safe_int(self.symptom_next.get(self.uid(player)), 0)
            if due <= 0: self.symptom_next[self.uid(player)] = now + self._symptom_delay(stage)
            elif now >= due: self._symptom(player, stage); self.symptom_next[self.uid(player)] = now + self._symptom_delay(stage)
            if stage >= 3: self._random_compass(player, now)

    def _zone_exposure(self, players, now):
        healthy = set()
        for player in players:
            uid_key = self.uid(player)
            if self.record(player) is not None: self.zone_next.pop(uid_key, None); continue
            healthy.add(uid_key); anomaly = self.manager.anomaly_at_location(player.getLocation())
            if anomaly is None: self.zone_next.pop(uid_key, None); continue
            due = self.zone_next.get(uid_key)
            if due is not None and now < due: continue
            self.zone_next[uid_key] = now + INF_ZONE_INTERVAL
            if random.random() < INF_ZONE_CHANCE: self.infect(player, "ZONE", anomaly=anomaly)
        for uid_key in list(self.zone_next.keys()):
            if uid_key not in healthy: self.zone_next.pop(uid_key, None)
    def _contact_chance(self, distance):
        if distance > INF_CONTACT_RADIUS: return 0.0
        return min(0.30, max(0.0, (6.0 - float(distance)) * 0.05))
    def _contact_spread(self, players, now):
        if now < self.contact_next: return
        self.contact_next = now + INF_CONTACT_INTERVAL
        sources = [p for p in players if self.record(p) is not None and safe_int(self.record(p).get("stage"), 1) >= 2]
        for target in [p for p in players if self.record(p) is None]:
            nearest = None; nearest_d = INF_CONTACT_RADIUS + 1.0
            for source in sources:
                try:
                    if source.getWorld() != target.getWorld(): continue
                    d = source.getLocation().distance(target.getLocation())
                    if d <= INF_CONTACT_RADIUS and d < nearest_d: nearest, nearest_d = source, d
                except Exception: pass
            if nearest is not None and random.random() < self._contact_chance(nearest_d): self.infect(target, "CONTACT", source_player=nearest)
    def _pulse(self, player, stage):
        self._effect(player, _INF_DARKNESS, random.randint(2,5)); self._play(player, ("ENTITY_WARDEN_HEARTBEAT","BLOCK_SCULK_SENSOR_CLICKING"), 0.70, random.uniform(0.55,0.80)); self._particles(player, stage >= 2, random.randint(5,12))
    def _global_pulses(self, players):
        local = time.localtime(); minute = int(local.tm_min)
        if minute not in (0,30): return
        key = time.strftime("%Y%m%d%H%M", local)
        if key == self.last_pulse_key: return
        self.last_pulse_key = key
        for player in players:
            r = self.record(player)
            if r is None: continue
            stage = safe_int(r.get("stage"),1,1,3)
            if minute == 30 and stage < 3: continue
            self._pulse(player, stage)
    def _random_compass(self, player, now):
        uid_key = self.uid(player)
        if now < safe_int(self.compass_next.get(uid_key),0): return
        self.compass_next[uid_key] = now + INF_COMPASS_INTERVAL
        try:
            limit = 29900000; player.setCompassTarget(Location(player.getWorld(), random.randint(-limit,limit)+0.5, 64.0, random.randint(-limit,limit)+0.5))
        except Exception: pass
    def on_bed(self, event):
        player = event.getPlayer(); r = self.record(player)
        if r is None or safe_int(r.get("stage"),1) < 3: return
        key = u"{0}:{1}".format(player.getWorld().getName(), int(player.getWorld().getFullTime() // 24000))
        if to_unicode(r.get("insomnia_night_key")) != key:
            r["insomnia_night_key"] = key; r["insomnia_blocked"] = random.random() < INF_INSOMNIA_CHANCE; self._save()
        if r.get("insomnia_blocked"): event.setCancelled(True); send_message(player, u"&cВы страдаете бессонницей.")
    def tick(self):
        if not self.active or not self.manager.active: return
        now = now_ts()
        try: players = list(Bukkit.getOnlinePlayers())
        except Exception: players = []
        try: self._zone_exposure(players,now); self._contact_spread(players,now); self._progress_and_symptoms(players,now); self._global_pulses(players)
        except Exception as exc: self.manager.log_error_throttled("infection-tick", u"Infection cycle failed", exc)

    def _admin(self, sender, args):
        if not args or args[0].lower() in ("list","status"):
            if len(args) >= 2:
                player = Bukkit.getPlayer(to_java_string(args[1])); r = self.record(player) if player is not None else None
                send_message(sender, AnomalyConfig.PREFIX + (u"&7{0}: стадия {1}, source={2}.".format(player.getName(),r.get("stage"),r.get("source")) if r is not None else u"&7Игрок не заражён/не онлайн.")); return True
            send_message(sender, AnomalyConfig.PREFIX + u"&7Заражённых: &f{0}".format(len(self.data["players"]))); return True
        sub = args[0].lower()
        if sub in ("infect","stage","clear") and len(args) >= 2:
            player = Bukkit.getPlayer(to_java_string(args[1]))
            if player is None: send_message(sender,u"&cИгрок должен быть онлайн."); return True
            if sub == "clear": ok = self.clear(player)
            else:
                stage = safe_int(args[2],1,1,3) if len(args)>=3 else 1; ok = self.infect(player,"ADMIN",stage=stage) if sub=="infect" else self.set_stage(player,stage)
            send_message(sender, u"&aГотово." if ok else u"&eБез изменений."); return True
        send_message(sender,u"&7infection: list | status <player> | infect <player> [1-3] | stage <player> <1-3> | clear <player>"); return True
    def _patch_commands(self):
        self.old_handle = self.manager.handle_command; self.old_tab = self.manager.tab_complete; controller = self; old_handle = self.old_handle; old_tab = self.old_tab
        def handle(sender,args):
            converted=[to_unicode(x) for x in args]
            if converted and converted[0].lower()=="infection" and controller.manager.is_admin(sender): return controller._admin(sender,converted[1:])
            return old_handle(sender,args)
        def tab(sender,args):
            converted=[to_unicode(x) for x in args]
            if not controller.manager.is_admin(sender): return old_tab(sender,args)
            if len(converted)<=1:
                base=list(old_tab(sender,args)); prefix=converted[0].lower() if converted else ""
                if "infection".startswith(prefix) and "infection" not in base: base.append("infection")
                return base
            if converted[0].lower()!="infection": return old_tab(sender,args)
            if len(converted)==2: return [x for x in ("list","status","infect","stage","clear") if x.startswith(converted[-1].lower())]
            return []
        self.manager.handle_command=handle; self.manager.tab_complete=tab
    def _unpatch_commands(self):
        try:
            if self.old_handle is not None: self.manager.handle_command=self.old_handle
            if self.old_tab is not None: self.manager.tab_complete=self.old_tab
        except Exception: pass

infection_controller = None

def _start_infection():
    global infection_controller
    if manager is None or not BUKKIT_AVAILABLE: return
    try:
        old = System.getProperties().get(INF_PROPERTY) if JAVA_AVAILABLE and System is not None else None
        if old is not None and hasattr(old,"stop"): old.stop()
    except Exception: pass
    infection_controller = AnomalyInfectionController(manager); infection_controller.start()
    try:
        if JAVA_AVAILABLE and System is not None: System.getProperties().put(INF_PROPERTY,infection_controller)
    except Exception: pass

_start_infection()
_base_anomaly_on_disable = on_disable

def on_disable():
    global infection_controller
    if infection_controller is not None:
        try: infection_controller.stop()
        except Exception as exc: log_error(u"Infection shutdown error",exc)
    infection_controller=None; _base_anomaly_on_disable()

def stop(script=None):
    on_disable()
