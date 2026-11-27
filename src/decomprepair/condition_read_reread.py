"""A narrow local that holds a memory read and is only tested, written as the read at each test.

A rewrite (or m2c) names a halfword read once and tests the name in both halves of an `if`:

    buttons = **gPad;                              if (**gPad & code[step]) {
    if (buttons & code[step]) {                        step++;
        step++;                           ->           ...
        ...                                        } else if (**gPad) {
    } else if (buttons) {                              step = 0;
        step = 0;                                  }
    }

The program is the same (nothing between the read and a test writes memory or calls), the code is not: GCC keeps a
`u16` user variable in a promoted register, so the second test reads it as it is, while the unnamed halfword the
compiler's value reuse carries into the `else` arm is zero-extended there (`andi $v0, $a0, 0xffff` before the
`bnel`). On a 132-instruction N64 input-sequence routine (SN64 GCC, `-O2 -mips3 -mfp64`, three such blocks) it was
the whole difference between 1825 and 0. The promoted-register explanation is a hypothesis read from the
instructions, not from the compiler's source; the judge decides each child. `*(T *)p & 0xFFFF` on a `u16` read
(m2c's spelling of the second test) is the read itself.

`variants` takes each statement `local = <read>;` where the local is a `u8`, `u16`, `s8` or `s16` and the read is a
dereference with no call and no assignment in it, and whose reads (two or more, up to the next set of the local) are
all inside `if` conditions with no call and no store to anything but a plain local on the way from the set. All such
sets at once first, then each alone. Returns [(family, source)]."""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pattern_repairs import close

FAMILY = 'condition_read_reread'
FAMILIES = (FAMILY,)
LIMIT = 8
_NARROW = {'u8': 0xFF, 'u16': 0xFFFF, 's8': None, 's16': None, 'unsigned char': 0xFF, 'unsigned short': 0xFFFF,
           'signed char': None, 'signed short': None, 'short': None, 'char': None}
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b){IDENT}\s*\(|[\)\]]\s*\(\s*\)')
_ASSIGN = re.compile(r'(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--')
_PLAIN_SET = re.compile(rf'(?:^|[;{{}}:)]|\belse\b)\s*(?:(?:{IDENT})\s+)?({IDENT})\s*$')
_IF = re.compile(r'\bif\s*\(')


def _conditions(clean, start, end):
    """The spans inside the parentheses of every `if` between `start` and `end`."""
    found = []
    for hit in _IF.finditer(clean, start, end):
        stop = close(clean, hit.end() - 1, '(', ')')
        if stop:
            found.append((hit.end(), stop - 1))
    return found


def _block_end(clean, at, end):
    """The `}` that ends the block `at` stands in."""
    depth = 0
    for hit in re.compile(r'[{}]').finditer(clean, at, end):
        if hit[0] == '{':
            depth += 1
        elif depth == 0:
            return hit.start()
        else:
            depth -= 1
    return end


def _path(clean, start, use):
    """The text run between the set and a use: without the `if` arms whose `else` holds the use."""
    text = clean[start:use]
    pieces, position = [], 0
    for hit in re.finditer(r'{', text):
        if hit.start() < position:
            continue
        stop = close(text, hit.start(), '{', '}')
        if stop and re.match(r'\s*else\b', text[stop:]):
            pieces.append(text[position:hit.start()])
            position = stop
    pieces.append(text[position:])
    return ''.join(pieces)


def _quiet(path, names, reads):
    """No call, and nothing assigned but plain locals the read does not use."""
    if _CALL.search(path):
        return False
    for hit in _ASSIGN.finditer(path):
        if hit[0] in ('++', '--'):
            return False
        target = _PLAIN_SET.search(path[:hit.start()])
        if not target or target[1] not in names or target[1] in reads:
            return False
    return True


def _webs(part):
    """[(local's declaration, set span, read text, [use spans])] for each eligible set."""
    clean, source = part.clean, part.source
    declared = [decl for decl in locals_for(part)]
    names = {decl['name'] for decl in declared}
    found = []
    for decl in declared:
        kind = ' '.join(decl['type'].split())
        if kind not in _NARROW:
            continue
        name = decl['name']
        sets = list(re.finditer(rf'(?<=[;{{}}])\s*\b{name}\s*=(?!=)\s*(?P<read>[^;{{}}]+);', clean[:part.end]))
        sets = [hit for hit in sets if hit.start() > part.opening]
        every = refs(part, decl)
        for index, hit in enumerate(sets):
            read = source[hit.start('read'):hit.end('read')].strip()
            masked = clean[hit.start('read'):hit.end('read')].strip()
            if (not (masked.startswith('*') or masked.startswith('(*') or '->' in masked) or _CALL.search(masked)
                    or _ASSIGN.search(masked) or re.search(rf'\b{name}\b', masked)):
                continue
            stop = _block_end(clean, hit.end(), part.end)
            if index + 1 < len(sets):
                stop = min(stop, sets[index + 1].start())
            uses = [use for use in every if hit.end() <= use.start() < stop]
            conditions = _conditions(clean, hit.end(), stop)
            if len(uses) < 2 or not all(any(a <= use.start() < b for a, b in conditions) for use in uses):
                continue
            reads = set(re.findall(IDENT, masked))
            if not all(_quiet(_path(clean, hit.end(), use.start()), names, reads) for use in uses):
                continue
            found.append((decl, (hit.start(), hit.end()), read, [(use.start(), use.end()) for use in uses]))
    return found


def _rewrite(part, chosen):
    clean, changes, taken = part.clean, [], {}
    for decl, (start, stop), read, uses in chosen:
        mask = _NARROW[' '.join(decl['type'].split())]
        gap = start + len(clean[start:stop]) - len(clean[start:stop].lstrip())
        line = part.source.rfind('\n', 0, gap)
        alone = line >= start and not part.source[line:gap].strip()
        changes.append((line if alone else gap, stop, ''))
        for a, b in uses:
            text = '(' + read + ')'
            tail = re.compile(r'\s*&\s*(0[xX][0-9A-Fa-f]+|\d+)\b').match(clean, b)
            before = clean[:a].rstrip()
            if (tail and mask is not None and int(tail[1], 0) == mask and before.endswith('(')
                    and clean[tail.end():].lstrip().startswith(')')):
                text, b = read, tail.end()
            changes.append((a, b, text))
        taken[decl['name']] = taken.get(decl['name'], 0) + len(uses) + 1
    for decl, *_ in chosen:
        name = decl['name']
        if decl is None or taken.get(name) != len(refs(part, decl)):
            continue
        a = part.source.rfind('\n', 0, decl.start())
        a = a if a > part.opening and not part.source[a:decl.start()].strip() else decl.start()
        if (a, decl.end(), '') not in changes:
            changes.append((a, decl.end(), ''))
    return edit(part.source, changes)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    webs = _webs(part)[:LIMIT]
    chosen = ([webs] if len(webs) > 1 else []) + [[web] for web in webs]
    out = []
    for group in chosen:
        text = _rewrite(part, group)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 200}  # registry.py
