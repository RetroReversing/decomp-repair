"""A counter kept in a word's low bits, stepped with the field read first and into its own local.

m2c reads the word once and writes `t = *p; *p = (t & 0xF8) | ((t & 7) - 1);`. The game took the field first,
`n = *p & 7; *p = (*p & 0xF8) | (n - 1);`: cse still loads the word once, but the `andi 7` comes first and keeps its
register through the `addiu`, with the kept bits in the other (35 -> 0 on a 145-instruction state switch, KMC gcc 2.7.2
-O1). Offered when the local is read nowhere else, and for the same update with the read written inline (as
`reload_temp_inline` leaves it), where the field gets a local of its own type.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'low_field_step'
FAMILIES = (FAMILY,)
LIMIT = 4
LOCAL = '__repair_low'

I = r'[A-Za-z_]\w*'
K = r'(?:0x[0-9a-fA-F]+|\d+)'
LOAD = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<t>' + I + r')\s*=\s*(?P<value>[^=;\n][^;\n]*);[ \t]*\n[ \t]*(?P<lhs>[^;=\n]+?)\s*=(?!=)\s*(?P<rhs>[^;\n]+);')


def _bare(text):
    """An lvalue or read without spaces, redundant outer parentheses or a leading integer cast."""
    text = re.sub(r'\s+', '', text)
    while True:
        cast = re.match(r'\((?:u8|u16|u32|s8|s16|s32|int|unsignedshort|unsignedchar)\)', text)
        if cast:
            text = text[cast.end():]
        elif text.startswith('(') and close(text, 0) in (len(text), len(text) - 1):
            text = text[1:-1]
        else:
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
    for hit in LOAD.finditer(clean, opening, end):
        t = hit['t']
        value = source[hit.start('value'):hit.end('value')].strip()
        lhs = source[hit.start('lhs'):hit.end('lhs')].strip()
        rhs = source[hit.start('rhs'):hit.end('rhs')]
        if _bare(value) != _bare(lhs):
            continue
        keep = r'\(\s*' + t + r'\s*&\s*(?P<keep>' + K + r')\s*\)'
        step = r'\(\s*\(\s*' + t + r'\s*&\s*(?P<low>' + K + r')\s*\)\s*(?P<op>[-+])\s*(?P<by>' + K + r')\s*\)'
        shape = (re.search(keep + r'\s*\|\s*' + step, rhs) or re.search(step + r'\s*\|\s*' + keep, rhs))
        if not shape or len(re.findall(r'\b' + t + r'\b', rhs)) != 2:
            continue
        after = clean[hit.end():end]
        later = re.search(r'\b' + t + r'\b', after)
        if later and not re.match(r'\s*=(?!=)', after[later.end():]):
            continue
        new = f'({lhs} & {shape["keep"]}) | ({t} {shape["op"]} {shape["by"]})'
        text = (source[:hit.start()] + f'{hit["ind"]}{t} = {value} & {shape["low"]};\n'
                + source[hit.start('lhs') - len(hit['ind']):hit.start('rhs')] + rhs[:shape.start()] + new
                + rhs[shape.end():] + source[hit.end('rhs'):])
        result.append((FAMILY, text))
    result += _inline(source, clean, opening, end)
    return result[:LIMIT]


def _inline(source, clean, opening, end):
    """`*p = (*p & 0xF8) | ((*p & 7) - 1);` with the read already written inline: the field gets a local of its type."""
    result = []
    if LOCAL in clean:
        return result
    for hit in re.finditer(r'(?m)^(?P<ind>[ \t]*)(?P<lhs>[^;=\n]+?)\s*=(?!=)\s*(?P<rhs>[^;\n]+);', clean[opening:end]):
        start, stop = opening + hit.start('rhs'), opening + hit.end('rhs')
        lhs = source[opening + hit.start('lhs'):opening + hit.end('lhs')].strip()
        kind = re.search(r'\b(u8|u16|u32|s8|s16|s32)\s*\*', lhs)
        if not kind or '++' in lhs or '(' not in lhs:
            continue
        rhs = source[start:stop]
        # the outer `|` of the right side, after an optional cast
        cast = re.match(r'\(\s*(?:u8|u16|u32|s8|s16|s32)\s*\)\s*', rhs)
        head = cast[0] if cast else ''
        body = rhs[len(head):].strip()
        while body.startswith('(') and close(body, 0) in (len(body), len(body) - 1):
            body = body[1:-1].strip()
        parts = _split(body)
        if not parts:
            continue
        for keep_side, step_side in (parts, parts[::-1]):
            keep = _binary(keep_side, '&')
            step = _binary(step_side, '-+')
            if not keep or not step or not re.fullmatch(K, keep[2]) or not re.fullmatch(K, step[2]):
                continue
            field = _binary(step[0], '&')
            if not field or not re.fullmatch(K, field[2]) or _bare(keep[0]) != _bare(lhs) or _bare(field[0]) != _bare(lhs):
                continue
            ind = hit['ind']
            line = opening + hit.start()
            new = (f'{ind}{LOCAL} = {lhs} & {field[2]};\n'
                   f'{ind}{lhs} = {head}(({lhs} & {keep[2]}) | ({LOCAL} {step[1]} {step[2]}));')
            text = source[:line] + new + source[stop + 1:]
            text = text[:opening + 1] + f'\n    {kind[1]} {LOCAL};' + text[opening + 1:]
            result.append((FAMILY, text))
            return result
    return result


def _unwrapped(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) in (len(text), len(text) - 1):
        text = text[1:-1].strip()
    return text


def _top(text, operators):
    """Where the one-character operators stand outside every parenthesis (not part of `->`, `&&`, `||`)."""
    depth, found = 0, []
    for i, c in enumerate(text):
        depth += (c == '(') - (c == ')')
        if not depth and c in operators and i and text[i - 1:i + 1] != '||' and text[i:i + 2] not in ('->', '&&', '||'):
            found.append(i)
    return found


def _split(text):
    at = _top(text, '|')
    return (text[:at[0]].strip(), text[at[0] + 1:].strip()) if len(at) == 1 else None


def _binary(text, operators):
    """(left, operator, right) of an expression with exactly one top-level operator of these, else None."""
    text = _unwrapped(text)
    at = _top(text, operators)
    return (text[:at[-1]].strip(), text[at[-1]], text[at[-1] + 1:].strip()) if at else None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
