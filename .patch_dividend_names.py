from pathlib import Path

ECONOMY = Path("economy.py")
COMPANIES = Path("companies.py")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError("%s: expected exactly 1 match, got %d" % (label, count))
    return text.replace(old, new, 1)


eco = ECONOMY.read_text(encoding="utf-8")
companies = COMPANIES.read_text(encoding="utf-8")

# 1) Existing accounts must not be renamed by generic balance mutations.
eco = replace_once(
    eco,
    '''    def _get_or_create_in_memory(self, uuid_str, name):\n        uuid_key = str(uuid_str)\n        unicode_name = to_unicode(name)\n        acc = self.accounts.get(uuid_key)\n        created = acc is None\n        if created:\n            acc = Account(uuid_key, unicode_name)\n            self.accounts[uuid_key] = acc\n        else:\n            acc.update_last_seen(unicode_name)\n        if unicode_name and unicode_name != u"Unknown":\n            self.name_to_uuid[unicode_name.lower()] = uuid_key\n        return acc, created\n''',
    '''    def _get_or_create_in_memory(self, uuid_str, name, update_name=True):\n        uuid_key = str(uuid_str)\n        unicode_name = to_unicode(name)\n        acc = self.accounts.get(uuid_key)\n        created = acc is None\n        if created:\n            acc = Account(uuid_key, unicode_name)\n            self.accounts[uuid_key] = acc\n        else:\n            # Balance mutations (dividends/refunds/etc.) are allowed to touch\n            # money and last_seen, but must never rename an existing UUID.\n            # Only trusted identity paths such as PlayerJoin/get_or_create_account\n            # may update the stored player name.\n            if update_name:\n                old_name = to_unicode(acc.name).strip() if acc.name else u""\n                acc.update_last_seen(unicode_name)\n                if old_name and old_name.lower() != unicode_name.lower():\n                    mapped = self.name_to_uuid.get(old_name.lower())\n                    if mapped == uuid_key:\n                        self.name_to_uuid.pop(old_name.lower(), None)\n            else:\n                acc.update_last_seen()\n        if unicode_name and unicode_name != u"Unknown" and (created or update_name):\n            self.name_to_uuid[unicode_name.lower()] = uuid_key\n        return acc, created\n\n    @staticmethod\n    def _is_placeholder_account_name(name):\n        value = to_unicode(name).strip().lower() if name is not None else u""\n        return value in (u"", u"unknown", u"investor", u"{minecraft_username}")\n\n    def _offline_name_for_uuid(self, uuid_str):\n        if not BUKKIT_AVAILABLE or JavaUUID is None:\n            return None\n        try:\n            offline = Bukkit.getOfflinePlayer(JavaUUID.fromString(str(uuid_str)))\n            if offline is None:\n                return None\n            name = offline.getName()\n            if name and not self._is_placeholder_account_name(name):\n                return to_unicode(name)\n        except Exception:\n            pass\n        return None\n\n    def _name_for_new_credit_account(self, uuid_str, supplied_name=None):\n        # UUID is authoritative. Prefer Bukkit's UUID -> last known Minecraft\n        # name mapping; a supplied label is only a fallback for a brand-new\n        # account and is never used to rename an existing account.\n        resolved = self._offline_name_for_uuid(uuid_str)\n        if resolved:\n            return resolved\n        if supplied_name is not None and not self._is_placeholder_account_name(supplied_name):\n            return to_unicode(supplied_name)\n        return u"Unknown"\n\n    def repair_corrupted_account_names(self):\n        # One-shot/idempotent repair for the old companies.py dividend bug,\n        # which stored literal labels such as "Investor" as player names.\n        repaired = 0\n        self._lock.acquire()\n        try:\n            for uuid_key, acc in self.accounts.items():\n                if not self._is_placeholder_account_name(acc.name):\n                    continue\n                resolved = self._offline_name_for_uuid(uuid_key)\n                if not resolved:\n                    continue\n                acc.name = resolved\n                acc.last_seen = int(time.time())\n                repaired += 1\n\n            if repaired:\n                rebuilt = {}\n                for uuid_key, acc in self.accounts.items():\n                    name = to_unicode(acc.name).strip() if acc.name else u""\n                    if name and not self._is_placeholder_account_name(name):\n                        rebuilt[name.lower()] = str(uuid_key)\n                self.name_to_uuid = rebuilt\n                invalidate_baltop_cache()\n        finally:\n            self._lock.release()\n        return repaired\n''',
    "protect account names",
)

# 2) Deposits and admin balance sets do not rename an existing UUID.
eco = replace_once(
    eco,
    '''        uuid_key = str(uuid_str)\n        self._lock.acquire()\n        try:\n            acc, created = self._get_or_create_in_memory(uuid_key, name if name else u"Unknown")\n            old_balance = acc.balance\n            new_balance = old_balance + safe\n''',
    '''        uuid_key = str(uuid_str)\n        self._lock.acquire()\n        try:\n            credit_name = self._name_for_new_credit_account(uuid_key, name)\n            acc, created = self._get_or_create_in_memory(uuid_key, credit_name, update_name=False)\n            old_balance = acc.balance\n            new_balance = old_balance + safe\n''',
    "safe deposit identity",
)

eco = replace_once(
    eco,
    '''        from_key, to_key = str(from_uuid), str(to_uuid)\n        self._lock.acquire()\n        try:\n            source = self.accounts.get(from_key)\n            if source is None or source.balance < safe:\n                return False, self.get_balance(from_key), self.get_balance(to_key)\n            target, created = self._get_or_create_in_memory(to_key, to_name if to_name else u"Unknown")\n''',
    '''        from_key, to_key = str(from_uuid), str(to_uuid)\n        self._lock.acquire()\n        try:\n            source = self.accounts.get(from_key)\n            if source is None or source.balance < safe:\n                return False, self.get_balance(from_key), self.get_balance(to_key)\n            target_name = self._name_for_new_credit_account(to_key, to_name)\n            target, created = self._get_or_create_in_memory(to_key, target_name, update_name=False)\n''',
    "safe transfer identity",
)

# set_balance_checked has the same dangerous pattern. Replace its remaining instance.
eco = replace_once(
    eco,
    '''        uuid_key = str(uuid_str)\n        self._lock.acquire()\n        try:\n            acc, created = self._get_or_create_in_memory(uuid_key, name if name else u"Unknown")\n            old_balance = acc.balance\n            acc.balance = round(safe, 2)\n''',
    '''        uuid_key = str(uuid_str)\n        self._lock.acquire()\n        try:\n            account_name = self._name_for_new_credit_account(uuid_key, name)\n            acc, created = self._get_or_create_in_memory(uuid_key, account_name, update_name=False)\n            old_balance = acc.balance\n            acc.balance = round(safe, 2)\n''',
    "safe set-balance identity",
)

# 3) Repair bad legacy names as soon as the authoritative manager is active.
eco = replace_once(
    eco,
    '''        economy._active = True\n        # Creates the first file when the database does not exist and upgrades\n        # the on-disk format only after this manager becomes authoritative.\n        if not economy.save_database():\n''',
    '''        economy._active = True\n        repaired_names = economy.repair_corrupted_account_names()\n        if repaired_names:\n            log_info(u"Repaired {0} corrupted economy account name(s) from Bukkit UUID data.".format(repaired_names))\n        # Creates the first file when the database does not exist and upgrades\n        # the on-disk format only after this manager becomes authoritative.\n        if not economy.save_database():\n''',
    "startup repair",
)

# 4) companies.py must not use the human-readable role label as a player name.
companies = replace_once(
    companies,
    '''            for uuid_str, payout in payouts:\n                deposited, balance = self.economy.deposit_checked(uuid_str, payout, u"Investor")\n''',
    '''            for uuid_str, payout in payouts:\n                # The UUID identifies the shareholder. "Investor" used to be\n                # passed as a fake player name here and permanently polluted\n                # economy.json / baltop. Never send a role label as identity.\n                deposited, balance = self.economy.deposit_checked(uuid_str, payout, None)\n''',
    "dividend fake name",
)

ECONOMY.write_text(eco, encoding="utf-8")
COMPANIES.write_text(companies, encoding="utf-8")
print("Dividend account-name fix applied successfully")
