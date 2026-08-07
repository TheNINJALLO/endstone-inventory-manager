"""
Database utility for storing player inventory and ender chest data.
Uses NBT JSON blob storage for full-fidelity item serialization.
"""

import sqlite3
import threading
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from endstone import Player
from endstone.inventory import ItemStack

# Endstone 0.11 exports NBT tag classes from endstone.nbt.
from endstone.nbt import (
    CompoundTag, ListTag, ByteTag, ShortTag, IntTag, LongTag,
    FloatTag, DoubleTag, StringTag, ByteArrayTag, IntArrayTag,
)


# Database folder path
DB_FOLDER = Path("plugins/inventory_manager_data")
DB_FOLDER.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# NBT ↔ dict serialization helpers
# ---------------------------------------------------------------------------

def nbt_to_dict(tag):
    """Recursively convert any NBT Tag to a JSON-serializable Python object."""
    if isinstance(tag, CompoundTag):
        return {
            "_type": "compound",
            "value": {k: nbt_to_dict(v) for k, v in tag.items()}
        }
    elif isinstance(tag, ListTag):
        return {
            "_type": "list",
            "value": [nbt_to_dict(tag[i]) for i in range(tag.size())]
        }
    elif isinstance(tag, ByteTag):
        return {"_type": "byte", "value": tag.value}
    elif isinstance(tag, ShortTag):
        return {"_type": "short", "value": tag.value}
    elif isinstance(tag, IntTag):
        return {"_type": "int", "value": tag.value}
    elif isinstance(tag, LongTag):
        return {"_type": "long", "value": tag.value}
    elif isinstance(tag, FloatTag):
        return {"_type": "float", "value": tag.value}
    elif isinstance(tag, DoubleTag):
        return {"_type": "double", "value": tag.value}
    elif isinstance(tag, StringTag):
        return {"_type": "string", "value": tag.value}
    elif isinstance(tag, ByteArrayTag):
        return {"_type": "byte_array", "value": list(tag)}
    elif isinstance(tag, IntArrayTag):
        return {"_type": "int_array", "value": list(tag)}
    else:
        return {"_type": "unknown", "value": str(tag)}


def dict_to_nbt(data):
    """Recursively rebuild an NBT Tag from a dict produced by nbt_to_dict."""
    t = data.get("_type", "unknown")
    v = data.get("value")

    if t == "compound":
        tag = CompoundTag()
        for key, child in v.items():
            tag[key] = dict_to_nbt(child)
        return tag
    elif t == "list":
        list_tag = ListTag()
        for child in v:
            list_tag.append(dict_to_nbt(child))
        return list_tag
    elif t == "byte":
        return ByteTag(int(v))
    elif t == "short":
        return ShortTag(int(v))
    elif t == "int":
        return IntTag(int(v))
    elif t == "long":
        return LongTag(int(v))
    elif t == "float":
        return FloatTag(float(v))
    elif t == "double":
        return DoubleTag(float(v))
    elif t == "string":
        return StringTag(str(v))
    elif t == "byte_array":
        return ByteArrayTag(v)
    elif t == "int_array":
        return IntArrayTag(v)
    else:
        return StringTag(str(v))


# ---------------------------------------------------------------------------
# Item serialization / deserialization
# ---------------------------------------------------------------------------

def serialize_item(item, slot_num: int, slot_type: str = "slot") -> dict:
    """Serialize an ItemStack (or None/air) to a JSON-friendly dict."""
    if item is None or str(item.type) == "minecraft:air":
        return {"slot": slot_num, "slot_type": slot_type, "type": None}

    result = {
        "slot": slot_num,
        "slot_type": slot_type,
        "type": str(item.type),
        "amount": item.amount,
    }

    # Save the full NBT compound tag — this preserves everything:
    # enchantments, lore, display name, shulker contents, damage, etc.
    try:
        nbt_tag = item.nbt
        if nbt_tag is not None:
            result["nbt"] = nbt_to_dict(nbt_tag)
    except Exception:
        pass

    return result


def deserialize_item(item_data: dict) -> Optional[ItemStack]:
    """Recreate an ItemStack from a dict produced by serialize_item."""
    if item_data.get("type") is None:
        return None

    item_type = item_data["type"]
    amount = item_data.get("amount", 1)

    item = ItemStack(item_type, amount)

    # Restore the full NBT compound tag
    nbt_data = item_data.get("nbt")
    if nbt_data is not None:
        try:
            tag = dict_to_nbt(nbt_data)
            if isinstance(tag, CompoundTag):
                item.nbt = tag
        except Exception:
            pass

    return item


def get_item_display_info(item_data: dict) -> dict:
    """Extract display information from a serialized item dict for UI display."""
    if item_data.get("type") is None:
        return {"name": "", "amount": 0, "type": "minecraft:air"}

    item_type = item_data.get("type", "minecraft:air")
    amount = item_data.get("amount", 1)
    slot = item_data.get("slot", 0)
    slot_type = item_data.get("slot_type", "slot")

    # Default display name from type
    display_name = item_type.replace("minecraft:", "").replace("_", " ").title()

    # Extract display info from NBT if available
    lore = []
    enchants = {}
    damage = 0

    nbt = item_data.get("nbt")
    if nbt and isinstance(nbt, dict) and nbt.get("_type") == "compound":
        nbt_value = nbt.get("value", {})

        # Extract display name and lore
        display_tag = nbt_value.get("display")
        if display_tag and isinstance(display_tag, dict) and display_tag.get("_type") == "compound":
            display_val = display_tag.get("value", {})

            name_tag = display_val.get("Name")
            if name_tag and isinstance(name_tag, dict):
                display_name = name_tag.get("value", display_name)

            lore_tag = display_val.get("Lore")
            if lore_tag and isinstance(lore_tag, dict) and lore_tag.get("_type") == "list":
                lore = [entry.get("value", "") for entry in lore_tag.get("value", [])
                        if isinstance(entry, dict)]

        # Extract enchantments
        ench_tag = nbt_value.get("ench")
        if ench_tag and isinstance(ench_tag, dict) and ench_tag.get("_type") == "list":
            for ench_entry in ench_tag.get("value", []):
                if isinstance(ench_entry, dict) and ench_entry.get("_type") == "compound":
                    ench_val = ench_entry.get("value", {})
                    ench_id = ench_val.get("id", {}).get("value", 0) if isinstance(ench_val.get("id"), dict) else 0
                    ench_lvl = ench_val.get("lvl", {}).get("value", 1) if isinstance(ench_val.get("lvl"), dict) else 1
                    enchants[f"Enchantment {ench_id}"] = ench_lvl

        # Extract damage
        damage_tag = nbt_value.get("Damage")
        if damage_tag and isinstance(damage_tag, dict):
            damage = damage_tag.get("value", 0)

    return {
        "name": display_name,
        "amount": amount,
        "type": item_type,
        "slot": slot,
        "slot_type": slot_type,
        "damage": damage,
        "lore": lore,
        "enchants": enchants,
        "display_name": display_name,
    }


def extract_shulker_contents(item_data: dict) -> list:
    """Extract the contents of a shulker box from its serialized NBT data.
    Returns a list of dicts with 'name' and 'count' for each contained item."""
    contents = []

    nbt = item_data.get("nbt")
    if not nbt or not isinstance(nbt, dict) or nbt.get("_type") != "compound":
        return contents

    nbt_value = nbt.get("value", {})

    # Shulker box contents are stored in the "Items" tag
    items_tag = nbt_value.get("Items")
    if not items_tag or not isinstance(items_tag, dict) or items_tag.get("_type") != "list":
        return contents

    for item_entry in items_tag.get("value", []):
        if not isinstance(item_entry, dict) or item_entry.get("_type") != "compound":
            continue

        entry_val = item_entry.get("value", {})

        # Get item Name
        name_tag = entry_val.get("Name")
        item_name = ""
        if name_tag and isinstance(name_tag, dict):
            item_name = name_tag.get("value", "unknown")
        if not item_name:
            continue

        # Clean up name for display
        clean_name = item_name.replace("minecraft:", "").replace("_", " ").title()

        # Get item Count
        count_tag = entry_val.get("Count")
        count = 1
        if count_tag and isinstance(count_tag, dict):
            count = count_tag.get("value", 1)

        contents.append({"name": clean_name, "count": count})

    return contents


@dataclass
class User:
    """User data structure"""
    xuid: str
    name: str
    last_join: int = 0
    last_leave: int = 0


class DatabaseManager:
    """Base database manager with thread-safe operations"""

    _lock = threading.Lock()

    def __init__(self, db_name: str):
        """Initialize database connection"""
        self.db_path = DB_FOLDER / (db_name if db_name.endswith('.db') else db_name + '.db')
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # Enable WAL mode for better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.cursor = self.conn.cursor()

    def execute(self, query: str, params: tuple = (), readonly: bool = False) -> sqlite3.Cursor:
        """Execute a database query with thread safety"""
        if readonly:
            read_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            cursor = read_conn.cursor()
            cursor.execute(query, params)
            return cursor
        else:
            with self._lock:
                self.cursor.execute(query, params)
                if not query.strip().upper().startswith("SELECT"):
                    self.conn.commit()
                return self.cursor

    def close(self):
        """Close database connection"""
        self.conn.close()


class InventoryDB(DatabaseManager):
    """Database for storing player inventory and ender chest data using NBT JSON blobs"""

    def __init__(self, db_name: str = "inventories.db"):
        """Initialize inventory database"""
        super().__init__(db_name)
        self.create_tables()

    def create_tables(self):
        """Create database tables if they don't exist"""
        # Users table
        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                xuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                last_join INTEGER DEFAULT 0,
                last_leave INTEGER DEFAULT 0
            )
        """)

        # Inventories table — stores full NBT JSON blob
        self.execute("""
            CREATE TABLE IF NOT EXISTS inventories_v2 (
                xuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                items_json TEXT NOT NULL
            )
        """)

        # Ender chests table — stores full NBT JSON blob
        self.execute("""
            CREATE TABLE IF NOT EXISTS ender_chests_v2 (
                xuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                items_json TEXT NOT NULL
            )
        """)

        # Indices
        self.execute("CREATE INDEX IF NOT EXISTS idx_users_name ON users(name)")

    def save_user(self, player: Player, join_time: int):
        """Save or update user information"""
        with self._lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO users (xuid, name, last_join)
                VALUES (?, ?, ?)
            """, (player.xuid, player.name, join_time))
            self.conn.commit()

    def update_user_leave_time(self, xuid: str, leave_time: int):
        """Update user's last leave time"""
        with self._lock:
            self.cursor.execute("""
                UPDATE users SET last_leave = ? WHERE xuid = ?
            """, (leave_time, xuid))
            self.conn.commit()

    def get_user_by_name(self, name: str) -> Optional[User]:
        """Get user by name (case-insensitive partial match)"""
        self.cursor.execute("""
            SELECT xuid, name, last_join, last_leave
            FROM users
            WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY last_join DESC
            LIMIT 1
        """, (f"%{name}%",))

        row = self.cursor.fetchone()
        if row:
            return User(xuid=row[0], name=row[1], last_join=row[2], last_leave=row[3])
        return None

    def search_users_by_name(self, name: str) -> List[User]:
        """Search for users by name (case-insensitive partial match)"""
        self.cursor.execute("""
            SELECT xuid, name, last_join, last_leave
            FROM users
            WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY last_join DESC
        """, (f"%{name}%",))

        users = []
        for row in self.cursor.fetchall():
            users.append(User(xuid=row[0], name=row[1], last_join=row[2], last_leave=row[3]))
        return users

    def save_inventory(self, player: Player):
        """Save player's full inventory (main + armor + offhand) as NBT JSON blob"""
        items = []

        # Main inventory slots
        for i in range(player.inventory.size):
            items.append(serialize_item(player.inventory.get_item(i), i, "slot"))

        # Armor slots
        armor_map = {
            "helmet": -1,
            "chestplate": -2,
            "leggings": -3,
            "boots": -4,
            "item_in_off_hand": -5,
        }
        for attr_name, slot_num in armor_map.items():
            item = getattr(player.inventory, attr_name, None)
            items.append(serialize_item(item, slot_num, attr_name))

        items_json = json.dumps(items, ensure_ascii=False)

        with self._lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO inventories_v2 (xuid, name, items_json)
                VALUES (?, ?, ?)
            """, (player.xuid, player.name, items_json))
            self.conn.commit()

    def get_inventory(self, xuid: str) -> List[Dict[str, Any]]:
        """Get player's inventory from database as list of item dicts"""
        self.cursor.execute("""
            SELECT items_json FROM inventories_v2 WHERE xuid = ?
        """, (xuid,))

        row = self.cursor.fetchone()
        if not row or not row[0]:
            return []

        try:
            items = json.loads(row[0])
            # Filter out empty slots
            return [item for item in items if item.get("type") is not None]
        except (json.JSONDecodeError, Exception) as e:
            print(f"[InventoryDB] Failed to parse inventory for {xuid}: {e}")
            return []

    def save_enderchest(self, player: Player):
        """Save player's ender chest as NBT JSON blob"""
        items = []

        for i in range(player.ender_chest.size):
            items.append(serialize_item(player.ender_chest.get_item(i), i, "slot"))

        items_json = json.dumps(items, ensure_ascii=False)

        with self._lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO ender_chests_v2 (xuid, name, items_json)
                VALUES (?, ?, ?)
            """, (player.xuid, player.name, items_json))
            self.conn.commit()

    def get_enderchest(self, xuid: str) -> List[Dict[str, Any]]:
        """Get player's ender chest from database as list of item dicts"""
        self.cursor.execute("""
            SELECT items_json FROM ender_chests_v2 WHERE xuid = ?
        """, (xuid,))

        row = self.cursor.fetchone()
        if not row or not row[0]:
            return []

        try:
            items = json.loads(row[0])
            # Filter out empty slots
            return [item for item in items if item.get("type") is not None]
        except (json.JSONDecodeError, Exception) as e:
            print(f"[InventoryDB] Failed to parse ender chest for {xuid}: {e}")
            return []
