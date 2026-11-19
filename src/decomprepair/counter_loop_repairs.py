"""m2c's masked counter loop, written as the `u16` (or `u8`) `for` loop it came from.

A loop over a `u16` counter comes back from m2c as two variables, the counter and its masked copy, with the copy
updated one step behind:

    var_s0 = 0;
    var_a0 = 0 & 0xFFFF;
    do {
        func_80011938(var_a0, 0);
        var_a0 = var_s0 & 0xFFFF;
        ++var_s0;
    } while ((u32) (var_s0 & 0xFFFF) < 4U);

gcc 2.7.2 builds that with an extra masked register; the game's `u16 i; for (i = 0; i < 4; i++) f(i, 0);` keeps one.
When the masked copy was also passed on after the loop (`func_800283B0(var_a0);`), that argument was never really
there: the game called with whatever `$a0` held, so the second proposal also drops arguments the C never sets. An N64
function was 92% as m2c wrote it, 90% with the loop alone (a register more for the unset argument) and exact with both.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'u16_counter_loop'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
LOOP = re.compile(
    r'(?m)^(?:(?P<indent>[ \t]*)(?P<init>' + IDENT + r') = 0;[ \t]*\n)?'
    r'(?P<indent2>[ \t]*)(?P<copy>' + IDENT + r') = 0 & (?P<mask>0xFFFF|0xFF);[ \t]*\n'
    r'[ \t]*do \{[ \t]*\n'
    r'(?P<body>(?:(?![ \t]*\} while).*\n)*?)'
    r'[ \t]*(?P=copy) = (?P<count>' + IDENT + r') & (?P=mask);[ \t]*\n'
    r'[ \t]*(?:\+\+(?P=count)|(?P=count)\+\+|(?P=count) \+= 1);[ \t]*\n'
    r'[ \t]*\} while \(\(u32\) \((?P=count) & (?P=mask)\) < (?P<limit>0x[0-9a-fA-F]+|\d+)U?\);[ \t]*\n')


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
    for hit in LOOP.finditer(clean, opening, end):
        copy, count = hit['copy'], hit['count']
        if hit['init'] not in (None, count):
            continue
        # (the counter starts at 0: zeroed on the line before, or earlier with nothing changing it on the way)
        before = clean[opening:hit.start()]
        stores = re.findall(r'(?<![\w.>])' + count + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)\s*([^;]*);', before)
        if hit['init'] is None and (not stores or stores[-1].strip() != '0'):
            continue
        body = source[hit.start('body'):hit.end('body')]
        if re.search(r'\b' + count + r'\b', body) or re.search(r'(?<![\w.>])' + copy + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)',
                                                               body):
            continue  # the counter itself is used, or the copy changes: not this shape
        kind = 'u16' if hit['mask'] == '0xFFFF' else 'u8'
        indent = hit['indent'] if hit['init'] is not None else hit['indent2']
        inner = re.sub(r'(?<![\w.>])' + copy + r'\b', '__repair_i', body)
        loop = (f'{indent}{{\n{indent}    {kind} __repair_i;\n'
                f'{indent}    for (__repair_i = 0; __repair_i < {hit["limit"]}; __repair_i++) {{\n'
                + ''.join(f'{indent}        {line.strip()}\n' for line in inner.splitlines() if line.strip())
                + f'{indent}    }}\n{indent}}}\n')
        text = source[:hit.start()] + loop + source[hit.end():]
        result.append((FAMILY, text))
        if (dropped := _drop_unset_arguments(text, name)) is not None:
            result.append((FAMILY, dropped))
    return result[:4]


def _drop_unset_arguments(source, name):
    """The C with trailing call arguments that are locals never assigned taken out (their callee's prototype then takes
    any arguments), or None when there are none."""
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}')
    body = clean[opening:end]
    declared = re.findall(r'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+|signed\s+)?\w+[\s*]+(' + IDENT + r')\s*;', body)
    unset = [v for v in declared if not re.search(r'(?<![\w.>])' + v + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*' + v + r'\b'
                                                  r'|(?:\+\+|--)\s*' + v + r'\b|\b' + v + r'\s*(?:\+\+|--)', body)]
    text = source
    changed = False
    for var in unset:
        for call in reversed(list(re.finditer(r'\b(' + IDENT + r')\s*\(([^()]*)\)\s*;', _blank(text)))):
            if not span[0] <= call.start() or call[1] == name:
                continue
            args = [a.strip() for a in call[2].split(',')] if call[2].strip() else []
            if not args or args[-1] != var:
                continue
            kept = ', '.join(args[:-1])
            at = call.start(2)
            text = text[:at] + kept + text[call.end(2):]
            # the callee's prototype no longer says how many: as m2c's unknown callees are
            text = re.sub(r'(?m)^(.*\b' + re.escape(call[1]) + r')\s*\([^()]*\)(\s*;)', r'\1()\2', text, count=1)
            changed = True
    if not changed:
        return None
    # the unset local itself goes when nothing mentions it any more
    for var in unset:
        if len(re.findall(r'(?<![\w.>])' + var + r'\b', _blank(text))) == 1:
            text = re.sub(r'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+|signed\s+)?\w+[\s*]+' + var + r'\s*;[ \t]*\n', '', text,
                          count=1)
    return text
