"""Pointers and byte offsets stepped beside a loop counter, written as the counter times the stride.

m2c turns a table walk into a counter and companions that step with it:

    j = 0; k = &D_800E6A84; f = 0;
    do { ... *k ... *(D_800E5AC4 + f) ...; k += 0xFF8; j++; f += 0xFF8; } while (8U > j);

gcc makes those companions itself from `D_800E6A84[j * 0xFF8]` (loop.c strength reduction): the induction variables
are created after the loop's invariant constants are hoisted, so the preheader reads `li $fp,-1`, `lui`/`addiu` the
base, `move $s2,$zero`. The m2c form already has the companions before the loop, so a hoisted constant lands after
them: a MIPS function with this loop was 535 and, with every companion written off the counter, 475 (420 with the
rest of its edits), the target's order of preheader instructions.

Each companion `v` that starts at an expression and steps by a constant `S` as the loop's last statements, and is
not read after the loop, becomes `INIT + j * S` at its uses (a pointer through `(char *)`), with its initialisation
and step dropped. The counter must start at 0 and step by 1 as another of those last statements, and the
initialisations must be the statements right before the loop. Offered with every companion rewritten and, when
there are several, each one alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'counter_companion'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|\d+)U?'
STEP = re.compile(r'(?:(?P<name>' + IDENT + r')\s*\+=\s*(?P<stride>' + NUM + r')'
                  r'|(?P<name2>' + IDENT + r')\s*=\s*(?P=name2)\s*\+\s*(?P<stride2>' + NUM + r'))\s*;')
COUNT = re.compile(r'(?:(?P<a>' + IDENT + r')\s*(?:\+\+|\+=\s*1U?|=\s*(?P=a)\s*\+\s*1U?)|\+\+\s*(?P<b>' + IDENT + r'))\s*;')
INIT = re.compile(r'(?P<name>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}]+);')
INITS = re.compile(r'(?:[ \t\n]*' + IDENT + r'\s*=(?!=)[^;{}]+;)+[ \t\n]*$')


def _tail(body):
    """The trailing run of step statements of a loop body: (start, name, stride or None) in order."""
    steps, end = [], len(body.rstrip())
    while end > 0:
        text = body[:end]
        start = max(text.rfind(';', 0, end - 1), text.rfind('{'), text.rfind('}')) + 1
        statement = text[start:].strip()
        count, step = COUNT.fullmatch(statement), STEP.fullmatch(statement)
        if count:
            steps.append((start + len(text[start:]) - len(text[start:].lstrip()), count['a'] or count['b'], None))
        elif step:
            steps.append((start + len(text[start:]) - len(text[start:].lstrip()), step['name'] or step['name2'],
                          step['stride'] or step['stride2']))
        else:
            break
        end = start
    return steps[::-1]


def _loops(clean, opening, end):
    for loop in re.finditer(r'\bdo\s*\{', clean[opening:end]):
        start = opening + loop.start()
        body_open = opening + loop.end() - 1
        body_end = close(clean, body_open, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:end]) if body_end else None
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        if cond_end and re.match(r'\s*;', clean[cond_end:end]):
            yield start, body_open, body_end, cond_open, cond_end


def _removal(clean, a, b):
    """The span of a dropped statement: its whole line when nothing else is on it, else the space before it."""
    line = clean.rfind('\n', 0, a) + 1
    alone = not clean[line:a].strip()
    tail = re.match(r'[ \t]*(?:\n|$)', clean[b:])
    if alone and tail:
        return line, b + tail.end()
    if alone:
        return a, b + len(re.match(r'[ \t]*', clean[b:]).group())
    return a - (len(clean[:a]) - len(clean[:a].rstrip(' \t'))), b


def _value(var, base, stride, counter, pointer):
    scaled = f'{counter} * {stride}'
    if pointer:
        return f'((char *) ({base}) + {scaled})'
    return f'({scaled})' if base in ('0', '0U') else f'({base} + {scaled})'


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
    for start, body_open, body_end, cond_open, cond_end in _loops(clean, opening, end):
        body = clean[body_open + 1:body_end - 1]
        steps = _tail(body)
        counters = [s for s in steps if s[2] is None]
        if len(counters) != 1 or len({s[1] for s in steps}) != len(steps):
            continue
        counter = counters[0][1]
        region = INITS.search(clean, opening, start)
        if not region or clean[opening:region.start()].rstrip()[-1:] not in (';', '{', '}') \
                or not re.search(r'\b' + counter + r'\b', clean[cond_open:cond_end]):
            continue
        inits = {hit['name']: hit for hit in INIT.finditer(clean, region.start(), start)}
        if inits.get(counter) is None or inits[counter]['value'].strip() not in ('0', '0U'):
            continue
        first = body_open + 1 + steps[0][0]
        after = clean[body_end:end]
        companions = []
        for position, var, stride in steps:
            init = inits.get(var)
            if stride is None or init is None:
                continue
            declared = re.search(r'(?m)^[ \t]*[A-Za-z_][\w ]*?(\*?)[ \t]*\b' + var + r'[ \t]*;', clean[opening:region.start()])
            word = r'\b' + var + r'\b'
            if (not declared or re.search(word, after) or re.search(word, clean[cond_open:cond_end])
                    or re.search(r'&\s*' + var + r'\b', clean[opening:end])
                    or re.search(r'(?<![\w.>])' + var + r'\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + var + r'\b|\b'
                                 + var + r'\s*(?:\+\+|--)', clean[body_open + 1:first])
                    or len(re.findall(word, region.group())) != 1):
                continue
            companions.append((var, stride, init, bool(declared[1])))
        if not companions:
            continue
        for group in [companions] + ([[c] for c in companions] if len(companions) > 1 else []):
            edits = []
            for var, stride, init, pointer in group:
                value = _value(var, init['value'].strip(), stride, counter, pointer)
                for use in re.finditer(r'(?<![\w.>])' + var + r'\b', clean[body_open + 1:first]):
                    edits.append((body_open + 1 + use.start(), body_open + 1 + use.end(), value))
                for position, name_, _ in steps:
                    if name_ == var:
                        at = body_open + 1 + position
                        edits.append((*_removal(clean, at, clean.index(';', at) + 1), ''))
                edits.append((*_removal(clean, init.start(), init.end()), ''))
            text = source
            for a, b, v in sorted(edits, reverse=True):
                text = text[:a] + v + text[b:]
            result.append((FAMILY, text))
    return result
