from pathlib import Path

ECONOMY = Path("economy.py")
COMPANIES = Path("companies.py")
HIDDEN = Path("hidden.py")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError("%s: expected exactly 1 match, got %d" % (label, count))
    return text.replace(old, new, 1)


eco = ECONOMY.read_text(encoding="utf-8")
companies = COMPANIES.read_text(encoding="utf-8")
hidden = HIDDEN.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# hidden.py: publish the *active current-session* hidden UUID set through the
# JVM. The persistent 'armed for next login' flag is deliberately not used,
# because a visible admin may arm hidden mode without being hidden yet.
# ---------------------------------------------------------------------------
hidden = replace_once(
    hidden,
    'from java.lang import String as JavaString, StringBuilder\n',
    'from java.lang import String as JavaString, StringBuilder, System\n',
    "hidden System import",
)
hidden = replace_once(
    hidden,
    '    StringBuilder = None\n\n\n# -----------------------------------------------------------------------------\n# КОНФИГУРАЦИЯ: КОМУ ДОСТУПЕН СКРЫТЫЙ РЕЖИМ\n',
    '    StringBuilder = None\n    System = None\n\n\n# -----------------------------------------------------------------------------\n# КОНФИГУРАЦИЯ: КОМУ ДОСТУПЕН СКРЫТЫЙ РЕЖИМ\n',
    "hidden System fallback",
)
hidden = replace_once(
    hidden,
    'VERSION = u"1.0.0"\nPREFIX = u"&8[&7Hidden&8]&r "\n',
    'VERSION = u"1.0.1"\nPREFIX = u"&8[&7Hidden&8]&r "\nHIDDEN_SESSIONS_PROPERTY = u"SmartY_Hidden_ActiveSessions"\n',
    "hidden version/property",
)
hidden = replace_once(
    hidden,
    'active_hidden_sessions = set()\n\n\n# -----------------------------------------------------------------------------\n# ВИЗУАЛЬНОЕ СКРЫТИЕ / ПОКАЗ ИГРОКА (Tab + мир одним вызовом hidePlayer)\n',
    '''active_hidden_sessions = set()\n\n\ndef publish_active_hidden_sessions():\n    """Expose the live hidden-session set to sibling PySpigot scripts.\n\n    This is intentionally the in-memory active set, not hidden_mode.json's\n    "armed for next login" value. Storing the same mutable set object means\n    joins/reveals/quits are visible immediately without cross-script imports.\n    """\n    if not JAVA_STRING_AVAILABLE or System is None:\n        return\n    try:\n        System.getProperties().put(HIDDEN_SESSIONS_PROPERTY, active_hidden_sessions)\n    except Exception as e:\n        log_error(u"Failed to publish active hidden sessions: {0}".format(e))\n\n\n# -----------------------------------------------------------------------------\n# ВИЗУАЛЬНОЕ СКРЫТИЕ / ПОКАЗ ИГРОКА (Tab + мир одним вызовом hidePlayer)\n''',
    "hidden shared state",
)
hidden = replace_once(
    hidden,
    '    storage.load()\n    register_listeners()\n',
    '    storage.load()\n    publish_active_hidden_sessions()\n    register_listeners()\n',
    "hidden publish on enable",
)

# ---------------------------------------------------------------------------
# economy.py: hidden admins are completely outside AFK detection while they
# are actually hidden in the current session. Their payday activity clock also
# continues, matching the requirement that AFK simply does not apply to them.
# ---------------------------------------------------------------------------
eco = replace_once(
    eco,
    '    VERSION = u"3.8.0"\n',
    '    VERSION = u"3.8.1"\n',
    "economy version",
)
eco = replace_once(
    eco,
    '''def is_player_afk(player):\n    if player is None:\n        return False\n    try:\n        return bool(afk_players.get(str(player.getUniqueId()), False))\n    except Exception:\n        return False\n''',
    '''HIDDEN_SESSIONS_PROPERTY = u"SmartY_Hidden_ActiveSessions"\n\n\ndef is_hidden_admin(player):\n    """True only while /hidden is active in this exact online session."""\n    if player is None or not JAVA_STRING_AVAILABLE or System is None:\n        return False\n    try:\n        sessions = System.getProperties().get(HIDDEN_SESSIONS_PROPERTY)\n        if sessions is None:\n            return False\n        return str(player.getUniqueId()) in sessions\n    except Exception:\n        return False\n\n\ndef is_player_afk(player):\n    if player is None:\n        return False\n    try:\n        if is_hidden_admin(player):\n            return False\n        return bool(afk_players.get(str(player.getUniqueId()), False))\n    except Exception:\n        return False\n''',
    "hidden AFK predicate",
)
eco = replace_once(
    eco,
    '''        if not uuid_str:\n            return False\n        current = bool(afk_players.get(uuid_str, False))\n        value = bool(value)\n''',
    '''        if not uuid_str:\n            return False\n        value = bool(value)\n        if value and is_hidden_admin(player):\n            # Hidden staff never enters AFK, neither automatically nor via /afk.\n            afk_players.pop(uuid_str, None)\n            last_activity[uuid_str] = time.time()\n            last_location_keys[uuid_str] = get_location_key(player.getLocation())\n            return False\n        current = bool(afk_players.get(uuid_str, False))\n''',
    "block hidden AFK state",
)
eco = replace_once(
    eco,
    '''                if not uuid_str:\n                    continue\n                if uuid_str not in last_activity:\n                    last_activity[uuid_str] = now\n''',
    '''                if not uuid_str:\n                    continue\n                if is_hidden_admin(player):\n                    # Keep the activity clock fresh as well: payday must not be\n                    # frozen by the secondary inactivity guard while hidden.\n                    afk_players.pop(uuid_str, None)\n                    last_activity[uuid_str] = now\n                    last_location_keys[uuid_str] = get_location_key(player.getLocation())\n                    continue\n                if uuid_str not in last_activity:\n                    last_activity[uuid_str] = now\n''',
    "AFK runnable hidden exemption",
)
eco = replace_once(
    eco,
    '''    la = last_activity.get(uuid_str)\n    if la is None:\n        return False\n''',
    '''    hidden_player = get_online_player_by_uuid(uuid_str)\n    if hidden_player is not None and is_hidden_admin(hidden_player):\n        return True\n    la = last_activity.get(uuid_str)\n    if la is None:\n        return False\n''',
    "payday hidden activity exemption",
)

# ---------------------------------------------------------------------------
# economy.py: Companies already uses an idempotent batch API, but the current
# EconomyManager is missing it. Persist operation IDs in the SAME atomic JSON
# write as the credited balances so a crash cannot duplicate a dividend batch.
# ---------------------------------------------------------------------------
eco = replace_once(
    eco,
    '''        self.payday_afk_threshold = float(EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)\n        self.sleep_defaults = {}\n        self._database_loaded = self.load_database()\n''',
    '''        self.payday_afk_threshold = float(EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)\n        self.sleep_defaults = {}\n        self.processed_batch_operations = {}\n        self._database_loaded = self.load_database()\n''',
    "batch state init",
)
eco = replace_once(
    eco,
    '''        loaded_accounts = {}\n        loaded_names = {}\n        loaded_sleep_defaults = {}\n        try:\n''',
    '''        loaded_accounts = {}\n        loaded_names = {}\n        loaded_sleep_defaults = {}\n        loaded_processed_batch_operations = {}\n        try:\n''',
    "batch state load locals",
)
eco = replace_once(
    eco,
    '''            for world_name, percent in (data.get("sleep_defaults", {}) or {}).items():\n                loaded_sleep_defaults[to_unicode(world_name)] = max(1, min(100, int(percent)))\n        except Exception as exc:\n''',
    '''            for world_name, percent in (data.get("sleep_defaults", {}) or {}).items():\n                loaded_sleep_defaults[to_unicode(world_name)] = max(1, min(100, int(percent)))\n            raw_batch_operations = data.get("processed_batch_operations", {}) or {}\n            if isinstance(raw_batch_operations, dict):\n                for operation_id, processed_at in raw_batch_operations.items():\n                    try:\n                        operation_key = to_unicode(operation_id).strip()\n                        if operation_key:\n                            loaded_processed_batch_operations[operation_key] = int(processed_at)\n                    except Exception:\n                        pass\n        except Exception as exc:\n''',
    "batch state load parsing",
)
eco = replace_once(
    eco,
    '''            self.payday_afk_threshold = safe_amount(data.get("payday_afk_threshold", EconomyConfig.DEFAULT_PAYDAY_INACTIVITY), default=EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)\n            self.sleep_defaults = loaded_sleep_defaults\n        finally:\n''',
    '''            self.payday_afk_threshold = safe_amount(data.get("payday_afk_threshold", EconomyConfig.DEFAULT_PAYDAY_INACTIVITY), default=EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)\n            self.sleep_defaults = loaded_sleep_defaults\n            self.processed_batch_operations = loaded_processed_batch_operations\n        finally:\n''',
    "batch state assign",
)
eco = replace_once(
    eco,
    '''            "schema_version": 2,\n            "saved_at": int(time.time()),\n''',
    '''            "schema_version": 3,\n            "saved_at": int(time.time()),\n''',
    "economy schema version",
)
eco = replace_once(
    eco,
    '''            "sleep_defaults": {str(wn): int(pct) for wn, pct in self.sleep_defaults.items()},\n            "accounts": {uuid_str: acc.to_dict() for uuid_str, acc in self.accounts.items()}\n''',
    '''            "sleep_defaults": {str(wn): int(pct) for wn, pct in self.sleep_defaults.items()},\n            "processed_batch_operations": dict(self.processed_batch_operations),\n            "accounts": {uuid_str: acc.to_dict() for uuid_str, acc in self.accounts.items()}\n''',
    "persist batch operation IDs",
)
eco = replace_once(
    eco,
    '''    def deposit(self, uuid_str, amount, name=None):\n        success, balance = self.deposit_checked(uuid_str, amount, name)\n        return balance\n\n    def withdraw(self, uuid_str, amount):\n''',
    '''    def deposit_batch_once(self, operation_id, payouts):\n        """Atomically credit a dividend batch exactly once.\n\n        Returns (success, already_processed). Operation IDs are persisted in\n        economy.json in the same atomic save as balances, so Companies may\n        safely retry a pending dividend after reload/crash without duplicating it.\n        """\n        manager = self.current_manager()\n        if manager is not None and manager is not self:\n            if hasattr(manager, "deposit_batch_once"):\n                return manager.deposit_batch_once(operation_id, payouts)\n            return False, False\n        if manager is None:\n            return False, False\n\n        operation_key = to_unicode(operation_id).strip() if operation_id is not None else u""\n        if not operation_key or not isinstance(payouts, (list, tuple)) or not payouts:\n            return False, False\n\n        normalized = []\n        for item in payouts:\n            try:\n                uuid_key = str(item[0]).strip()\n                amount = safe_amount(item[1], default=None)\n                supplied_name = item[2] if len(item) >= 3 else None\n            except Exception:\n                return False, False\n            if not uuid_key or amount is None or amount <= 0.0:\n                return False, False\n            normalized.append((uuid_key, float(amount), supplied_name))\n\n        touched = set()\n        self._lock.acquire()\n        try:\n            if operation_key in self.processed_batch_operations:\n                return True, True\n\n            old_name_to_uuid = dict(self.name_to_uuid)\n            snapshots = {}\n            created_uuids = set()\n\n            def rollback():\n                self.processed_batch_operations.pop(operation_key, None)\n                self.name_to_uuid = old_name_to_uuid\n                for key in created_uuids:\n                    self.accounts.pop(key, None)\n                for key, values in snapshots.items():\n                    if key in created_uuids:\n                        continue\n                    acc = self.accounts.get(key)\n                    if acc is not None:\n                        acc.balance, acc.last_seen = values\n\n            for uuid_key, amount, supplied_name in normalized:\n                credit_name = self._name_for_new_credit_account(uuid_key, supplied_name)\n                acc, created = self._get_or_create_in_memory(uuid_key, credit_name, update_name=False)\n                if uuid_key not in snapshots:\n                    snapshots[uuid_key] = (acc.balance, acc.last_seen)\n                if created:\n                    created_uuids.add(uuid_key)\n                new_balance = acc.balance + amount\n                if new_balance > EconomyConfig.MAX_BALANCE:\n                    rollback()\n                    return False, False\n                acc.balance = round(new_balance, 2)\n                touched.add(uuid_key)\n\n            self.processed_batch_operations[operation_key] = int(time.time())\n            if not self.save_database():\n                rollback()\n                return False, False\n        finally:\n            self._lock.release()\n\n        for uuid_key in touched:\n            update_online_player_hud(uuid_key)\n        invalidate_baltop_cache()\n        return True, False\n\n    def deposit(self, uuid_str, amount, name=None):\n        success, balance = self.deposit_checked(uuid_str, amount, name)\n        return balance\n\n    def withdraw(self, uuid_str, amount):\n''',
    "idempotent batch deposit",
)

# ---------------------------------------------------------------------------
# companies.py: production cadence is exactly three hours. The scheduler
# version is tied to the interval, so existing companies are migrated to the
# new cadence on the next script load. Payout recipients are already selected
# solely from share ownership (no AFK/online filter).
# ---------------------------------------------------------------------------
companies = replace_once(
    companies,
    '    VERSION = u"1.3.0"\n',
    '    VERSION = u"1.3.1"\n',
    "companies version",
)
companies = replace_once(
    companies,
    '''    # Test mode: switch this to 86400 for one payout per day.\n    DIVIDEND_INTERVAL_SECONDS = 300\n''',
    '''    # Production: dividend cycle is exactly three hours.\n    DIVIDEND_INTERVAL_SECONDS = 3 * 60 * 60\n''',
    "three-hour dividend interval",
)
companies = replace_once(
    companies,
    'каждые 5 минут (тестовый режим).',
    'каждые 3 часа.',
    "production dividend message",
)

ECONOMY.write_text(eco, encoding="utf-8")
COMPANIES.write_text(companies, encoding="utf-8")
HIDDEN.write_text(hidden, encoding="utf-8")
print("AFK/hidden and production dividend fix applied successfully")
