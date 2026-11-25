"""A value computed from a variable that is never read again, kept in that variable instead of m2c's new temporary.

m2c names each new value: the end of an N64 CRC routine came back as

    temp_a2 = ~var_a2;
    ret = ((temp_a2 << 8) | ((temp_a2 >> 8) & 0xFF)) & 0xFFFF;

and gcc 2.7.2 gave the temporary a register of its own, where the game kept writing `var_a2`'s (99.1%). Written
back into `var_a2`, and the swap stored there too before the mask, it was exact:

    var_a2 = ~var_a2;
    var_a2 = (var_a2 << 8) | ((var_a2 >> 8) & 0xFF);
    ret = var_a2 & 0xFFFF;

Offered when the temporary is assigned once, from an expression of one other local that nothing reads after it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'source_variable_reuse'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
ASSIGN = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<temp>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}]*);[ \t]*\n')


def _mentions(text, name):
    return re.findall(r'(?<![\w.>])' + re.escape(name) + r'\b', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    declared = {v: t for t, v in re.findall(r'(?m)^[ \t]*((?:unsigned\s+|signed\s+)?\w+)[ \t]+(' + IDENT + r')\s*;',
                                            body)}
    result = []
    for hit in ASSIGN.finditer(clean, opening + 1, end):
        temp, value = hit['temp'], hit['value']
        if temp not in declared or len(re.findall(r'(?<![\w.>])' + re.escape(temp) + r'\s*=(?!=)', body)) != 1:
            continue
        sources = [v for v in dict.fromkeys(re.findall(r'(?<![\w.>])(' + IDENT + r')\b', value)) if v in declared]
        if len(sources) != 1 or sources[0] == temp or re.search(r'\b' + IDENT + r'\s*\(', value):
            continue
        var = sources[0]
        if declared[var] != declared[temp]:
            continue
        after = clean[hit.end():end]
        if _mentions(after, var) or re.search(r'&\s*' + re.escape(var) + r'\b', body):
            continue  # the source variable is read again: its value is still needed
        # inside the same block: the assignment's own block must contain every later use of the temporary
        block_end = _block_end(clean, hit.end(), end)
        if _mentions(clean[block_end:end], temp):
            continue
        rewritten = source[:hit.start('temp')] + var + source[hit.end('temp'):hit.end()] + re.sub(
            r'(?<![\w.>])' + re.escape(temp) + r'\b', var, source[hit.end():block_end]) + source[block_end:]
        result.append((FAMILY, rewritten))
        # the masked use split in two, the value stored back before the mask
        rest = _blank(rewritten)
        nxt = ASSIGN.match(rest, rest.find('\n', hit.start()) + 1)  # (the line start doesn't move)
        mask = re.fullmatch(r'\s*\((?P<inner>.*)\)\s*&\s*(?P<m>0[xX][0-9a-fA-F]+|\d+)[uU]?\s*', nxt['value']) if nxt else None
        if mask and _mentions(mask['inner'], var) and nxt['temp'] != var and close(nxt['value'], nxt['value'].index('(')) == \
                nxt['value'].rindex(')') + 1:
            inner = rewritten[nxt.start('value'):nxt.end('value')]
            inner = inner[inner.index('(') + 1:inner.rindex(')')]
            split = (rewritten[:nxt.start()] + nxt['indent'] + var + ' = ' + inner.strip() + ';\n' + nxt['indent']
                     + nxt['temp'] + ' = ' + var + ' & ' + mask['m'] + ';\n' + rewritten[nxt.end():])
            result.append((FAMILY, split))
        if len(result) >= 4:
            break
    return result


def _python_block_end(clean, at, end):
    depth = 0
    for i in range(at, end):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth < 0:
            return i
    return end


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, at, end):
        found = _scan.enclosing_end(clean, at, end, end)
        return _python_block_end(clean, at, end) if found is NotImplemented else found
