"""A pointer stored into a field and passed to the next call, read back from the field for the call, with the local's
next step written before the call.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) object initialiser (392 instructions, 27 -> 22). The draft
allocated a record, kept it in the local that then walks the allocation, and cleared its head:

    p = alloc(size);
    if (p != 0) {
        obj->rec = p;
        memset((void *) p, 0, 0xB8);
        rec = obj->rec;
        p += 0xB8;
        rec->a = p;
        ...

The target passes the call's result register (`move $a0,$v0`), while the draft passed the local (`move $a0,$s0`): cse
makes the copy of the call's result and the local one class and writes the local, the longer-lived of the two, for
every use (cse.c `make_regs_eqv`). Read from the field the call's argument is the value the store recorded, and once
the local has taken its next step the store's class is the result's alone, so the argument is the call's result.
The step is a register operation on a saved register, and the scheduler is free to put it back after the call:

    obj->rec = p;
    p += 0xB8;
    memset((void *) obj->rec, 0, 0xB8);

stored_value_call_reread
    For each `LV = x;` (`LV` not a plain name and not mentioning `x`, `x` a local without its address taken) followed
    directly by a call statement whose first argument is `x` (cast or not), when the first later statement of the
    block that mentions `x` is its update `x += K;`/`x -= K;`/`x = x + K;`: the update moved before the call and the
    argument written as `LV` (with the argument's cast). One child per site, at most four.

Hypothesis from this function's dumps (`.cse`, `.cse2`), not proven from the compiler source beyond `make_regs_eqv`.
The exact judge decides every child.
"""
import re

from .integer_repair_support import view

FAMILY = 'stored_value_call_reread'
FAMILIES = (FAMILY,)
LIMIT = 4
_IDENT = r'[A-Za-z_]\w*'
_STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<lv>[^;={{}}\n]*?(?:->|\[|\*|\.)[^;={{}}\n]*?)[ \t]*=[ \t]*'
                    rf'(?P<x>{_IDENT})[ \t]*;[ \t]*\n')
_CALL = re.compile(rf'[ \t]*(?P<fn>{_IDENT})[ \t]*\([ \t]*(?P<cast>\([^()]*\)[ \t]*)?(?P<arg>{_IDENT})[ \t]*'
                   rf'(?P<rest>(?:,[^;\n]*)?\))[ \t]*;[ \t]*\n')
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'do'}


def _words(text, name):
    return list(re.finditer(rf'(?<![\w.>]){re.escape(name)}(?!\w)', text))


def _statements(clean, start, high):
    """(start, end) of each line-statement after `start` in the same block, stopping at the block's end."""
    out, depth, i = [], 0, start
    while i < high:
        line_end = clean.find('\n', i)
        if line_end < 0:
            line_end = high
        line = clean[i:line_end]
        depth += line.count('{') - line.count('}')
        if depth < 0:
            break
        out.append((i, line_end + 1, depth))
        i = line_end + 1
    return out


def variants(source, name):
    """Proposals: a stored local's next call argument read back from the store, the local's step moved above it."""
    part = view(source, name)
    if not part:
        return []
    clean, low, high = part.clean, part.opening + 1, part.end
    out = []
    for store in _STORE.finditer(clean, low, high):
        x, lv = store['x'], store['lv'].strip()
        if _words(lv, x) or re.search(rf'&\s*{re.escape(x)}\b', clean[low:high]):
            continue
        if not re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*[ \t*]{re.escape(x)}[ \t]*;', clean[low:store.start()]):
            continue  # (a global's step could be seen by the call)
        call = _CALL.match(clean, store.end())
        if not call or call['fn'] in _KEYWORDS or call['arg'] != x or _words(call['rest'], x):
            continue
        update = None
        for start, end, depth in _statements(clean, call.end(), high):
            text = clean[start:end]
            if not _words(text, x):
                continue
            step = (re.fullmatch(rf'[ \t]*{re.escape(x)}[ \t]*[-+]=[ \t]*(?P<k>[^;\n]+);[ \t]*\n', text)
                    or re.fullmatch(rf'[ \t]*{re.escape(x)}[ \t]*=[ \t]*{re.escape(x)}[ \t]*[-+][ \t]*(?P<k>[^;\n]+);[ \t]*\n',
                                    text))
            if depth == 0 and step and not _words(step['k'], x):
                update = (start, end)
            break
        if not update:
            continue
        line = source[call.start():call.end()]
        offset = call.start('arg') - call.start()
        line = line[:offset] + lv + line[offset + len(x):]
        step_text = store['indent'] + source[update[0]:update[1]].lstrip(' \t')
        edited = (source[:call.start()] + step_text + line + source[call.end():update[0]] + source[update[1]:])
        out.append((FAMILY, edited))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 62}
