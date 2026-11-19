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
WHILE = re.compile(r'\}\s*while\s*\(\s*\(u32\)\s*\((?P<count>' + IDENT + r') & (?P<mask>0xFFFF|0xFF)\)\s*<\s*'
                   r'(?P<limit>0x[0-9a-fA-F]+|\d+)U?\s*\)\s*;|\}\s*while\s*\(\s*\((?P<count2>' + IDENT + r') & '
                   r'(?P<mask2>0xFFFF|0xFF)\)\s*<\s*(?P<limit2>0x[0-9a-fA-F]+|\d+)U?\s*\)\s*;')
STEP = r'(?:\+\+{v}|{v}\+\+|{v} \+= 1|{v} = {v} \+ 1)\s*;'


def _assigned(var, text):
    return re.search(r'(?<![\w.>])' + var + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + var + r'\b|\b' + var
                     + r'\s*(?:\+\+|--)', text)


def _loops(clean, opening, end):
    """(do_start, body_start, body_end, while_end, count, mask, limit) for each `do { } while ((u32)(c & M) < N);`."""
    for do in re.finditer(r'\bdo\s*\{', clean[opening:end]):
        start = opening + do.start()
        brace = opening + do.end() - 1
        closing = close(clean, brace, '{', '}')
        if not closing:
            continue
        hit = WHILE.match(clean, closing - 1)
        if not hit:
            continue
        count, mask, limit = (hit['count'], hit['mask'], hit['limit']) if hit['count'] else \
            (hit['count2'], hit['mask2'], hit['limit2'])
        yield start, brace + 1, closing - 1, hit.end(), count, mask, limit


def _line_start(text, at):
    return text.rfind('\n', 0, at) + 1


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
    for start, body_start, body_end, while_end, count, mask, limit in _loops(clean, opening, end):
        body = clean[body_start:body_end]
        kind = 'u16' if mask == '0xFFFF' else 'u8'
        # the counter starts at 0: its last store before the loop
        stores = re.findall(r'(?<![\w.>])' + count + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)\s*([^;]*);', clean[opening:start])
        if not stores or stores[-1].strip() != '0':
            continue
        steps = list(re.finditer(r'(?m)^[ \t]*' + STEP.format(v=count) + r'[ \t]*\n', body))
        if len(steps) != 1:
            continue
        rest = body[:steps[0].start()] + body[steps[0].end():]
        # the copy one step behind (`x = 0 & M;` before the loop, `x = count & M;` in it), if m2c made one
        copy = None
        before_line = clean[_line_start(clean, start - 1) if start else 0:start]
        prior = re.search(r'(?m)^[ \t]*(' + IDENT + r') = 0 & ' + mask + r';[ \t]*\n[ \t]*$', clean[opening:start])
        if prior:
            update = re.search(r'(?m)^[ \t]*' + prior[1] + r' = ' + count + ' & ' + mask + r';[ \t]*\n', rest)
            if update:
                copy = prior[1]
                rest = rest[:update.start()] + rest[update.end():]
                if _assigned(copy, rest):
                    continue
        # every other use of the counter is its masked value
        masked = r'\(?\s*' + count + r' & ' + mask + r'\s*\)?'
        plain = re.sub(r'\(\s*' + count + r' & ' + mask + r'\s*\)|' + count + r' & ' + mask, '__repair_i', rest)
        if re.search(r'\b' + count + r'\b', plain) or _assigned('__repair_i', plain):
            continue
        del masked, before_line
        if copy:
            plain = re.sub(r'(?<![\w.>])' + copy + r'\b', '__repair_i', plain)
        # rebuild from the source text with the same edits, keeping its spelling
        raw = source[body_start:body_end]
        raw_rest = raw[:steps[0].start()] + raw[steps[0].end():]
        if copy:
            update = re.search(r'(?m)^[ \t]*' + copy + r' = ' + count + ' & ' + mask + r';[ \t]*\n', raw_rest)
            raw_rest = raw_rest[:update.start()] + raw_rest[update.end():]
        raw_rest = re.sub(r'\(\s*' + count + r' & ' + mask + r'\s*\)|' + count + r' & ' + mask, '__repair_i', raw_rest)
        if copy:
            raw_rest = re.sub(r'(?<![\w.>])' + copy + r'\b', '__repair_i', raw_rest)
        indent = re.match(r'[ \t]*', clean[_line_start(clean, start):])[0]
        loop = (f'{{\n{indent}    {kind} __repair_i;\n'
                f'{indent}    for (__repair_i = 0; __repair_i < {limit}; __repair_i++) {{\n'
                + ''.join(f'{indent}        {line.strip()}\n' for line in raw_rest.splitlines() if line.strip())
                + f'{indent}    }}\n{indent}}}')
        text = source[:start] + loop + source[while_end:]
        if copy:  # m2c's `x = 0 & M;` before the loop goes with it
            text = re.sub(r'(?m)^[ \t]*' + copy + r' = 0 & ' + mask + r';[ \t]*\n(?=[ \t]*\{\n[ \t]*' + kind
                          + r' __repair_i;)', '', text, count=1)
        text = _drop_dead_counter(text, name, count)
        result.append((FAMILY, text))
        if (dropped := _drop_unset_arguments(text, name)) is not None:
            result.append((FAMILY, dropped))
        if len(result) >= 4:
            break
    return result


def _drop_dead_counter(source, name, count):
    """m2c's counter, when only its zeroing is left: the store and its declaration go."""
    span = find(source, name)
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    mentions = re.findall(r'(?<![\w.>])' + count + r'\b', body)
    stores = re.findall(r'(?m)^[ \t]*' + count + r' = 0;[ \t]*\n', body)
    declared = re.findall(r'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+|signed\s+)?\w+[\s*]+' + count + r'\s*;[ \t]*\n', body)
    if len(mentions) != len(stores) + len(declared):
        return source
    text = source[:span[0]] + re.sub(r'(?m)^[ \t]*' + count + r' = 0;[ \t]*\n', '', source[span[0]:span[1]]) + source[span[1]:]
    span = find(text, name)
    return text[:span[0]] + re.sub(r'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+|signed\s+)?\w+[\s*]+' + count
                                   + r'\s*;[ \t]*\n', '', text[span[0]:span[1]], count=1) + text[span[1]:]


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
