"""Fast copies of the mutable function tree in the pinned permuter parser."""

from copy import deepcopy

_IMMUTABLE = frozenset({str, bytes, int, float, complex, bool, type(None)})
_MISSING = object()


def make_cloner(nodes, coordinate):
    """Return a deepcopy specialized for the parser's generated slotted records."""
    slots = {
        cls: tuple(name for name in cls.__slots__ if name != '__weakref__')
        for cls in (*nodes, coordinate)
    }

    def clone_tree(root):
        memo = {}

        def clone(value):
            cls = type(value)
            if cls in _IMMUTABLE:
                return value

            identity = id(value)
            previous = memo.get(identity, _MISSING)
            if previous is not _MISSING:
                return previous

            if cls is list:
                result = []
                memo[identity] = result
                result.extend(clone(item) for item in value)
                return result

            fields = slots.get(cls)
            if fields is None:
                return deepcopy(value, memo)

            result = cls.__new__(cls)
            memo[identity] = result
            for name in fields:
                field = getattr(value, name, _MISSING)
                if field is not _MISSING:
                    setattr(result, name, clone(field))
            return result

        return clone(root)

    return clone_tree
