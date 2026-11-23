"""An address-taken local read before the pointer store in front of it, not after.

A frame local whose address went to a callee (`f(&locals.out40)`) is memory the compiler must assume any store through a
pointer may overwrite: it keeps the local's load after such a store. The game's `if (locals.out40 != 0 && ...)` was
written after `p->flags &= ~4;` in the draft, so the load followed the store and the compare took the register the
store's pointer had just freed (`lw $v0, 0x40($sp)`, the `sh` ahead of the `beqz`, a `nop` in its delay slot). The target
reads the local first (`lw $a0, 0x40($sp)` before the `andi`, the `sh` in the delay slot of the `beqz`). With the read
written first and the condition using the copy, a 1137-instruction update routine went 570 -> 320 (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`; one step of a chain that ended 60 from a match). Hypothesis from the match: cse keeps the
local's load after a store through a pointer, and the register the compare takes follows from where the load sits.

store_barrier_read_hoist
    A statement that stores through a pointer (`... ->field = ...;`, `*(...) = ...;`, a compound assignment to either)
    followed directly by `if (X ...)` where X is a member `local.field` of a declared struct local whose address is taken
    elsewhere (`&local.field`), and X is the first operand of the condition: one child declares `field_early` of the
    member's type, writes `field_early = X;` before the store and reads it in the condition. At most 4 children."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'store_barrier_read_hoist'
FAMILIES = (FAMILY,)
LIMIT = 4
_STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<stmt>[^;{}\n]*(?:->|\*)[^;{}\n]*?(?:[-+*/%&|^]|<<|>>)?=(?!=)[^;{}\n]+;)[ \t]*\n(?P<gap>[ \t]*\n)*[ \t]*if\s*\(')
_MEMBER = re.compile(rf'(?<![\w.>])(?P<var>{IDENT})\.(?P<field>{IDENT})\b')


def _field_type(clean, var, field):
    """The declared type of `var.field` when `var` is a struct local declared with its body in the function."""
    for decl in re.finditer(rf'struct\s*(?:{IDENT}\s*)?\{{(?P<fields>[^{{}}]*)\}}\s*{re.escape(var)}\s*;', clean):
        member = re.search(rf'(?m)^\s*(?P<type>[A-Za-z_][\w \t\*]*?)\s*(?P<star>\*?)\s*{re.escape(field)}\s*;', decl['fields'])
        if member:
            return re.sub(r'\s+', ' ', member['type'].strip()) + (' *' if member['star'] else '')
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for hit in _STORE.finditer(clean, opening, span[1]):
        stmt = hit['stmt']
        if re.match(r'\s*(?:return|if|while|for|else)\b', stmt):
            continue
        cond_at = hit.end() - 1
        stop = close(clean, cond_at, '(', ')')
        if not stop:
            continue
        condition = clean[cond_at + 1:stop - 1]
        first = _MEMBER.search(condition)
        if not first:
            continue
        lead = condition[:first.start()].replace('(', '').strip()
        if lead not in ('', '!'):
            continue
        var, field = first['var'], first['field']
        if not re.search(rf'&\s*{re.escape(var)}\.{re.escape(field)}\b', clean[opening:span[1]]):
            continue
        kind = _field_type(clean[opening:span[1]], var, field)
        if not kind:
            continue
        copy = f'{field}_early'
        if re.search(rf'\b{copy}\b', clean):
            continue
        at = cond_at + 1 + first.start()
        text = source[:at] + copy + source[at + first.end() - first.start():]
        store_at = hit.start()
        text = text[:store_at] + f'{hit["indent"]}{copy} = {var}.{field};\n' + text[store_at:]
        body = text.find('\n', text.find('{', span[0])) + 1
        decl_indent = re.match(r'[ \t]*', text[body:])[0] or '  '
        text = text[:body] + f'{decl_indent}{kind}{"" if kind.endswith("*") else " "}{copy};\n' + text[body:]
        out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
