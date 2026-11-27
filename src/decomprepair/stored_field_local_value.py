"""A later read of a field just stored from a local written as the local.

    obj->nodes = nodes = header + offset;
    ...
    } else {
        node = obj->nodes;      /* the target: move $s0, $a0 */
    }

The compiler reloads the field after other stores through `obj` (`lw $s0, 4($s4)`), while the target keeps the value it
stored in a register: the original read the local (`node = nodes;`). One read at a time (SN GCC 2.8.1, one N64 model
loader: 200 -> exact with the other steps). Offered when neither the local nor the field is assigned between the store
and the read; as with the compiler, the other members of the same object are taken not to overlap the field.
"""
import re

from .csource import _blank, find

FAMILY = 'stored_field_local_value'
FAMILIES = (FAMILY,)
LIMIT = 16

_FIELD = r'[A-Za-z_]\w*->[A-Za-z_]\w*'
_CHAINED = re.compile(rf'(?<![\w.>])(?P<field>{_FIELD})[ \t]*=[ \t]*(?P<local>[A-Za-z_]\w*)[ \t]*=(?!=)[^;]*;')
_PLAIN = re.compile(rf'(?<![\w.>])(?P<field>{_FIELD})[ \t]*=[ \t]*(?P<local>[A-Za-z_]\w*)[ \t]*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    brace = source.find('{', span[0])
    clean = _blank(source)
    out = []
    for store in [*_CHAINED.finditer(clean, brace), *_PLAIN.finditer(clean, brace)]:
        field, local = store['field'], store['local']
        read = re.compile(rf'=[ \t]*(?P<read>{re.escape(field)})(?=[ \t]*;)')
        written = re.compile(rf'(?<![\w.>]){re.escape(local)}[ \t]*(?:\+\+|--|(?:[-+*/&|^]|<<|>>)?=(?!=))'
                             rf'|{re.escape(field)}[ \t]*(?:[-+*/&|^]|<<|>>)?=(?!=)')
        for use in read.finditer(clean, store.end()):
            between = clean[store.end():use.start()]
            # a read in an `else` arm is not preceded by what the `then` arm assigned
            arm = between.rfind('else')
            if arm >= 0 and '}' not in between[arm:]:
                head = between[:between.find('{')] if '{' in between else between
                between = head
            if written.search(between):
                continue
            child = source[:use.start('read')] + local + source[use.end('read'):]
            out.append((FAMILY, child))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
