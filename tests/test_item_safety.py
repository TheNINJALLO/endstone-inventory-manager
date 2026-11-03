import json

import pytest
from endstone.nbt import CompoundTag, ListTag, StringTag, IntTag, ByteTag
from endstone_inventory_manager import db_util


class Item:
    def __init__(self, kind, amount=1, data=0):
        self.type, self.amount, self.data = kind, amount, data
        self.nbt = CompoundTag()


def test_bundle_contents_lore_and_auxiliary_data_survive_json(monkeypatch):
    monkeypatch.setattr(db_util, 'ItemStack', Item)
    item = Item('minecraft:blue_bundle', data=13)
    item.nbt = CompoundTag({'storage_item_component_content': ListTag([
        CompoundTag({'Name': StringTag('minecraft:diamond'), 'Count': ByteTag(7),
                     'tag': CompoundTag({'display': CompoundTag({'Lore': ListTag([StringTag('§dEssentials lore')])})})})
    ]), 'bundle_weight': IntTag(7)})
    record = json.loads(json.dumps(db_util.serialize_item(item, 2)))
    restored = db_util.deserialize_item(record)
    assert restored.data == 13
    assert db_util.nbt_to_dict(restored.nbt) == record['nbt']


def test_read_error_never_becomes_a_plain_item():
    class Broken:
        type, amount, data = 'minecraft:blue_bundle', 1, 0
        @property
        def nbt(self):
            raise OSError('unreadable metadata')
    with pytest.raises(ValueError):
        db_util.serialize_item(Broken(), 0)


def test_unknown_saved_metadata_cannot_be_coerced_to_string():
    with pytest.raises(ValueError):
        db_util.dict_to_nbt({'_type': 'unknown', 'value': 'lost original'})
