"""An accumulator updated in both arms of an if/else, written as one update after the join.

m2c writes what the compiler emitted, an add in each arm:

    if (mode == 4 || mode == 6) { sum += A[i]; } else { sum += B[i]; }

but the game picked the value in the arms and added once (`v = A[i]` / `v = B[i]`, then `sum += v;`): reorg then
copies the join's add into the first arm's `j` delay slot, so the output still shows an add in each arm. The two
spellings give the same instructions with other registers: two read-modify-writes inside a loop double the
accumulator's weighted references, so global.c ranks it above a hoisted loop invariant and the two exchange registers
(SN64 GCC 2.8.1 `-O1`, a 29-instruction table sum: 30 -> 10).

The remaining rows came from the counter's initialisation: with `u8 i;` and `s32 sum;` (or both one width) cse
copies the counter's zero from the accumulator's register (`move $3,$7` where the target has `move $3,$0`). The game
set the accumulator's zero first, kept the accumulator narrow (`u8`, read only as `sum & 0xFF`) and the counter wide (every read masked `& 0xFF`, so
`s32` changes nothing it computes); each alone changes nothing, together they were exact (10 -> 0). The join is offered
alone and with those widths as one child.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_accumulate_join'
FAMILIES = (FAMILY,)

ARMS = re.compile(r'(?m)^(?P<indent>[ \t]*)if \((?P<cond>[^{};]*)\)\s*\{\s*(?P<a>[A-Za-z_]\w*)\s*\+=\s*(?P<e1>[^;{}]+);'
                  r'\s*\}\s*else\s*\{\s*(?P<b>[A-Za-z_]\w*)\s*\+=\s*(?P<e2>[^;{}]+);\s*\}[ \t]*$')
DECLARATION = r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*)[ \t]+{}[ \t]*;'


def _declaration(body, local):
    return re.search(DECLARATION.format(re.escape(local)), body)


def _reads_masked(body, local, allowed):
    """Every occurrence of `local` in `body` is an assignment, an update or a read through `& 0xFF`."""
    for hit in re.finditer(rf'(?<![\w.>])({re.escape(local)})\b', body):
        after = body[hit.end():hit.end() + 12]
        before = body[max(0, hit.start() - 40):hit.start()]
        if re.match(r'\s*(?:\+=|-=|\+\+|--|=(?!=))', after) or re.match(r'\s*;', after) and re.search(r'(?:\+\+|--)\s*$', before):
            continue
        if re.match(r'\s*&\s*0xFF\b', after, re.I) and 'mask' in allowed:
            continue
        if re.search(r'\b[A-Za-z_]\w*\s+$', before) and re.match(r'\s*;', after):
            continue  # its declaration
        return False
    return True


def _widths(text, opening, end, accumulator, index_names):
    """The accumulator made `u8` and a `u8` counter made `s32`, when every read already masks them to a byte."""
    body = text[opening:end]
    edits = []
    decl = _declaration(body, accumulator)
    if not decl or decl['type'] not in ('s32', 'u32', 's16', 'u16') or not _reads_masked(body, accumulator, ('mask',)):
        return None
    edits.append((opening + decl.start('type'), opening + decl.end('type'), 'u8'))
    for counter in index_names:
        cdecl = _declaration(body, counter)
        if cdecl and cdecl['type'] == 'u8' and counter != accumulator and _reads_masked(body, counter, ('mask',)):
            edits.append((opening + cdecl.start('type'), opening + cdecl.end('type'), 's32'))
    if len(edits) < 2:
        return None
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in ARMS.finditer(clean, opening, end):
        accumulator = hit['a']
        if hit['b'] != accumulator or re.search(rf'\b{accumulator}\b', hit['e1'] + hit['e2'] + hit['cond']):
            continue
        if not _declaration(clean[opening:end], accumulator):
            continue
        value = 'value'
        while re.search(rf'\b{value}\b', clean):
            value = '_' + value if value.startswith('arm') else 'arm_value'
        indent = hit['indent']
        inner = indent + '    '
        e1 = source[hit.start('e1'):hit.end('e1')].strip()
        e2 = source[hit.start('e2'):hit.end('e2')].strip()
        cond = source[hit.start('cond'):hit.end('cond')]
        block = (f'{indent}if ({cond}) {{\n{inner}{value} = {e1};\n{indent}}} else {{\n{inner}{value} = {e2};\n'
                 f'{indent}}}\n{indent}{accumulator} += {value};')
        text = source[:hit.start()] + block + source[hit.end():]
        # the new local, after the function's last top-level declaration
        decls = list(re.finditer(r'(?m)^([ \t]+)[A-Za-z_][\w \t]*\*?[ \t]*\w+(?:\[[^]]*\])?;[ \t]*\n',
                                 _blank(text)[opening + 1:hit.start()]))
        top = [d for d in decls if not re.search(r'[{}]', _blank(text)[opening + 1:opening + 1 + d.start()])]
        at = opening + 1 + (top[-1].end() if top else 1)
        pad = top[-1][1] if top else '    '
        text = text[:at] + f'{pad}s32 {value};\n' + text[at:]
        result.append((FAMILY, text))
        new_end = close(_blank(text), opening, '{', '}')
        indexes = set(re.findall(r'\b([A-Za-z_]\w*)\s*&\s*0xFF\b', _blank(text)[opening:new_end], re.I))
        widened = _widths(text, opening, new_end, accumulator, sorted(indexes))
        if widened:
            # the accumulator's zero ahead of the counter's: the counter's is then the last insn before the guard
            # (the guard's delay slot), as two separate `li 0`s
            swapped = re.sub(rf'(?m)^([ \t]*)(\w+) = 0;[ \t]*\n\1({accumulator}) = 0;',
                             r'\1\3 = 0;\n\1\2 = 0;', widened, count=1)
            if swapped != widened:
                result.append((FAMILY, swapped))
            result.append((FAMILY, widened))
        if len(result) >= 4:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
