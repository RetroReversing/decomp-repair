"""Two scaled fields of one packed index, written as plain extractions followed by in-place scales.

m2c writes the column and row of a glyph or tile index as one expression each:

    col = (index & 0xF) * 8;
    row = (index >> 4) * 8;

Compiled by KMC GCC 2.7.2 without scheduling, that merges each extraction with its scale (the row becomes one shift
and a mask). A target that shifts the row out and masks the column first, and multiplies each by 8 later in the same
register, was written in two steps, the high field first:

    row = index >> 4;
    col = index & 0xF;
    row *= 8;
    col *= 8;

On a 143-instruction N64 text-glyph display-list builder this step, with both locals `u16`, was the last one: the
one-expression form scored 265 under `-O1`, the split one 0. Both field orders are offered, with the locals' types as
written and as `u16`. The rewrite applies to adjacent statements whose mask is the bits below the shift. Proposals
only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find

FAMILY = 'field_extract_scale_split'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
VALUE = r'(?:\(\s*(?:u16|u32|s32|unsigned(?:\s+(?:short|int))?)\s*\)\s*)?(?P<value>' + IDENT + r')'
LOW = re.compile(r'^\(\s*' + VALUE + r'\s*&\s*(?P<mask>' + NUMBER + r')\s*\)\s*(?P<op>\*|<<)\s*(?P<scale>' + NUMBER
                 + r')$')
HIGH = re.compile(r'^\(\s*' + VALUE + r'\s*>>\s*(?P<shift>' + NUMBER + r')\s*\)\s*(?P<op>\*|<<)\s*(?P<scale>' + NUMBER
                  + r')$')
STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<target>' + IDENT + r')[ \t]*=(?!=)[ \t]*(?P<expr>[^;\n]+);[ \t]*\n')
DECLARATION = (r'(?m)^([ \t]*)(?:(?:unsigned|signed)\s+)?(?:char|short|int|long|[su](?:8|16|32))(?:\s+int)?[ \t]+'
               r'{name}[ \t]*;')


def _number(text):
    return int(text.rstrip('uU'), 0)


def _field(statement):
    expr = statement['expr'].strip()
    for kind, pattern in (('low', LOW), ('high', HIGH)):
        hit = pattern.match(expr)
        if hit:
            return kind, hit
    return None, None


def _pairs(clean, lo, hi):
    """(first statement, second statement, low part, high part) of each adjacent pair that splits one value."""
    statements = list(STATEMENT.finditer(clean, lo, hi))
    for first, second in zip(statements, statements[1:]):
        if clean[first.end():second.start()].strip():
            continue
        parts = {}
        for statement in (first, second):
            kind, hit = _field(statement)
            if kind:
                parts[kind] = (statement['target'], hit)
        if len(parts) != 2:
            continue
        (low_name, low), (high_name, high) = parts['low'], parts['high']
        value = low['value']
        if high['value'] != value or low_name == high_name or value in (low_name, high_name):
            continue
        if _number(low['mask']) != (1 << _number(high['shift'])) - 1:
            continue
        yield first, second, parts['low'], parts['high']


def _retyped(body, names):
    for name in names:
        pattern = re.compile(DECLARATION.format(name=re.escape(name)))
        if not pattern.search(body):
            return None
        body = pattern.sub(lambda m, var=name: m.group(1) + 'u16 ' + var + ';', body, count=1)
    return body


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result, seen = [], {source}
    for first, second, (low_name, low), (high_name, high) in _pairs(clean, span[0], span[1]):
        value, indent = low['value'], first['indent']
        take = {low_name: f"{low_name} = {value} & {low['mask']};",
                high_name: f"{high_name} = {value} >> {high['shift']};"}
        scale = {n: f"{n} {part['op']}= {part['scale']};" for n, part in ((low_name, low), (high_name, high))}
        for order in ((high_name, low_name), (low_name, high_name)):
            lines = [take[n] for n in order] + [scale[n] for n in order]
            text = ''.join(indent + line + '\n' for line in lines)
            child = source[:first.start()] + text + source[second.end():]
            at = find(child, name)
            body = _retyped(child[at[0]:at[1]], order) if at else None
            for option in (child[:at[0]] + body + child[at[1]:] if body else None, child):
                if option and option not in seen:
                    seen.add(option)
                    result.append((FAMILY, option))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
