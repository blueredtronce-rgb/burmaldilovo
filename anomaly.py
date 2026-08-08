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
                # The entire active radius is a protected anomaly zone.  This
                # prevents a replacement block from being mistaken for a
                # player-owned block during later restoration.
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

    # integrations ---------------------------------------------------------

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

    # lookups --------------------------------------------------------------

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

    # active-zone effects --------------------------------------------------

    def on_bed_enter(self, event):
        try:
            player = event.getPlayer()
            if self.anomaly_at_location(player.getLocation()) is not None:
                event.setCancelled(True)
        except Exception as exc:
            self.log_error_throttled("bed-protection", u"Bed protection event failed", exc)

    def on_creature_spawn(self, event):
        try:
            # Some Bukkit/Paper event subclasses share a HandlerList.  The
            # executor can therefore receive ItemSpawnEvent or another sibling
            # event even though it was registered for CreatureSpawnEvent.
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
        """Animate sparse smoke columns throughout each already-loaded anomaly."""
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
                    # Uniform area distribution (sqrt) avoids a dense centre
                    # and does not inspect or load any missing chunks.
                    distance = radius * math.sqrt(random.random()) * 0.95
                    angle = random.random() * math.pi * 2.0
                    x = int(round(float(anomaly.get("x")) + math.cos(angle) * distance))
                    z = int(round(float(anomaly.get("z")) + math.sin(angle) * distance))
                    if not self.chunk_loaded(world, x, z):
                        continue
                    ground_y = int(world.getHighestBlockYAt(x, z)) + 1
                    rise = (phase + index * 7) % (AnomalyConfig.PARTICLE_MAX_HEIGHT + 1)
                    # Each source advances upward by two blocks per second,
                    # then restarts at the ground; zero spread prevents side drift.
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

    # world/candidate safety ----------------------------------------------

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
        # Do not create an anomaly over rivers, oceans, lakes or lava.  A
        # single wet sample is enough to reject a candidate so the protected
        # radius does not overlap the shoreline and distort the lake bed.
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
        threshold = (
                AnomalyConfig.ANOMALY_MIN_DISTANCE *
                AnomalyConfig.ANOMALY_MIN_DISTANCE
        )
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
            if dist_sq_2d(
                    anomaly.get("x"), anomaly.get("z"),
                    home.get("x"), home.get("z")
            ) <= max_sq:
                count += 1
        return count

    def town_capacity_ok(self, world_name, x, z):
        return True

    def validate_center(self, world, x, z, allow_near_town=False):
        if world is None or not self.world_is_normal(world):
            return False, u"только обычный мир"
        if (AnomalyConfig.MAX_ACTIVE > 0 and
                len(self.active_anomalies()) >= AnomalyConfig.MAX_ACTIVE):
            return False, u"достигнут глобальный лимит активных аномалий"
        if not self.all_chunks_loaded_for_radius(
                world, x, z, AnomalyConfig.SAFETY_CONTAINER_RADIUS
        ):
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

    # create/autospawn -----------------------------------------------------

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
            "id": anomaly_id,
            "status": "ACTIVE",
            "stage": 1,
            "radius": AnomalyConfig.STAGE1_RADIUS,
            "world": to_unicode(world.getName()),
            "x": int(point.get("x")),
            "y": int(point.get("y")),
            "z": int(point.get("z")),
            "created_at": now,
            "stage_started_at": now,
            "source_type": to_unicode(source_type),
            "source_player_uuid": None,
            "source_player_name": None,
            "city_id": None,
            "city_name": None,
            "reporter_uuid": None,
            "reporter_name": None,
            "blocks": [],
            "player_touched_columns": {},
            "stabilization_started_at": 0,
            "stabilization_total": 0,
            "fixed_at": 0,
            "reward": {
                "operation_id": "anomaly_reward_v1:{0}".format(anomaly_id),
                "state": "NOT_READY",
                "amount": AnomalyConfig.REWARD_AMOUNT,
                "prepared_at": 0,
                "before_balance": None,
                "expected_balance": None,
                "paid_at": 0,
                "last_error": None
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
        """Append an audit line; the JSON journal remains the source of truth."""
        line = (u"id={0} source={1} city={2} player={3} "
                u"world={4} x={5} y={6} z={7}").format(
            anomaly.get("id"), anomaly.get("source_type"),
            anomaly.get("city_name") or "-", anomaly.get("source_player_name") or "-",
            anomaly.get("world"), anomaly.get("x"), anomaly.get("y"), anomaly.get("z")
        )
        if not append_utf8_log(AnomalyConfig.SPAWN_LOG_FILE, "CREATE", line):
            log_error(u"Cannot append anomaly spawn log for {0}".format(anomaly.get("id")))

    def player_far_from_all_towns(self, player):
        try:
            loc = player.getLocation()
            world_name = to_unicode(loc.getWorld().getName())
            threshold = (
                    AnomalyConfig.EXPLORER_MIN_FROM_TOWN *
                    AnomalyConfig.EXPLORER_MIN_FROM_TOWN
            )
            for city in self.get_city_records():
                home = self.city_home(city)
                if home is None or to_unicode(home.get("world")) != world_name:
                    continue
                if dist_sq_2d(
                        loc.getX(), loc.getZ(), home.get("x"), home.get("z")
                ) <= threshold:
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
        self.auto_note(u"старт проверки: городов={0}, пропускаемый город={1}".format(
            len(cities), skipped_city or u"-"))
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
            point, reason = self.safe_point_around(
                world, home.get("x"), home.get("z"),
                AnomalyConfig.CITY_POINT_MIN, AnomalyConfig.CITY_POINT_MAX, 60,
                allow_near_town=True
            )
            if point is None:
                self.auto_note(u"город {0}: безопасная точка не найдена ({1})".format(city.get("name"), reason))
                continue
            anomaly = self.create_anomaly(point, "CITY", city=city)
            if anomaly is not None:
                rotation["skip_city_id"] = key
                self.storage.save(self.data)
                log_info(u"Autospawned {0} near town {1}.".format(
                    anomaly.get("id"), to_unicode(city.get("name"))
                ))
                self.auto_note(u"создана {0} у города {1}".format(anomaly.get("id"), city.get("name")))
                return

        try:
            players = list(Bukkit.getOnlinePlayers())
        except Exception:
            players = []
        players.sort(key=lambda player: str(player.getUniqueId()))
        skipped_player = to_unicode(rotation.get("skip_player_uuid"))
        rotation["skip_player_uuid"] = None
        self.auto_note(u"переход к игрокам: онлайн={0}, пропускаемый UUID={1}".format(
            len(players), skipped_player or u"-"))
        for player in players:
            try:
                uuid_key = str(player.getUniqueId())
                if uuid_key == skipped_player:
                    self.auto_note(u"игрок {0}: пропущен по ротации".format(player.getName()))
                    continue
                world = player.getWorld()
                if not self.world_is_normal(world) or not self.player_far_from_all_towns(player):
                    self.auto_note(u"игрок {0}: не подходит (мир или расстояние до города)".format(player.getName()))
                    continue
                loc = player.getLocation()
                point, reason = self.safe_point_around(
                    world, loc.getX(), loc.getZ(),
                    AnomalyConfig.EXPLORER_POINT_MIN,
                    AnomalyConfig.EXPLORER_POINT_MAX, 18
                )
                if point is None:
                    self.auto_note(u"игрок {0}: безопасная точка не найдена ({1})".format(player.getName(), reason))
                    continue
                anomaly = self.create_anomaly(point, "EXPLORER", source_player=player)
                if anomaly is not None:
                    rotation["skip_player_uuid"] = uuid_key
                    self.storage.save(self.data)
                    log_info(u"Autospawned {0} around explorer {1}.".format(
                        anomaly.get("id"), to_unicode(player.getName())
                    ))
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
        point, reason = self.safe_point_around(
            world, home.get("x"), home.get("z"),
            AnomalyConfig.CITY_POINT_MIN,
            AnomalyConfig.CITY_POINT_MAX, 40
        )
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
        point = {
            "world": world,
            "x": x,
            "y": int(world.getHighestBlockYAt(x, z)) + 1,
            "z": z
        }
        anomaly = self.create_anomaly(point, "ADMIN_HERE")
        if anomaly is None:
            return None, u"не удалось сохранить новую аномалию"
        return anomaly, u"ok"

    # terrain distortion ---------------------------------------------------

    def block_key(self, world_name, x, y, z):
        return "{0}:{1}:{2}:{3}".format(
            to_unicode(world_name), int(x), int(y), int(z)
        )

    def existing_block_keys(self, anomaly):
        result = set()
        for record in anomaly.get("blocks", []):
            if not isinstance(record, dict):
                continue
            result.add(self.block_key(
                record.get("world"), record.get("x"),
                record.get("y"), record.get("z")
            ))
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
            min_radius = 0.0
            max_radius = float(AnomalyConfig.STAGE1_RADIUS)
        elif applied_surface < AnomalyConfig.STAGE1_SURFACE_TARGET:
            min_radius = 0.0
            max_radius = float(AnomalyConfig.STAGE1_RADIUS)
        else:
            min_radius = float(AnomalyConfig.STAGE1_RADIUS) + 0.5
            max_radius = float(AnomalyConfig.STAGE2_RADIUS)

        # A dense or awkward biome can reject many random columns.  Keep the
        # distortion progressing instead of treating a short unlucky streak as
        # the end of the anomaly.
        for unused in range(160):
            x, z = self.random_point(
                anomaly.get("x"), anomaly.get("z"), min_radius, max_radius
            )
            if not self.chunk_loaded(world, x, z):
                continue
            touched_key = "{0}:{1}".format(int(x), int(z))
            if touched_key in anomaly.get("player_touched_columns", {}):
                continue
            ground = self.find_natural_ground(world, x, z)
            if ground is None:
                continue
            key = self.block_key(
                anomaly.get("world"), ground.getX(), ground.getY(), ground.getZ()
            )
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
                "world": to_unicode(anomaly.get("world")),
                "x": int(ground.getX()),
                "y": int(ground.getY()),
                "z": int(ground.getZ()),
                "kind": "surface",
                "stage": stage,
                "original_data": original,
                "anomaly_data": anomaly_data,
                "state": "PLANNED",
                "planned_at": now_ts()
            }
            vein = None
            if random.random() < AnomalyConfig.VEIN_CHANCE:
                above = world.getBlockAt(
                    int(ground.getX()), int(ground.getY()) + 1, int(ground.getZ())
                )
                above_key = self.block_key(
                    anomaly.get("world"),
                    above.getX(), above.getY(), above.getZ()
                )
                if (
                        above_key not in existing_keys and
                        material_name(above.getType()) in ("AIR", "CAVE_AIR")
                ):
                    vein = {
                        "world": to_unicode(anomaly.get("world")),
                        "x": int(above.getX()),
                        "y": int(above.getY()),
                        "z": int(above.getZ()),
                        "kind": "vein",
                        "stage": stage,
                        "original_data": self.serialize_block(above),
                        "anomaly_data": self.make_vein_data_string(),
                        "state": "PLANNED",
                        "planned_at": now_ts()
                    }
            return record, vein
        return None, None

    def apply_planned_record(self, record):
        world = Bukkit.getWorld(to_java_string(record.get("world")))
        if world is None:
            return False
        x = int(record.get("x"))
        y = int(record.get("y"))
        z = int(record.get("z"))
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
            if not self.coreprotect_log_transition(
                    block, original, anomaly_data,
                    AnomalyConfig.COREPROTECT_APPLY_ACTOR, record, "apply"):
                record["state"] = "COREPROTECT_FAILED"
                record["last_error"] = u"CoreProtect did not confirm both journal records"
                return False
            block.setBlockData(data, False)
            record["state"] = "APPLIED"
            record["applied_at"] = now_ts()
            return True
        except Exception as exc:
            record["state"] = "APPLY_FAILED"
            record["last_error"] = to_unicode(exc)
            log_error(u"Cannot apply anomaly block at {0}:{1},{2},{3}".format(
                record.get("world"), x, y, z
            ), exc)
            return False

    def surface_count(self, anomaly):
        count = 0
        for record in anomaly.get("blocks", []):
            if (
                    isinstance(record, dict) and
                    record.get("kind") == "surface" and
                    record.get("state") in ("APPLIED", "PLANNED")
            ):
                count += 1
        return count

    def desired_surface_count(self, anomaly):
        stage = safe_int(anomaly.get("stage"), 1)
        elapsed = max(0, now_ts() - safe_int(
            anomaly.get("stage_started_at"),
            anomaly.get("created_at", now_ts())
        ))
        fraction = min(1.0, float(elapsed) / float(AnomalyConfig.STAGE_SECONDS))
        if stage <= 1:
            return min(
                AnomalyConfig.STAGE1_SURFACE_TARGET,
                max(1, int(math.floor(
                    AnomalyConfig.STAGE1_SURFACE_TARGET * fraction
                )) + 1)
            )
        return min(
            AnomalyConfig.STAGE2_SURFACE_TARGET_TOTAL,
            AnomalyConfig.STAGE1_SURFACE_TARGET +
            int(math.floor(
                AnomalyConfig.STAGE2_ADDITIONAL_TARGET * fraction
            ))
        )

    def distortion_cycle(self):
        if not self.active:
            return
        if not self.coreprotect_ready_for_mutation("distortion_cycle"):
            return
        changed_any = False
        for anomaly in list(self.active_anomalies()):
            if anomaly.get("status") != "ACTIVE":
                continue
            stage = safe_int(anomaly.get("stage"), 1)
            if stage <= 1:
                target = AnomalyConfig.STAGE1_SURFACE_TARGET
            else:
                target = AnomalyConfig.STAGE2_SURFACE_TARGET_TOTAL
            current = self.surface_count(anomaly)
            if current >= target:
                continue
            # Add at most one surface block every timer run.  Do not use the
            # elapsed-stage calculation here: it initially evaluates to one,
            # which used to stop all subsequent distortions for 96 hours.
            remaining = min(AnomalyConfig.DISTORTION_MAX_PER_CYCLE, target - current)
            existing_keys = self.existing_block_keys(anomaly)
            planned = []
            for unused in range(remaining):
                surface, vein = self.planned_surface_record(anomaly, existing_keys)
                if surface is None:
                    break
                planned.append(surface)
                existing_keys.add(self.block_key(
                    surface.get("world"), surface.get("x"),
                    surface.get("y"), surface.get("z")
                ))
                if vein is not None:
                    planned.append(vein)
                    existing_keys.add(self.block_key(
                        vein.get("world"), vein.get("x"),
                        vein.get("y"), vein.get("z")
                    ))
            if not planned:
                continue

            anomaly.setdefault("blocks", []).extend(planned)
            if not self.storage.save(self.data):
                del anomaly["blocks"][-len(planned):]
                log_info(u"Skipped distortion for {0}: journal save failed.".format(
                    anomaly.get("id")
                ))
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
                if not isinstance(record, dict):
                    continue
                if record.get("state") not in ("PLANNED", "APPLY_FAILED"):
                    continue
                world = Bukkit.getWorld(to_java_string(record.get("world")))
                if world is None:
                    continue
                x = int(record.get("x"))
                y = int(record.get("y"))
                z = int(record.get("z"))
                if not self.chunk_loaded(world, x, z):
                    continue
                block = world.getBlockAt(x, y, z)
                current = self.serialize_block(block)
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

    # stage progression ----------------------------------------------------

    def stage_name(self, stage):
        return u"Подозрение" if safe_int(stage, 1) <= 1 else u"Усиление"

    def stage_cycle(self):
        if not self.active:
            return
        now = now_ts()
        changed = False
        for anomaly in self.active_anomalies():
            if anomaly.get("status") != "ACTIVE":
                continue
            stage = safe_int(anomaly.get("stage"), 1)
            if stage != 1:
                continue
            started = safe_int(
                anomaly.get("stage_started_at"),
                anomaly.get("created_at", now)
            )
            if now - started < AnomalyConfig.STAGE_SECONDS:
                continue
            anomaly["stage"] = 2
            anomaly["radius"] = AnomalyConfig.STAGE2_RADIUS
            anomaly["stage_started_at"] = now
            changed = True
            self.notify_admins(
                u"&dАномалия &f{0}&d перешла на стадию 2 «Усиление». "
                u"&7Центр: {1} [{2}, {3}], радиус ~{4}."
                .format(
                    anomaly.get("id"), anomaly.get("world"),
                    anomaly.get("x"), anomaly.get("z"),
                    AnomalyConfig.STAGE2_RADIUS
                )
            )
        if changed:
            self.storage.save(self.data)

    def manual_next_stage(self, anomaly):
        if anomaly.get("status") != "ACTIVE":
            return False, u"аномалия не активна"
        stage = safe_int(anomaly.get("stage"), 1)
        if stage >= 2:
            return False, u"стадии 3 и 4 пока не реализованы"
        anomaly["stage"] = 2
        anomaly["radius"] = AnomalyConfig.STAGE2_RADIUS
        anomaly["stage_started_at"] = now_ts()
        if not self.storage.save(self.data):
            anomaly["stage"] = 1
            anomaly["radius"] = AnomalyConfig.STAGE1_RADIUS
            return False, u"не удалось сохранить переход стадии"
        return True, u"стадия 2 включена"

    # stabilization --------------------------------------------------------

    def create_bossbar(self, anomaly):
        anomaly_id = anomaly.get("id")
        old = self.bossbars.get(anomaly_id)
        if old is not None:
            return old
        try:
            bar = Bukkit.createBossBar(
                to_java_string(u"Стабилизация {0}".format(anomaly_id)),
                BarColor.PURPLE, BarStyle.SOLID
            )
            bar.setProgress(0.0)
            self.bossbars[anomaly_id] = bar
            return bar
        except Exception as exc:
            log_error(u"Cannot create boss bar for {0}".format(anomaly_id), exc)
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
        except Exception:
            current = set()
        try:
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
                bar = self.create_bossbar(anomaly)
                self.bossbar_add_admins(bar)

    def start_stabilization(self, anomaly):
        if anomaly.get("status") == "FIXED":
            return False, u"аномалия уже закрыта"
        if anomaly.get("status") == "STABILIZING":
            return False, u"стабилизация уже идёт"
        if anomaly.get("status") != "ACTIVE":
            return False, u"аномалия не активна"
        old_status = anomaly.get("status")
        anomaly["status"] = "STABILIZING"
        anomaly["stabilization_started_at"] = now_ts()
        anomaly["stabilization_total"] = len(anomaly.get("blocks", []))
        if not self.storage.save(self.data):
            anomaly["status"] = old_status
            log_error(u"Cannot start stabilization for {0}: journal save failed".format(
                anomaly.get("id")
            ))
            return False, u"не удалось сохранить начало стабилизации"
        log_action(u"Stabilization started for {0}; blocks={1}; admin_cleanup={2}".format(
            anomaly.get("id"), len(anomaly.get("blocks", [])),
            bool(anomaly.get("admin_cleanup"))
        ))
        bar = self.create_bossbar(anomaly)
        self.bossbar_add_admins(bar)
        if not anomaly.get("blocks"):
            self.finish_stabilization(anomaly)
        return True, u"стабилизация запущена"

    def start_quiet_removal(self, anomaly):
        """Immediately hide a zone, then restore it without teleporting or loading chunks."""
        if anomaly is None:
            return False, u"аномалия не найдена"
        old_status = anomaly.get("status")
        if old_status == "FIXED":
            return False, u"аномалия уже закрыта"
        if old_status == "REMOVING":
            return False, u"тихое удаление уже выполняется"
        if old_status not in ("ACTIVE", "STABILIZING"):
            return False, u"аномалия не находится в удаляемом состоянии"
        old_admin_cleanup = anomaly.get("admin_cleanup")
        old_quiet_removal = anomaly.get("quiet_removal")
        anomaly["status"] = "REMOVING"
        anomaly["admin_cleanup"] = True
        anomaly["quiet_removal"] = True
        anomaly["stabilization_started_at"] = now_ts()
        anomaly["stabilization_total"] = len(anomaly.get("blocks", []))
        if not self.storage.save(self.data):
            anomaly["status"] = old_status
            anomaly["admin_cleanup"] = old_admin_cleanup
            anomaly["quiet_removal"] = old_quiet_removal
            log_error(u"Cannot start quiet removal for {0}: journal save failed".format(
                anomaly.get("id")
            ))
            return False, u"не удалось сохранить тихое удаление"
        self.remove_bossbar(anomaly.get("id"))
        log_action(u"Quiet removal started for {0}; blocks={1}".format(
            anomaly.get("id"), len(anomaly.get("blocks", []))
        ))
        if not anomaly.get("blocks"):
            self.finish_stabilization(anomaly)
        return True, u"аномалия скрыта; блоки восстанавливаются в загруженных чанках"

    def record_resolved(self, record):
        return record.get("state") in ("RESTORED", "SKIPPED_PLAYER")

    def unresolved_records(self, anomaly):
        return [
            record for record in anomaly.get("blocks", [])
            if isinstance(record, dict) and not self.record_resolved(record)
        ]

    def restore_record(self, record):
        world = Bukkit.getWorld(to_java_string(record.get("world")))
        if world is None:
            return False
        x = int(record.get("x"))
        y = int(record.get("y"))
        z = int(record.get("z"))
        if not self.chunk_loaded(world, x, z):
            return False
        block = world.getBlockAt(x, y, z)
        current = self.serialize_block(block)
        original = to_unicode(record.get("original_data"))
        anomaly_data = to_unicode(record.get("anomaly_data"))
        if current == original:
            record["state"] = "RESTORED"
            record["restored_at"] = now_ts()
            return True
        if current != anomaly_data:
            record["state"] = "SKIPPED_PLAYER"
            record["restored_at"] = now_ts()
            log_error(u"Restoration skipped because block was externally changed at {0}:{1},{2},{3}".format(
                record.get("world"), x, y, z
            ))
            return True
        try:
            data = Bukkit.createBlockData(to_java_string(original))
            if not self.coreprotect_log_transition(
                    block, anomaly_data, original,
                    AnomalyConfig.COREPROTECT_RESTORE_ACTOR, record, "restore"):
                record["state"] = "COREPROTECT_RESTORE_FAILED"
                record["last_error"] = u"CoreProtect did not confirm restoration journal records"
                return False
            block.setBlockData(data, False)
            record["state"] = "RESTORED"
            record["restored_at"] = now_ts()
            return True
        except Exception as exc:
            record["state"] = "RESTORE_FAILED"
            record["last_error"] = to_unicode(exc)
            log_error(u"Cannot restore anomaly block at {0}:{1},{2},{3}".format(
                record.get("world"), x, y, z
            ), exc)
            return False

    def stabilization_cycle(self):
        if not self.active:
            return
        if not self.coreprotect_ready_for_mutation("stabilization_cycle"):
            return
        changed = False
        for anomaly in list(self.data.get("anomalies", {}).values()):
            if not isinstance(anomaly, dict):
                continue
            if anomaly.get("status") not in ("STABILIZING", "REMOVING"):
                continue
            unresolved = self.unresolved_records(anomaly)
            total = max(
                1,
                safe_int(anomaly.get("stabilization_total"),
                         len(anomaly.get("blocks", [])))
            )
            if not unresolved:
                self.finish_stabilization(anomaly)
                continue
            cycles = max(
                1,
                int((AnomalyConfig.STABILIZE_SECONDS * 20) /
                    AnomalyConfig.STABILIZE_TICKS)
            )
            budget = max(1, int(math.ceil(float(total) / float(cycles))))
            processed = 0
            for record in unresolved:
                if processed >= budget:
                    break
                processed += 1
                if self.restore_record(record):
                    changed = True

            resolved_count = len([
                record for record in anomaly.get("blocks", [])
                if isinstance(record, dict) and self.record_resolved(record)
            ])
            progress = min(1.0, max(0.0, float(resolved_count) / float(total)))
            bar = None
            if anomaly.get("status") == "STABILIZING":
                bar = self.create_bossbar(anomaly)
            if bar is not None:
                try:
                    bar.setProgress(progress)
                    bar.setTitle(to_java_string(
                        u"Стабилизация {0}: {1}%".format(
                            anomaly.get("id"), int(progress * 100.0)
                        )
                    ))
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
        previous_status = anomaly.get("status")
        anomaly["status"] = "FIXED"
        anomaly["fixed_at"] = now_ts()
        if anomaly.get("admin_cleanup"):
            reward = anomaly.setdefault("reward", {})
            reward["state"] = "CANCELLED_ADMIN"
            reward["last_error"] = u"закрыто административной очисткой"
        anomaly_id = anomaly.get("id")
        if not self.storage.save(self.data):
            anomaly["status"] = previous_status
            anomaly["fixed_at"] = 0
            log_error(u"Cannot finish stabilization for {0}: journal save failed".format(
                anomaly_id
            ))
            return False
        self.remove_bossbar(anomaly_id)
        if anomaly.get("admin_cleanup"):
            ok, message = True, u"административная очистка, награда не выдана"
        else:
            ok, message = self.issue_reward(anomaly)
        self.notify_admins(
            u"&aАномалия &f{0}&a стабилизирована. &7Награда: {1}"
            .format(anomaly_id, message)
        )
        log_action(u"Stabilization completed for {0}; reward={1}".format(
            anomaly_id, message
        ))
        return ok

    # reward journal -------------------------------------------------------

    def reward_close_enough(self, left, right):
        if left is None or right is None:
            return False
        try:
            return abs(float(left) - float(right)) < 0.005
        except Exception:
            return False

    def issue_reward(self, anomaly):
        reward = anomaly.setdefault("reward", {})
        reward.setdefault("operation_id", "anomaly_reward_v1:{0}".format(anomaly.get("id")))
        reward.setdefault("amount", AnomalyConfig.REWARD_AMOUNT)
        state = to_unicode(reward.get("state") or "NOT_READY")

        if state == "PAID":
            return True, u"уже выплачена"
        reporter_uuid = anomaly.get("reporter_uuid")
        if not reporter_uuid:
            reward["state"] = "NO_REPORTER"
            reward["last_error"] = u"репортёр не назначен"
            self.storage.save(self.data)
            return False, u"репортёр не назначен"

        economy = self.get_economy_manager()
        if economy is None:
            reward["state"] = "FAILED"
            reward["last_error"] = u"экономика недоступна"
            self.storage.save(self.data)
            return False, u"экономика недоступна"

        try:
            current = float(economy.get_balance(str(reporter_uuid)))
        except Exception as exc:
            reward["state"] = "FAILED"
            reward["last_error"] = u"не удалось прочитать баланс: {0}".format(exc)
            log_error(u"Cannot read reward balance for anomaly {0}".format(anomaly.get("id")), exc)
            self.storage.save(self.data)
            return False, reward["last_error"]

        before = reward.get("before_balance")
        expected = reward.get("expected_balance")

        if state == "PREPARED":
            if before is None or expected is None:
                reward["state"] = "REVIEW_REQUIRED"
                reward["last_error"] = u"PREPARED-операция не содержит полного балансового журнала"
                self.storage.save(self.data)
                return False, u"нужна ручная проверка экономики"
            if self.reward_close_enough(current, expected):
                reward["state"] = "PAID"
                reward["paid_at"] = now_ts()
                reward["last_error"] = None
                self.storage.save(self.data)
                return True, u"подтверждена после восстановления"
            if before is not None and not self.reward_close_enough(current, before):
                reward["state"] = "REVIEW_REQUIRED"
                reward["last_error"] = (
                    u"неоднозначное состояние выплаты: ожидалось {0} или {1}, сейчас {2}"
                    .format(before, expected, current)
                )
                self.storage.save(self.data)
                return False, u"нужна ручная проверка экономики"

        if state == "REVIEW_REQUIRED":
            return False, u"нужна ручная проверка экономики"

        if state != "PREPARED":
            amount = safe_float(
                reward.get("amount"), AnomalyConfig.REWARD_AMOUNT, 0.01
            )
            before = current
            expected = round(before + amount, 2)
            reward["state"] = "PREPARED"
            reward["prepared_at"] = now_ts()
            reward["before_balance"] = before
            reward["expected_balance"] = expected
            reward["last_error"] = None
            if not self.storage.save(self.data):
                reward["state"] = "FAILED"
                reward["last_error"] = u"не удалось сохранить подготовленную операцию"
                return False, reward["last_error"]

        try:
            success, new_balance = economy.deposit_checked(
                str(reporter_uuid),
                float(reward.get("amount", AnomalyConfig.REWARD_AMOUNT)),
                None
            )
        except Exception as exc:
            reward["state"] = "PREPARED"
            reward["last_error"] = u"неоднозначная ошибка экономики: {0}".format(exc)
            log_error(u"Ambiguous economy error for anomaly {0}".format(anomaly.get("id")), exc)
            self.storage.save(self.data)
            return False, u"выплата оставлена на безопасном восстановлении"

        if not success:
            reward["state"] = "FAILED"
            reward["last_error"] = u"экономика отклонила начисление"
            self.storage.save(self.data)
            return False, reward["last_error"]

        if not self.reward_close_enough(new_balance, expected):
            reward["state"] = "REVIEW_REQUIRED"
            reward["last_error"] = (
                u"экономика вернула неожиданный баланс {0}, ожидалось {1}"
                .format(new_balance, expected)
            )
            self.storage.save(self.data)
            return False, u"начисление требует ручной проверки"

        reward["state"] = "PAID"
        reward["paid_at"] = now_ts()
        reward["last_error"] = None
        if not self.storage.save(self.data):
            reward["state"] = "PREPARED"
            return False, u"выплачено; подтверждение будет восстановлено по журналу"

        log_info(u"Reward {0}$ for {1} paid to UUID {2}; operation {3}."
        .format(
            reward.get("amount"), anomaly.get("id"),
            reporter_uuid, reward.get("operation_id")
        ))
        return True, u"5000$ выплачено"

    def recover_prepared_rewards(self):
        for anomaly in self.data.get("anomalies", {}).values():
            if not isinstance(anomaly, dict):
                continue
            if anomaly.get("status") != "FIXED":
                continue
            reward = anomaly.get("reward", {})
            if isinstance(reward, dict) and reward.get("state") == "PREPARED":
                self.issue_reward(anomaly)

    # command helpers ------------------------------------------------------

    def format_age(self, seconds):
        seconds = max(0, safe_int(seconds, 0))
        hours = seconds // 3600
        days = hours // 24
        hours = hours % 24
        if days:
            return u"{0}д {1}ч".format(days, hours)
        minutes = (seconds % 3600) // 60
        return u"{0}ч {1}м".format(hours, minutes)

    def inspect(self, sender, anomaly):
        reward = anomaly.get("reward", {})
        surface = len([
            r for r in anomaly.get("blocks", [])
            if isinstance(r, dict) and r.get("kind") == "surface"
        ])
        unresolved = len(self.unresolved_records(anomaly)) if anomaly.get("status") == "STABILIZING" else 0
        lines = [
            AnomalyConfig.PREFIX + u"&f{0} &7— {1}, стадия {2} «{3}»".format(
                anomaly.get("id"), anomaly.get("status"),
                anomaly.get("stage"), self.stage_name(anomaly.get("stage"))
            ),
            u"&7Мир/центр: &f{0} [{1}, {2}] &7R=&f{3}".format(
                anomaly.get("world"), anomaly.get("x"),
                anomaly.get("z"), anomaly.get("radius")
            ),
            u"&7Источник: &f{0} &7город=&f{1} &7игрок=&f{2}".format(
                anomaly.get("source_type"),
                anomaly.get("city_name") or u"-",
                anomaly.get("source_player_name") or u"-"
            ),
            u"&7Возраст стадии: &f{0} &7изменённых поверхностей: &f{1}".format(
                self.format_age(now_ts() - safe_int(anomaly.get("stage_started_at"), now_ts())),
                surface
            ),
            u"&7Репортёр: &f{0} &7reward=&f{1} &8({2})".format(
                anomaly.get("reporter_name") or u"-",
                reward.get("state", "NOT_READY"),
                reward.get("operation_id", "-")
            )
        ]
        if unresolved:
            lines.append(u"&7Осталось восстановить/проверить: &f{0}".format(unresolved))
        if reward.get("last_error"):
            lines.append(u"&cReward error: &f" + to_unicode(reward.get("last_error")))
        for line in lines:
            send_message(sender, line)

    def admin_list(self, sender):
        anomalies = sorted(
            self.data.get("anomalies", {}).values(),
            key=lambda item: to_unicode(item.get("id")) if isinstance(item, dict) else u""
        )
        if not anomalies:
            send_message(sender, AnomalyConfig.PREFIX + u"&7Аномалий нет.")
            return
        send_message(sender, AnomalyConfig.PREFIX + u"&fВсе зоны: &7{0}".format(len(anomalies)))
        for anomaly in anomalies:
            send_message(
                sender,
                u"&8- &f{0} &7{1} S{2} R{3} — {4} [{5}, {6}]".format(
                    anomaly.get("id"), anomaly.get("status"),
                    anomaly.get("stage"), anomaly.get("radius"),
                    anomaly.get("world"), anomaly.get("x"), anomaly.get("z")
                )
            )

    def debug_all(self, sender):
        anomalies = sorted(
            self.non_closed_anomalies(),
            key=lambda item: to_unicode(item.get("id"))
        )
        send_message(
            sender,
            AnomalyConfig.PREFIX + u"&eDEBUG: &f{0} незакрытых аномалий.".format(len(anomalies))
        )
        for anomaly in anomalies:
            reward = anomaly.get("reward", {})
            states = {}
            for record in anomaly.get("blocks", []):
                state = to_unicode(record.get("state", "UNKNOWN"))
                states[state] = states.get(state, 0) + 1
            send_message(
                sender,
                u"&8- &f{0} &7status={1} S{2} {3}[{4},{5}] "
                u"blocks={6} states={7} reporter={8} reward={9}".format(
                    anomaly.get("id"), anomaly.get("status"),
                    anomaly.get("stage"), anomaly.get("world"),
                    anomaly.get("x"), anomaly.get("z"),
                    len(anomaly.get("blocks", [])), states,
                    anomaly.get("reporter_name") or "-",
                    reward.get("state", "NOT_READY")
                )
            )

    def public_info(self, sender):
        if not isinstance(sender, Player):
            self.send_unknown_command(sender)
            return True
        anomaly = self.anomaly_at_location(sender.getLocation())
        if anomaly is None:
            self.send_unknown_command(sender)
            return True
        send_message(
            sender,
            u"&8Искажение мира: &7стадия &f{0} — «{1}»&7, примерный радиус &f~{2} блоков&7."
            .format(
                anomaly.get("stage"),
                self.stage_name(anomaly.get("stage")),
                anomaly.get("radius")
            )
        )
        return True

    def resolve_reporter(self, player_name):
        online = None
        try:
            online = Bukkit.getPlayer(to_java_string(player_name))
        except Exception:
            online = None
        if online is not None:
            return str(online.getUniqueId()), to_unicode(online.getName())

        economy = self.get_economy_manager()
        if economy is not None and hasattr(economy, "get_account_by_name"):
            try:
                account = economy.get_account_by_name(to_java_string(player_name))
                if account is not None:
                    uuid_str = str(account.uuid)
                    name = to_unicode(account.name or player_name)
                    return uuid_str, name
            except Exception:
                pass

        try:
            offline = Bukkit.getOfflinePlayer(to_java_string(player_name))
            if offline is not None:
                try:
                    if hasattr(offline, "hasPlayedBefore") and not offline.hasPlayedBefore():
                        return None, None
                except Exception:
                    pass
                return str(offline.getUniqueId()), to_unicode(offline.getName() or player_name)
        except Exception:
            pass
        return None, None

    def set_reporter(self, anomaly, player_name):
        current_reward = anomaly.get("reward", {})
        if current_reward.get("state") in ("PREPARED", "PAID", "REVIEW_REQUIRED"):
            return False, u"репортёра нельзя менять после начала/завершения reward-операции"
        uuid_str, resolved_name = self.resolve_reporter(player_name)
        if not uuid_str:
            return False, u"игрок не найден"
        old_uuid = anomaly.get("reporter_uuid")
        old_name = anomaly.get("reporter_name")
        anomaly["reporter_uuid"] = uuid_str
        anomaly["reporter_name"] = resolved_name
        reward = anomaly.setdefault("reward", {})
        if reward.get("state") != "PAID":
            reward["state"] = "NOT_READY"
            reward["before_balance"] = None
            reward["expected_balance"] = None
            reward["last_error"] = None
        if not self.storage.save(self.data):
            anomaly["reporter_uuid"] = old_uuid
            anomaly["reporter_name"] = old_name
            return False, u"не удалось сохранить репортёра"
        return True, u"репортёр назначен: {0}".format(resolved_name)

    def remove_anomaly(self, anomaly):
        anomaly_id = anomaly.get("id")
        if anomaly.get("status") != "FIXED":
            log_error(u"Refused to delete anomaly {0}: status={1}; run stabilization or cleanupall first".format(
                anomaly_id, anomaly.get("status")
            ))
            return False
        self.remove_bossbar(anomaly_id)
        snapshot = anomaly
        self.data.get("anomalies", {}).pop(anomaly_id, None)
        if not self.storage.save(self.data):
            self.data.setdefault("anomalies", {})[anomaly_id] = snapshot
            log_error(u"Cannot delete anomaly {0}: journal save failed".format(anomaly_id))
            return False
        log_action(u"Deleted FIXED anomaly record {0}".format(anomaly_id))
        return True

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
            if world is None or Location is None:
                log_error(u"Cleanup cannot teleport to {0}: world or Location unavailable".format(
                    anomaly.get("id")
                ))
                return False
            target = Location(
                world, float(anomaly.get("x")) + 0.5,
                float(anomaly.get("y")) + 2.0,
                float(anomaly.get("z")) + 0.5
            )
            return bool(player.teleport(target))
        except Exception as exc:
            log_error(u"Cleanup teleport failed for {0}".format(anomaly.get("id")), exc)
            return False

    def start_cleanup_all(self, player):
        if self.cleanup_session is not None:
            return False, u"очистка уже выполняется"
        queue = [
            anomaly.get("id") for anomaly in self.non_closed_anomalies()
            if anomaly.get("status") in ("ACTIVE", "STABILIZING")
        ]
        if not queue:
            return False, u"активных аномалий нет"
        queue.sort()
        self.cleanup_session = {
            "player_uuid": str(player.getUniqueId()),
            "queue": queue,
            "current": None
        }
        return True, u"запущена очистка {0} аномалий".format(len(queue))

    def cleanup_all_cycle(self):
        session = self.cleanup_session
        if session is None:
            return
        player = self.online_player_by_uuid(session.get("player_uuid"))
        if player is None:
            log_error(u"Mass anomaly cleanup stopped: initiating player went offline")
            self.cleanup_session = None
            return
        current_id = session.get("current")
        if current_id:
            anomaly = self.get_anomaly(current_id)
            if anomaly is None:
                log_error(u"Mass cleanup cannot find anomaly {0}".format(current_id))
                session["current"] = None
                return
            if anomaly.get("status") == "FIXED":
                session["current"] = None
                return
            # Keep the operator at this anomaly while its loaded chunks are
            # restored.  No chunks are force-loaded by the script.
            if not self.teleport_to_anomaly_for_cleanup(player, anomaly):
                log_error(u"Mass cleanup cannot load anomaly {0} by teleport".format(current_id))
                return
            if anomaly.get("status") == "ACTIVE":
                anomaly["admin_cleanup"] = True
                self.start_stabilization(anomaly)
            return
        if session.get("queue"):
            anomaly_id = session["queue"].pop(0)
            anomaly = self.get_anomaly(anomaly_id)
            if anomaly is None:
                log_error(u"Mass cleanup queue references missing anomaly {0}".format(anomaly_id))
                return
            if anomaly.get("status") == "FIXED":
                return
            session["current"] = anomaly_id
            anomaly["admin_cleanup"] = True
            if not self.teleport_to_anomaly_for_cleanup(player, anomaly):
                log_error(u"Mass cleanup cannot begin for {0}: teleport failed".format(anomaly_id))
                return
            ok, message = self.start_stabilization(anomaly)
            if not ok and anomaly.get("status") != "STABILIZING":
                log_error(u"Mass cleanup cannot start stabilization for {0}: {1}".format(
                    anomaly_id, message
                ))
            return
        self.cleanup_session = None
        log_action(u"Mass anomaly cleanup completed")
        send_message(player, AnomalyConfig.PREFIX + u"&aВсе аномалии восстановлены и закрыты.")

    def admin_help(self, sender):
        lines = [
            u"&f/anomaly start|stop|list",
            u"&f/anomaly autostatus &8(таймер и причины последнего автоспавна)",
            u"&f/anomaly coreprotect &8(состояние резервного журнала)",
            u"&f/anomaly inspect <id>",
            u"&f/anomaly create <город> &8| &fcreatehere",
            u"&f/anomaly stage <id> next",
            u"&f/anomaly reporter <id> <игрок>",
            u"&f/anomaly stabilize <id|nearest>",
            u"&f/anomaly dismiss <latest|nearest|id> &8(срочно и без координат)",
            u"&f/anomaly reward retry <id>",
            u"&f/anomaly remove <id> confirm",
            u"&f/anomaly cleanupall confirm &8(телепорт и безопасное восстановление)",
            u"&f/anomaly save|reload",
            u"&f/anomaly debug [id]"
        ]
        send_message(sender, AnomalyConfig.PREFIX + u"&7Админ-команды:")
        for line in lines:
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
            self.admin_help(sender)
            return True

        if sub == "info":
            if isinstance(sender, Player):
                anomaly = self.anomaly_at_location(sender.getLocation())
                if anomaly is None:
                    send_message(sender, AnomalyConfig.PREFIX + u"&7Вы не находитесь внутри активной аномалии.")
                else:
                    self.inspect(sender, anomaly)
            else:
                send_message(sender, AnomalyConfig.PREFIX + u"&cКоманда доступна игроку.")
            return True

        if sub == "start":
            old = bool(self.data.get("auto_spawn"))
            self.data["auto_spawn"] = True
            if self.storage.save(self.data):
                send_message(sender, AnomalyConfig.PREFIX + u"&aАвтоспавн включён.")
            else:
                self.data["auto_spawn"] = old
                send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось сохранить настройку.")
            return True

        if sub == "stop":
            old = bool(self.data.get("auto_spawn"))
            self.data["auto_spawn"] = False
            if self.storage.save(self.data):
                send_message(sender, AnomalyConfig.PREFIX + u"&eАвтоспавн выключен. Существующие зоны сохранены.")
            else:
                self.data["auto_spawn"] = old
                send_message(sender, AnomalyConfig.PREFIX + u"&cНе удалось сохранить настройку.")
            return True

        if sub == "list":
            self.admin_list(sender)
            return True

        if sub == "autostatus":
            self.auto_status(sender)
            return True

        if sub == "coreprotect":
            self.coreprotect_status(sender)
            return True

        if sub == "inspect":
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly inspect <id>")
                return True
            anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
            else:
                self.inspect(sender, anomaly)
            return True

        if sub == "debug":
            if len(args) >= 2:
                anomaly = self.get_anomaly(args[1])
                if anomaly is None:
                    send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
                else:
                    self.inspect(sender, anomaly)
            else:
                self.debug_all(sender)
            return True

        if sub == "create":
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly create <город>")
                return True
            city = self.find_city_by_name(u" ".join(args[1:]))
            if city is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cГород не найден.")
                return True
            anomaly, reason = self.create_for_city(city)
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cНе создано: " + reason)
            else:
                send_message(
                    sender,
                    AnomalyConfig.PREFIX +
                    u"&aСоздана &f{0}&a около города &f{1}&a. Координаты записаны только в приватный журнал."
                    .format(anomaly.get("id"), city.get("name"))
                )
            return True

        if sub == "createhere":
            if not isinstance(sender, Player):
                send_message(sender, AnomalyConfig.PREFIX + u"&cКоманда доступна только игроку.")
                return True
            anomaly, reason = self.create_here(sender)
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cНе создано: " + reason)
            else:
                send_message(
                    sender,
                    AnomalyConfig.PREFIX +
                    u"&aСоздана &f{0}&a. Координаты записаны только в приватный журнал."
                    .format(anomaly.get("id"))
                )
            return True

        if sub == "stage":
            if len(args) < 3 or args[2].lower() != "next":
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly stage <id> next")
                return True
            anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
                return True
            ok, message = self.manual_next_stage(anomaly)
            send_message(sender, AnomalyConfig.PREFIX + (u"&a" if ok else u"&c") + message)
            return True

        if sub == "reporter":
            if len(args) < 3:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly reporter <id> <игрок>")
                return True
            anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
                return True
            ok, message = self.set_reporter(anomaly, args[2])
            send_message(sender, AnomalyConfig.PREFIX + (u"&a" if ok else u"&c") + message)
            return True

        if sub == "stabilize":
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly stabilize <id|nearest>")
                return True
            anomaly = None
            if args[1].lower() == "nearest":
                if not isinstance(sender, Player):
                    send_message(sender, AnomalyConfig.PREFIX + u"&cnearest доступен только игроку.")
                    return True
                anomaly = self.nearest_anomaly(sender.getLocation(), 100.0)
            else:
                anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАктивная аномалия не найдена.")
                return True
            ok, message = self.start_stabilization(anomaly)
            send_message(sender, AnomalyConfig.PREFIX + (u"&a" if ok else u"&c") + message)
            return True

        if sub == "dismiss":
            if len(args) < 2:
                send_message(sender, AnomalyConfig.PREFIX +
                             u"&c/anomaly dismiss <latest|nearest|id>")
                return True
            target = args[1].lower()
            anomaly = None
            if target == "latest":
                anomaly = self.latest_active_anomaly()
            elif target == "nearest":
                if not isinstance(sender, Player):
                    send_message(sender, AnomalyConfig.PREFIX +
                                 u"&cnearest доступен только игроку; используй latest или ID.")
                    return True
                anomaly = self.nearest_anomaly(sender.getLocation(), 250.0)
            else:
                anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАктивная аномалия не найдена.")
                return True
            ok, message = self.start_quiet_removal(anomaly)
            send_message(sender, AnomalyConfig.PREFIX +
                         (u"&a" if ok else u"&c") + message)
            return True

        if sub == "reward":
            if len(args) < 3 or args[1].lower() != "retry":
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly reward retry <id>")
                return True
            anomaly = self.get_anomaly(args[2])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
                return True
            if anomaly.get("status") != "FIXED":
                send_message(sender, AnomalyConfig.PREFIX + u"&cНаграда доступна только после FIXED.")
                return True
            ok, message = self.issue_reward(anomaly)
            send_message(sender, AnomalyConfig.PREFIX + (u"&a" if ok else u"&c") + message)
            return True

        if sub == "remove":
            if len(args) < 3 or args[2].lower() != "confirm":
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly remove <id> confirm")
                return True
            anomaly = self.get_anomaly(args[1])
            if anomaly is None:
                send_message(sender, AnomalyConfig.PREFIX + u"&cАномалия не найдена.")
                return True
            if self.remove_anomaly(anomaly):
                send_message(
                    sender,
                    AnomalyConfig.PREFIX +
                    u"&aЗапись закрытой аномалии удалена."
                )
            else:
                send_message(sender, AnomalyConfig.PREFIX +
                             u"&cУдаление отклонено или не сохранено. Сначала восстанови её через stabilize/cleanupall; подробности в anomaly-errors.log.")
            return True

        if sub == "cleanupall":
            if len(args) < 2 or args[1].lower() != "confirm":
                send_message(sender, AnomalyConfig.PREFIX + u"&c/anomaly cleanupall confirm")
                return True
            if not isinstance(sender, Player):
                send_message(sender, AnomalyConfig.PREFIX + u"&cКоманда доступна только игроку: он загружает чанки телепортацией.")
                return True
            ok, message = self.start_cleanup_all(sender)
            send_message(sender, AnomalyConfig.PREFIX + (u"&a" if ok else u"&c") + message)
            return True

        if sub == "save":
            if self.storage.save(self.data):
                self.dirty = False
                send_message(sender, AnomalyConfig.PREFIX + u"&aДанные сохранены.")
            else:
                send_message(sender, AnomalyConfig.PREFIX + u"&cОшибка сохранения.")
            return True

        if sub == "reload":
            loaded = self.storage.load()
            if not self.storage.loaded_ok:
                send_message(sender, AnomalyConfig.PREFIX + u"&cПерезагрузка отклонена: данные не прочитаны.")
                return True
            self.remove_all_bossbars()
            self.data = loaded
            self.normalize_runtime_data()
            self.reconcile_planned_records()
            self.resume_bossbars()
            self.recover_prepared_rewards()
            send_message(sender, AnomalyConfig.PREFIX + u"&aДанные перечитаны.")
            return True

        self.admin_help(sender)
        return True

    def tab_complete(self, sender, args):
        if not self.is_admin(sender):
            return []
        args = [to_unicode(arg) for arg in args]
        if len(args) <= 1:
            options = [
                "start", "stop", "list", "autostatus", "coreprotect", "inspect", "create", "createhere",
                "stage", "reporter", "stabilize", "dismiss", "reward", "remove", "cleanupall",
                "save", "reload", "debug"
            ]
            prefix = args[0].lower() if args else ""
            return [item for item in options if item.startswith(prefix)]
        sub = args[0].lower()
        prefix = args[-1].upper()
        if sub in ("inspect", "stage", "reporter", "remove", "debug"):
            if len(args) == 2:
                return [
                    anomaly.get("id") for anomaly in self.non_closed_anomalies()
                    if to_unicode(anomaly.get("id")).upper().startswith(prefix)
                ]
        if sub == "stabilize" and len(args) == 2:
            options = ["nearest"] + [
                anomaly.get("id") for anomaly in self.active_anomalies()
            ]
            low = args[-1].lower()
            return [
                item for item in options
                if to_unicode(item).lower().startswith(low)
            ]
        if sub == "dismiss" and len(args) == 2:
            options = ["latest", "nearest"] + [
                anomaly.get("id") for anomaly in self.active_anomalies()
            ]
            low = args[-1].lower()
            return [item for item in options if to_unicode(item).lower().startswith(low)]
        if sub == "stage" and len(args) == 3:
            return ["next"] if "next".startswith(args[-1].lower()) else []
        if sub == "reward":
            if len(args) == 2:
                return ["retry"] if "retry".startswith(args[-1].lower()) else []
            if len(args) == 3 and args[1].lower() == "retry":
                return [
                    anomaly.get("id")
                    for anomaly in self.data.get("anomalies", {}).values()
                    if to_unicode(anomaly.get("id")).upper().startswith(prefix)
                ]
        if sub == "remove" and len(args) == 3:
            return ["confirm"] if "confirm".startswith(args[-1].lower()) else []
        if sub == "cleanupall" and len(args) == 2:
            return ["confirm"] if "confirm".startswith(args[-1].lower()) else []
        if sub == "reporter" and len(args) == 3:
            try:
                names = [to_unicode(p.getName()) for p in Bukkit.getOnlinePlayers()]
                low = args[-1].lower()
                return [name for name in names if name.lower().startswith(low)]
            except Exception:
                return []
        if sub == "create" and len(args) >= 2:
            low = u" ".join(args[1:]).lower()
            names = [to_unicode(city.get("name")) for city in self.get_city_records()]
            return [name for name in names if name.lower().startswith(low)]
        return []


class AnomalyCommand(Command, TabCompleter):
    def __init__(self, manager):
        aliases = build_java_list([])
        Command.__init__(
            self, "anomaly",
            "Server anomaly administration",
            "/anomaly",
            aliases
        )
        self.manager = manager
        try:
            self.setPermission(to_java_string(AnomalyConfig.ADMIN_PERMISSION))
        except Exception:
            pass

    def execute(self, sender, command_label, args):
        try:
            return bool(self.manager.handle_command(sender, list(args)))
        except Exception as exc:
            log_error(u"/anomaly execution error", exc)
            if self.manager.is_admin(sender):
                send_message(
                    sender,
                    AnomalyConfig.PREFIX +
                    u"&cВнутренняя ошибка. Подробности в консоли."
                )
            else:
                self.manager.send_unknown_command(sender)
            return True

    def tabComplete(self, sender, alias, args, location=None):
        try:
            return build_java_list(
                self.manager.tab_complete(sender, list(args))
            )
        except Exception as exc:
            log_error(u"Tab completion error", exc)
            return build_java_list([])


manager = None


def on_enable():
    global manager
    if JAVA_AVAILABLE and System is not None:
        try:
            old = System.getProperties().get(AnomalyConfig.MANAGER_PROPERTY)
            if (
                    old is not None and
                    old is not manager and
                    hasattr(old, "shutdown_from_replacement")
            ):
                old.shutdown_from_replacement()
        except Exception as exc:
            log_error(u"Failed to stop previous anomaly manager during reload", exc)
    try:
        manager = AnomalyManager()
        manager.start()
    except Exception as exc:
        log_error(u"Fatal anomaly startup error", exc)
        manager = None
        raise


def on_disable():
    global manager
    if manager is not None:
        try:
            manager.stop()
        except Exception as exc:
            log_error(u"Shutdown error", exc)
    manager = None


def stop(script=None):
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()
