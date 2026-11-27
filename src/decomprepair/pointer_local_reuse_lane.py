"""Expose pointer lifetime reuse in the local lane as well as the draft pass.

The legacy pointer-pair module is called by the draft pass; its CFG-proved
reuse proposals also need the Deep Permuter's local lane. The implementation
and its bounded ordering remain in that module so the two lanes agree.
"""
from .pointer_pair_repairs import reuse

FAMILIES = ('pointer_local_reuse',)


def variants(source, name, header=''):
    return reuse(source, name, header)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'lanes': ('local',)}
