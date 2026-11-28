"""m2c's stack slots stored word by word through a pointer, as the local record the game copied into the destination.

A function that builds a small record on its stack and copies it into a table slot (`Point dot; ...; table[n] = dot;`)
comes back from m2c as the frame's scratch array, a macro per slot, and one word store per slot, some of the slots
perhaps never assigned (a member the game left unset):

    u8 sp[16];                                                typedef struct { s32 w[4]; } __repair_slots4;
    #define sp0 (*(s32 *)(sp + 0x0))                          __repair_slots4 __repair_frame;
    ...                                                       ...
    sp0 = ...;  sp4 = ...;  sp8 = ...;                  ->    __repair_frame.w[0] = ...;  ...
    M2C_FIELD(dst, s32 *, 8) = sp8;                           *(__repair_slots4 *) ((s8 *) (dst)) = __repair_frame;
    M2C_FIELD(dst, s32 *, 4) = sp4;
    M2C_FIELD(dst, s32 *, 0) = sp0;
    M2C_FIELD(dst, s32 *, 0xC) = spC;

An assignment of a record is a block copy (`lw` four registers, `sw` four registers); the word stores are not. The
stores may come in any order: each reads its own slot and writes its own offset, and the frame's address is not taken.
Declined unless the macros are the only use of the array, they name every word of it as `s32` or `u32`, and one run of
stores copies every word to consecutive offsets of one pointer.

Three children, since the steps after the copy may only pay off together:

* `stack_slot_record_copy`: the record and its copy alone;
* `stack_slot_record_copy_unfenced`: with every `do { S } while (0);` a search left written as a block;
* `stack_slot_record_copy_bump_late`: and a counter bump (`G = n + 1;`) that stands between the writes of the record
  moved after the last of them, so the counter is stored where the record is complete.

Matched on a 39-instruction N64 dot-list append (SN GCC 2.8.1, `-G0 -mips3 -O2 -mgas -mfp32`): 860 as saved, 295 with
the copy, 120 with the fences opened, 0 with the counter bump below the third member. The bump alone and the fences
alone could not reach it. This module reads text only; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .scaffold_strip import unfence

FAMILY = 'stack_slot_record_copy'
UNFENCED = 'stack_slot_record_copy_unfenced'
BUMP_LATE = 'stack_slot_record_copy_bump_late'
FAMILIES = (FAMILY, UNFENCED, BUMP_LATE)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_FRAME = re.compile(rf'(?m)^[ \t]*(?:u8|s8|char)[ \t]+(?P<array>sp)\[(?P<size>{_NUM})\];[ \t]*\n')
_SLOT = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+(?P<name>sp[0-9A-F]+)[ \t]+'
                   rf'\(\*\([ \t]*(?P<type>{_ID})[ \t]*\*\)[ \t]*\([ \t]*sp[ \t]*\+[ \t]*(?P<off>{_NUM})[ \t]*\)\)[ \t]*\n')
_STORE = re.compile(rf'M2C_FIELD\(\s*(?P<base>{_ID})\s*,\s*(?:s32|u32)\s*\*\s*,\s*(?P<off>{_NUM})\s*\)\s*=\s*'
                    rf'(?:\(\s*(?:s32|u32)\s*\)\s*)?(?P<slot>sp[0-9A-F]+)\s*;')


def _copy_run(clean, lo, hi, slots):
    """The first run of adjacent stores that copies every slot to consecutive offsets of one pointer, or None."""
    run = []
    for m in _STORE.finditer(clean, lo, hi):
        if run and (clean[run[-1].end():m.start()].strip() or m['base'] != run[0]['base']):
            run = []
        if m['slot'] not in slots:
            run = []
            continue
        run.append(m)
        if len(run) == len(slots):
            starts = {int(s['off'], 0) - slots[s['slot']] for s in run}
            if len({s['slot'] for s in run}) == len(slots) and len(starts) == 1 and min(starts) >= 0:
                return run, starts.pop()
            run.pop(0)
    return None


def _record_copy(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    frame = _FRAME.search(clean, opening, end)
    if not frame:
        return None
    size = int(frame['size'], 0)
    defines = list(_SLOT.finditer(clean))
    slots = {m['name']: int(m['off'], 0) for m in defines if m['type'] in ('s32', 'u32')}
    if len(slots) != len(defines) or size < 8 or size % 4 or sorted(slots.values()) != list(range(0, size, 4)):
        return None
    body = clean[opening:end]
    # the array is only ever declared: every other use of the frame goes through a slot's macro
    if len(re.findall(r'\bsp\b', body)) != 1 or re.search(r'&\s*\(?\s*(?:%s)\b' % '|'.join(slots), body):
        return None
    found = _copy_run(clean, opening, end, slots)
    if not found:
        return None
    run, start = found
    words = size // 4
    record = f'__repair_slots{words}'
    local = '__repair_frame'
    if re.search(rf'\b{local}\b', source):
        return None
    destination = f'(s8 *) ({run[0]["base"]}) + 0x{start:X}' if start else f'(s8 *) ({run[0]["base"]})'
    copy = f'*({record} *) ({destination}) = {local};'
    inner = source[opening:run[0].start()] + copy + source[run[-1].end():end]
    for slot, offset in slots.items():
        inner = re.sub(rf'(?<![\w.>]){slot}\b', f'{local}.w[{offset // 4}]', inner)
    inner = _FRAME.sub(f'    {record} {local};\n', inner, count=1)
    typedef = '' if re.search(rf'\b{record}\b', source) else f'typedef struct {{ s32 w[{words}]; }} {record};\n'
    before, after = source[:span[0]], source[end:]
    for m in defines:  # the old array's macros go with it
        line = source[m.start():m.end()]
        before, after = before.replace(line, ''), after.replace(line, '')
    return before + typedef + source[span[0]:opening] + inner + after


_BUMP = re.compile(rf'(?:\(\s*\*\s*(?P<p>{_ID})\s*\)|(?<![\w.>\])])\*\s*(?P<q>{_ID})|(?<![\w.>*])(?P<g>{_ID}))\s*=\s*'
                   rf'(?P<value>{_ID})\s*\+\s*1\s*;')
_MEMBER = re.compile(r'[\s{}]*(?P<write>__repair_frame\.w\[\d+\]\s*=(?!=)[^;{}]*;)')


def _bare_blocks(clean, lo, hi):
    """Whether every brace in clean[lo:hi] belongs to a bare block (one opened where a statement may start)."""
    stack, openers = [], {}
    for brace in re.finditer(r'[{}]', clean[:hi]):
        if brace.group() == '{':
            stack.append(brace.start())
        elif stack:
            openers[brace.start()] = stack.pop()
    for brace in re.finditer(r'[{}]', clean[lo:hi]):
        at = lo + brace.start()
        opener = at if brace.group() == '{' else openers.get(at)
        if opener is None or not clean[:opener].rstrip().endswith(('{', '}', ';')):
            return False
    return True


def _bump_late(source, name):
    """`G = n + 1;` moved below the writes of the record that follow it, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    for bump in _BUMP.finditer(clean, span[0], span[1]):
        if not clean[:bump.start()].rstrip().endswith(('{', '}', ';')):
            continue
        target = bump['p'] or bump['q'] or bump['g']
        cursor = bump.end()
        while member := _MEMBER.match(clean, cursor):
            # the write must not read the counter, and only bare blocks may be left or entered on the way
            if re.search(rf'\b{target}\b', member['write']) or not _bare_blocks(clean, cursor, member.start('write')):
                break
            cursor = member.end()
        if cursor == bump.end():
            continue
        line = source[bump.start():bump.end()]
        return source[:bump.start()] + source[bump.end():cursor] + ' ' + line + source[cursor:]
    return None


def variants(source, name):
    """[(family, source)]: with the counter bump late, with the fences opened, and the record copy alone."""
    copied = _record_copy(source, name)
    if not copied:
        return []
    opened = unfence(copied, name)
    late = _bump_late(opened or copied, name)
    out = [(BUMP_LATE, late)] if late else []
    if opened:
        out.append((UNFENCED, opened))
    return out + [(FAMILY, copied)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
