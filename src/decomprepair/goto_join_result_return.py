"""m2c's shared result jumped into from an earlier arm, written as `else if` with an early return.

The game picks a result in one of several arms and returns it, except that one arm's last test fails with another
value. m2c cannot say that, so it presets the result and jumps from the earlier arm into the test's body:

    if (kind == 4) {                           if (kind == 4) {
        A...                                       A...
        goto block_6;                          } else if (kind == 8) {
    }                                              B...
    v = index;                                     if (n >= K2) {
    if (kind == 8) {                                   return 0;
        v = 0;                                     }
        B...                            ->     }
        if (n < K2) {                          return index;
    block_6:
            v = index;
        }
    }
    return v;

KMC and SN GCC lay the draft out with the preset on the branch's path and one more join. On a 47-instruction N64 table
append (`sn-n64-281 -O2`) this rewrite took the machine draft from 850 to 650, and with `narrow_widening`,
`member_array_rows` and `statement_slide` after it the exact judge scored 0.

goto_join_result_return
    Needs: the guards (one or more `if (..) { ...; goto L; }` without `else`) directly before `v = r;`; then
    `if (c) { .. v = K; .. if (d) { L: v = r; } }` and `return v;` ending the function; `L` used by those gotos only;
    `v` named nowhere else; `r` a literal, or a local or parameter whose address is not taken, which neither `c` nor
    `d` writes, declared with `v`'s type; `K` a small literal that every integer type holds the same way.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close, negate

FAMILY = 'goto_join_result_return'
FAMILIES = (FAMILY,)

IF = re.compile(r'(?<![\w.>])if\s*\(')
JOIN = re.compile(rf'\s*(?P<result>{IDENT})\s*=\s*(?P<value>{IDENT}|{NUMBER})\s*;\s*(?=if\s*\()')
BRACE = re.compile(r'\s*\{')
ELSE = re.compile(r'\s*else\b')
LABEL = re.compile(rf'(?<=[;{{}}])\s*(?P<label>{IDENT})\s*:(?!:)\s*(?P<result>{IDENT})\s*=\s*(?P<value>{IDENT}|{NUMBER})\s*;\s*\Z')


def _if_block(clean, match):
    """(condition's `(`, past its `)`, block's `{`, past its `}`) of an `if` with a braced arm, or None."""
    opening = match.end() - 1
    closing = close(clean, opening)
    brace = closing and BRACE.match(clean, closing)
    end = brace and close(clean, brace.end() - 1, '{', '}')
    return (opening, closing, brace.end() - 1, end) if end else None


def _declared(clean, span_start, end, ident):
    """The single integer type `ident` is declared with in the signature or body, or None."""
    hits = re.findall(rf'(?<![\w.>])({INTEGER})\s+{ident}\s*(?=[;,)=])', clean[span_start:end])
    return ' '.join(hits[0].split()) if len(hits) == 1 else None


def variants(source, name):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    start = find(source, name)[0]
    ifs = {}
    for match in IF.finditer(clean, opening + 1, end):
        block = _if_block(clean, match)
        if block:
            ifs[match.start()] = block
    result = []
    for join in JOIN.finditer(clean, opening + 1, end):
        if clean[:join.start()].rstrip()[-1:] != '}':
            continue
        outer = ifs.get(join.end())
        if not outer:
            continue
        _, outer_cond_end, outer_open, outer_end = outer
        v, r = join['result'], join['value']
        if ELSE.match(clean, outer_end) or not re.fullmatch(rf'\s*return\s+{v}\s*;\s*\}}\s*', clean[outer_end:end]):
            continue
        inner = next((block for at, block in sorted(ifs.items(), reverse=True)
                      if outer_open < at < outer_end and re.fullmatch(r'\s*\}', clean[block[3]:outer_end])), None)
        if not inner:
            continue
        inner_at = max(at for at, block in ifs.items() if block == inner)
        labelled = LABEL.search(clean, inner[2] + 1, inner[3] - 1)
        if not labelled or labelled['result'] != v or labelled['value'] != r:
            continue
        label = labelled['label']
        # The guards: every `if` without `else` ending in `goto label;` that runs straight into the join.
        guards, at = [], len(clean[:join.start()].rstrip())
        while True:
            guard = next((block for block in ifs.values() if block[3] == at), None)
            if not guard:
                break
            jump = re.search(rf'(?<=[;{{}}])\s*goto\s+{label}\s*;\s*\}}\Z', clean[guard[2]:guard[3]])
            head = max(where for where, block in ifs.items() if block == guard)
            if not jump or re.search(r'\belse\s*\Z', clean[:head]):
                break
            guards.append((head, guard, guard[2] + jump.start(), guard[2] + jump.end() - 1))
            at = len(clean[:head].rstrip())
        guards.reverse()
        if not guards or len(re.findall(rf'\b{label}\b', part.body)) != len(guards) + 1:
            continue
        # `v` appears only in its declaration, the preset, the arm's constant, the labelled copy and the return.
        sets = list(re.finditer(rf'(?<![\w.>]){v}\s*=\s*(?P<constant>-?{NUMBER})\s*;', clean[outer_open:inner_at]))
        kind = _declared(clean, start, end, v)
        if not kind or len(sets) != 1 or len(re.findall(rf'(?<![\w.>]){v}\b', clean[start:end])) != 5:
            continue
        constant = sets[0]['constant']
        if not 0 <= int(re.sub(r'[uUlL]+$', '', constant.lstrip('-')), 0) <= 0x7F or constant.startswith('-'):
            continue
        set_at, set_end = outer_open + sets[0].start(), outer_open + sets[0].end()
        # The constant must be at the arm's own level: a nested one would not reach every path to the test.
        if clean[outer_open + 1:set_at].count('{') != clean[outer_open + 1:set_at].count('}'):
            continue
        if clean[:set_at].rstrip()[-1:] not in ';{}':
            continue
        if not re.fullmatch(NUMBER, r):
            conditions = clean[outer[0]:outer_cond_end] + clean[inner[0]:inner[1]]
            writes = rf'(?:\+\+|--|&)\s*{r}\b|(?<![\w.>]){r}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))'
            if (_declared(clean, start, end, r) != kind or re.search(rf'(?<![&\w])&\s*{r}\b', part.body)
                    or re.search(writes, conditions)):
                continue
        condition = source[inner[0] + 1:inner[1] - 1].strip()
        inverse = negate(condition) or f'!({condition})'

        indent = _indent(source, guards[0][0])
        inner_indent = _indent(source, inner_at)
        edits = []
        for index, (head, guard, jump_start, jump_end) in enumerate(guards):
            word = clean.index('goto', jump_start)
            semicolon = clean.index(';', word) + 1
            line = source.rfind('\n', 0, word) + 1
            stop = source.find('\n', semicolon) + 1
            alone = not source[line:word].strip() and not source[semicolon:stop].strip()
            edits.append((line, stop, '') if alone else (word, semicolon, ''))
            following = guards[index + 1][0] if index + 1 < len(guards) else None
            if following is not None:
                edits.append((guard[3], following, ' else '))
        edits.append((guards[-1][1][3], join.end(), ' else '))
        line = source.rfind('\n', 0, set_at) + 1
        stop = source.find('\n', set_end) + 1
        alone = not source[line:set_at].strip() and not source[set_end:stop].strip()
        edits.append((line, stop, '') if alone else (set_at, set_end, ''))
        edits.append((inner[0], inner[1], f'({inverse})'))
        edits.append((inner[2], inner[3], f'{{\n{inner_indent}    return {constant};\n{inner_indent}}}'))
        tail = re.compile(rf'return\s+{v}\s*;').search(clean, outer_end, end)
        edits.append((tail.start(), tail.end(), f'return {r};'))
        declaration = re.search(rf'^[ \t]*{INTEGER}\s+{v}\s*;[ \t]*\n', clean[opening:end], re.M)
        if declaration:
            edits.append((opening + declaration.start(), opening + declaration.end(), ''))
        text = edit(source, edits)
        if indent is not None and _blank(text).count('{') == _blank(text).count('}'):
            result.append((FAMILY, text))
    return result


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:at])[0]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300}
