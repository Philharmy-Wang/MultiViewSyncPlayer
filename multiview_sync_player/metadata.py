"""
multiview_sync_player.metadata — Session metadata data class

Ordered dictionary of user-defined string fields (name → value).
Designed for serialization into .mvsp.json session files.
"""

import re
from collections import OrderedDict

# Field name must be a valid identifier: letters, digits, underscores
_FIELD_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class SessionMetadata:
    """Ordered collection of user-defined metadata fields.

    Each field is a (name, value) pair where name is a valid Python-style
    identifier and value is a string. Fields are stored in insertion order.
    """

    def __init__(self):
        self._fields: OrderedDict[str, str] = OrderedDict()

    # ---- Core operations ----

    def get(self, name: str, default: str = "") -> str:
        """Get field value by name."""
        return self._fields.get(name, default)

    def set(self, name: str, value: str):
        """Set field value. Creates the field if it doesn't exist.
        Name must be a valid identifier.
        """
        if not _FIELD_RE.match(name):
            raise ValueError(
                f"Invalid field name '{name}': must be a valid identifier "
                f"(letters, digits, underscores, not starting with digit)")
        self._fields[name] = str(value)

    def remove(self, name: str) -> bool:
        """Remove a field. Returns True if it existed."""
        if name in self._fields:
            del self._fields[name]
            return True
        return False

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a field, preserving its position and value.
        New name must be a valid identifier and not already in use.
        """
        if old_name not in self._fields:
            return False
        if not _FIELD_RE.match(new_name):
            raise ValueError(f"Invalid field name '{new_name}'")
        if new_name in self._fields and new_name != old_name:
            raise ValueError(f"Field '{new_name}' already exists")
        if new_name == old_name:
            return True
        # Rebuild OrderedDict with renamed key in the same position
        items = list(self._fields.items())
        self._fields.clear()
        for k, v in items:
            self._fields[new_name if k == old_name else k] = v
        return True

    def reorder(self, names_order: list):
        """Reorder fields to match the given name list.
        Any names not in the list are appended at the end in original order.
        Any names in the list that don't exist are ignored.
        """
        new_fields = OrderedDict()
        # First add fields in the specified order
        for name in names_order:
            if name in self._fields:
                new_fields[name] = self._fields[name]
        # Then append any remaining fields not in the order list
        for name, value in self._fields.items():
            if name not in new_fields:
                new_fields[name] = value
        self._fields = new_fields

    # ---- Query ----

    def names(self) -> list:
        """Return list of field names in order."""
        return list(self._fields.keys())

    def items(self):
        """Iterate over (name, value) pairs in order."""
        return self._fields.items()

    def __len__(self):
        return len(self._fields)

    def __contains__(self, name):
        return name in self._fields

    def __bool__(self):
        return bool(self._fields)

    # ---- Serialization ----

    def to_dict(self) -> dict:
        """Serialize to an ordered dict for JSON."""
        return dict(self._fields)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionMetadata":
        """Create from a dict (e.g., parsed from JSON)."""
        meta = cls()
        for k, v in data.items():
            if _FIELD_RE.match(k):
                meta._fields[k] = str(v)
        return meta

    # ---- Display ----

    def summary(self, max_items: int = 3) -> str:
        """Short summary string for window title, e.g. 'subject=24332, date=2026-01-26'."""
        parts = []
        for name in self._fields:
            val = self._fields[name]
            display = val if len(val) <= 30 else val[:27] + "..."
            parts.append(f"{name}={display}")
            if len(parts) >= max_items:
                break
        if len(self._fields) > max_items:
            parts.append(f"+{len(self._fields) - max_items} more")
        return ", ".join(parts)

    def __repr__(self):
        return f"SessionMetadata({dict(self._fields)})"
