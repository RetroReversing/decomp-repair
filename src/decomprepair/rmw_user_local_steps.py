"""A word read-modify-write written as one expression, written as a local updated by separate statements.

m2c writes a masked update as `p->w = (u32) ((p->w & 0xFFFF0FFF) | 0x7000);`. The first scheduler boosts an insn that
creates a pseudo set only once (`birthing_insn_p`: a launch priority above the ordinary ones), so the word's load is
pulled to wherever it first becomes ready, and in a basic block that also loads a float into a register with several sets
the word load ends up second. The target's block has the word first: the game's source updated a local
(`w = p->w; w &= mask; w |= bits; p->w = w;`), a pseudo with three sets, which gets no boost. On a 1137-instruction
player-update routine (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the last two differing rows (the `lw` and the `lwc1`
swapped) closed with it: 60 -> 0. A 25-line program with the same three statements shows the order flip with the
expression and with the local. The `sched.c` reading (`birthing_insn_p`, `adjust_priority`, `-dS` notes: the `7f000001`
priority on the word load) is the cause measured on that one block.

rmw_user_local_steps
    A statement `LHS = [(T)] ((LHS & M) | O);` (or `(LHS | O) & M`, `LHS & M`, `LHS | O`), where LHS is the same
    `((Field_T *) (((char *) base) + off))->v` read and written, becomes `rmw = LHS; rmw &= M; rmw |= O; LHS = rmw;`
    with `rmw_value` a new local of type T (the operations in the order written). Per statement three children: the steps where the
    expression stood, the load moved up above the one or two plain statements before it, and the load and the steps moved up
    (a statement that mentions the same word stops the move), and each with the new local declared below the last local, above it and first
    (where a local is declared is its pseudo's number: a match needed it one above the last); at most 72 children (3 places for the local x 3 forms x the statements)."""
import re

from .csource import _blank, find

FAMILY = 'rmw_user_local_steps'
FAMILIES = (FAMILY,)
LIMIT = 72
_FIELD = r'\(\(Field_[A-Za-z_]\w*\s*\*\)\s*\(\(\(char\s*\*\)\s*[A-Za-z_]\w*\)\s*\+\s*(?:0[xX][0-9A-Fa-f]+|\d+)\)\)\s*->\s*v'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_STMT = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>\(\(Field_(?P<type>[A-Za-z_]\w*)\s*\*\)\s*\(\(\(char\s*\*\)\s*[A-Za-z_]\w*\)\s*\+\s*(?:0[xX][0-9A-Fa-f]+|\d+)\)\)\s*->\s*v)\s*=\s*(?:\(\s*[A-Za-z_]\w*\s*\)\s*)?\(*\s*'
    rf'(?:\(\s*(?P<a>{_FIELD})\s*(?P<op1>[&|])\s*(?P<n1>{_NUM})\s*\)\s*(?P<op2>[&|])\s*(?P<n2>{_NUM})'
    rf'|(?P<b>{_FIELD})\s*(?P<op3>[&|])\s*(?P<n3>{_NUM}))\s*\)*\s*;[ \t]*$')


def _norm(text):
    return re.sub(r'\s+', '', text)


def _steps(found):
    if found['a']:
        return found['a'], [(found['op1'], found['n1']), (found['op2'], found['n2'])]
    return found['b'], [(found['op3'], found['n3'])]


_DECLARATION = re.compile(r'[ \t]*(?:register\s+|const\s+|unsigned\s+|signed\s+)*[A-Za-z_]\w*(?:[ \t]+\**[ \t]*|[ \t]*\*+[ \t]*)[A-Za-z_]\w*(?:\[[^\]]*\])?[ \t]*;[ \t]*$')


def _declaration_spots(text, start):
    """[(offset, indent)] of the places a new local can go in the declarations that open the function body: below the
    last one, above the last one, and first. Where a local is declared is its pseudo's number, which the allocator's
    tie-breaks read: a match needed the new local one place above the last."""
    pos = text.find('\n', text.find('{', start)) + 1
    first, ends, depth, inside = pos, [], 0, False
    while pos < len(text):
        end = text.find('\n', pos)
        end = len(text) if end < 0 else end
        line = text[pos:end]
        stripped = line.strip()
        if inside or re.match(r'(?:struct|union)\b', stripped):
            inside = True
            depth += stripped.count('{') - stripped.count('}')
            if depth == 0 and stripped.endswith(';'):
                inside = False
                ends.append((pos, end + 1, re.match(r'[ \t]*', line)[0]))
        elif stripped:
            if not (_DECLARATION.fullmatch(line) and '=' not in line):
                break
            ends.append((pos, end + 1, re.match(r'[ \t]*', line)[0]))
        pos = end + 1
    indent = ends[-1][2] if ends else '  '
    spots = [(ends[-1][1] if ends else first, indent)]
    if len(ends) > 1:
        spots.append((ends[-1][0], indent))
    spots.append((first, indent))
    return list(dict.fromkeys(spots))


def _rows(found, local):
    _, steps = _steps(found)
    lhs, indent = found['lhs'], found['indent']
    load = f'{indent}{local} = {lhs};'
    middle = [f'{indent}{local} {op}= {number};' for op, number in steps]
    return load, middle, f'{indent}{lhs} = {local};'


def _preceding(clean, source, start, lhs):
    """The (line start) of up to two single-line statements right above `start` that do not mention `lhs`."""
    spots, cursor = [], start
    while len(spots) < 2:
        line = clean.rfind('\n', 0, cursor - 1) + 1
        text = clean[line:cursor].strip()
        if not text or not text.endswith(';') or '{' in text or '}' in text or re.match(r'(?:return|goto|break|continue)\b', text) or _norm(lhs) in _norm(text):
            break
        spots.append(line)
        cursor = line
    return spots


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    hits = [f for f in _STMT.finditer(clean, opening, span[1]) if _norm(_steps(f)[0]) == _norm(f['lhs'])]
    if not hits or re.search(r'\brmw_value\b', clean):
        return []

    def build(chosen, mode, place):
        text = source
        for found in sorted(chosen, key=lambda f: f.start(), reverse=True):
            load, middle, store = _rows(found, 'rmw_value')
            above = _preceding(clean, source, found.start(), found['lhs']) if mode else []
            if mode and not above:
                return None
            if mode == 'load':
                head, rest = load + '\n', '\n'.join(middle + [store])
            elif mode == 'steps':
                head, rest = '\n'.join([load] + middle) + '\n', store
            else:
                head, rest = '', '\n'.join([load] + middle + [store])
            if mode:
                text = text[:found.start()] + rest + text[found.end():]
                text = text[:above[-1]] + head + text[above[-1]:]
            else:
                text = text[:found.start()] + rest + text[found.end():]
        spots = _declaration_spots(text, span[0])
        if place >= len(spots):
            return None
        at, indent = spots[place]
        return text[:at] + f'{indent}{chosen[0]["type"]} rmw_value;\n' + text[at:]

    out = []
    for mode in ('', 'load', 'steps'):
        for place in range(3):
            out += [build([h], mode, place) for h in hits]
    return [(FAMILY, text) for text in dict.fromkeys(t for t in out if t)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
