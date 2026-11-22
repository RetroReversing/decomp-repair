"""A float constant each arm picks, multiplied after the join: the product goes into each arm.

m2c reads a selecting if/else back as a variable each arm sets to a float literal, used once by the statement after
the join:

    if (flags & 0x20000000) {
        var_fv0 = 0.75f;
        idx = n * 4;
    } else {
        var_fv0 = 0.25f;
        idx = n * 4;
    }
    result = var_fv0 * table[idx];

gcc keeps the variable in a register of its own across the join and gives the table value the first float register,
so `$f0` and `$f2` trade places against a game that wrote the product in each arm. A KMC GCC 2.7.2 (-O2) N64 function
with this shape was at 15 (the two registers swapped, nothing else) and exact once written as

    if (flags & 0x20000000) {
        idx = n * 4;
        result = 0.75f * table[idx];
    } else {
        idx = n * 4;
        result = 0.25f * table[idx];
    }

The literal goes into the statement's one use of the variable, in each arm, after the arm's other statements, and the
statement after the join is removed. Nothing else changes: the arms are exhaustive and braced and hold no jump or
label, and the moved statement runs after the same statements it ran after before. The variable must be a float local
that nothing else in the function mentions but its declaration.
"""
import re

from .float_arm_roles import FLOAT, IDENT, _arms, _body, _statements
from .pattern_repairs import close

FAMILIES = ('float_arm_constant_tail',)
LIMIT = 2
LITERAL = r'[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]?'


def variants(source, name, header=''):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    result = []
    for keyword in re.finditer(r'\belse\s*\{', clean[opening:end]):
        closing = close(clean, opening + keyword.end() - 1, '{', '}')
        arms = _arms(clean, closing - 1) if closing else None
        if not arms:
            continue
        tail = re.match(r'\s*(?P<lhs>[^;={}]+?)\s*=(?!=)\s*(?P<rhs>[^;{}]+);', clean[closing:])
        if not tail or re.search(r'\+\+|--', clean[closing:closing + tail.end()]):
            continue
        rhs_at = closing + tail.start('rhs')
        rhs = source[rhs_at:closing + tail.end('rhs')]
        bodies = '\n'.join(clean[a:b] for a, b in arms)
        if re.search(r'\b(?:goto|return|break|continue|case|default|switch)\b|(?<![?:]):(?!:)|(?<![\w.>])asm\b', bodies):
            continue
        for var in dict.fromkeys(re.findall(IDENT, tail['rhs'])):
            use = re.compile(r'(?<![\w.>])' + var + r'\b')
            if len(use.findall(rhs)) != 1 or use.search(tail['lhs']):
                continue
            if not re.search(rf'(?m)^[ \t]*{FLOAT}\s+{var}\s*;', clean[opening:arms[0][0]]):
                continue
            # the variable carries nothing in or out: its declaration, one literal per arm and the tail's use
            mentions = [m.start() for m in use.finditer(clean, opening, end)]
            sets = []
            for a, b in arms:
                found = [s for s in (_statements(clean, a, b) or []) if s and re.match(var + r'\s*=(?!=)', clean[s[0]:s[1]])]
                sets.append(found)
            if any(len(found) != 1 for found in sets) or len(mentions) != 4:
                continue
            literals = [re.fullmatch(var + r'\s*=\s*(' + LITERAL + r')\s*;', clean[f[0][0]:f[0][1]]) for f in sets]
            if not all(literals):
                continue
            edits = [(closing, closing + tail.end(), '')]
            for (a, b), found, literal in zip(arms, sets, literals):
                value = literal[1]
                statement = re.sub(r'(?<![\w.>])' + var + r'\b', lambda _m, v=value: v, rhs)
                lhs = source[closing + tail.start('lhs'):closing + tail.end('lhs')].strip()
                line = clean.rfind('\n', 0, b) + 1
                indent = re.match(r'[ \t]*', source[clean.rfind('\n', 0, found[0][0]) + 1:])[0]
                edits.append((line, line, f'{indent}{lhs} = {statement.strip()};\n'))
                start = clean.rfind('\n', 0, found[0][0]) + 1
                stop = clean.find('\n', found[0][1]) + 1
                if clean[start:found[0][0]].strip() or clean[found[0][1]:stop].strip():
                    edits = None
                    break
                edits.append((start, stop, ''))
            if not edits:
                continue
            text = source
            for x, y, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
                text = text[:x] + new + text[y:]
            result.append((FAMILIES[0], text))
            if len(result) >= LIMIT:
                return result
    return result
