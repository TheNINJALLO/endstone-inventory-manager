# 1.0.18 — release, 2026-11-02

Require InventoryUI 2.0.10 instead of downloading the older 2.0.8 tag. Preserve auxiliary item data, reject unsupported/unreadable NBT and verify restored metadata. Failed offline inventory/ender-chest reads cancel editing before a save can replace the original snapshot.

# 1.0.16

InventoryUI 2.0.7 is now an explicit plugin dependency and the Python dependency is pinned to its release. Install both wheels and restart to receive the repaired inventory movement, menu opening, and close behavior.
