"""Four m2c shapes from functions an N64 game's deep passes left unimproved, each written back as the game had it.

- `negated_flag_return`: `v = 1; if (!(C)) { return 0; } return v;` -- m2c's reading of `return C;`. gcc keeps the
  1 in a register and branches the other way (91% so; exact as `if (C) { return 1; } return 0;`).
- `early_base_local`: a pointer read from a parameter, `M2C_FIELD(arg0, void **, 0x6C)`, used once as the base of a
  later test. gcc 2.7.2 loads it before the first test when the C read it into a local at the top (a 93% function
  exact so, after `call_into_arms`).
- `hardware_register_store`: a store to a symbol in the uncached I/O window (`D_A4500000 = x;`). The SDK writes those
  registers through constant volatile pointers (`IO_WRITE`), so gcc forms the address in a register, not `$at`
  (99.5% -> exact; the judge links the constant to the same bytes as the symbol).
- `used_before_set`: `LV = (... T ...); T = LV;` with `T` read before anything sets it -- m2c's name for the old value
  of `LV`, read in place (`LV = LV + (x - LV) * k;`). The C read an unset variable; the game read the field (exact).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

NEGATED = 'negated_flag_return'
EARLY_BASE = 'early_base_local'
HARDWARE = 'hardware_register_store'
USED_BEFORE_SET = 'used_before_set'
FAMILIES = (NEGATED, EARLY_BASE, HARDWARE, USED_BEFORE_SET)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


def _function(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (span, clean, opening, end) if end else None


def variants(source, name):
    found = _function(source, name)
    if not found:
        return []
    result = []
    for family, maker in ((NEGATED, _negated), (EARLY_BASE, _early_base), (HARDWARE, _hardware),
                          (USED_BEFORE_SET, _used_before_set)):
        for text in maker(source, name, *found):
            if text != source and text not in [t for _, t in result]:
                result.append((family, text))
    return result[:6]


def _negated(source, name, span, clean, opening, end):
    found = []
    pattern = re.compile(r'(?m)^(?P<i>[ \t]*)(?P<v>' + IDENT + r')\s*=\s*(?P<k>' + NUMBER + r')\s*;[ \t]*\n'
                         r'[ \t]*if\s*\(\s*!\s*\(')
    for hit in pattern.finditer(clean, opening, end):
        var, value = hit['v'], hit['k']
        cond_open = clean.index('(', clean.index('!', hit.end() - 3))
        cond_close = close(clean, cond_open)
        outer_close = close(clean, clean.rindex('(', hit.start(), cond_open))
        if not cond_close or not outer_close:
            continue
        arm = re.match(r'\s*\{\s*return\s+(?P<other>' + NUMBER + r')\s*;\s*\}\s*return\s+' + var + r'\s*;\s*\}\s*$',
                       clean[outer_close:end])
        if not arm:
            continue
        # the variable is used nowhere else in the function
        if len(re.findall(r'(?<![\w.>])' + var + r'\b', clean[opening:end])) != 3:
            continue
        condition = source[cond_open + 1:cond_close - 1]
        indent = hit['i']
        text = (source[:hit.start()] + f'{indent}if ({condition}) {{\n{indent}    return {value};\n{indent}}}\n'
                f'{indent}return {arm["other"]};\n}}' + source[end:])
        found.append(_drop_declaration(text, name, var))
    return found


def _drop_declaration(text, name, var):
    found = _function(text, name)
    if not found:
        return text
    _, clean, opening, end = found
    if len(re.findall(r'(?<![\w.>])' + var + r'\b', clean[opening:end])) != 1:
        return text
    declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', clean[opening:end])
    return text if not declared else text[:opening + declared.start()] + text[opening + declared.end():]


def _early_base(source, name, span, clean, opening, end):
    signature = clean[span[0]:opening]
    params = set(re.findall(r'(' + IDENT + r')\s*(?=[,)])', signature[signature.rfind('('):]))
    found = []
    inner = re.compile(r'M2C_FIELD\(\s*M2C_FIELD\(\s*(?P<p>' + IDENT + r')\s*,\s*void\s*\*\*\s*,\s*(?P<o>' + NUMBER
                       + r')\s*\)\s*,')
    body = clean[opening:end]
    first_if = re.search(r'\bif\s*\(', body)
    for hit in inner.finditer(body):
        # (not in the first test: reading that one early changes nothing)
        first_close = close(body, first_if.end() - 1) if first_if else None
        if hit['p'] not in params or not first_close or hit.start() < first_close:
            continue
        load = f'M2C_FIELD({hit["p"]}, void **, {hit["o"]})'
        # used once, inside an `if` condition that isn't the function's first, and the parameter is never assigned
        written = re.escape('M2C_FIELD(') + r'\s*' + hit['p'] + r'\s*,\s*void\s*\*\*\s*,\s*' + re.escape(hit['o']) + r'\s*\)'
        if len(re.findall(written, body)) != 1 or re.search(r'(?<![\w.>=!<])' + hit['p'] + r'\s*=(?!=)', body):
            continue
        line = body.rfind('\n', 0, hit.start())
        if not re.match(r'\s*if\s*\(', body[line + 1:]):
            continue
        at = opening + hit.start() + len('M2C_FIELD(')
        stop = at + re.match(written, clean[at:]).end()
        text = (source[:opening + 1] + f'\n    void *__repair_base = {load};' + source[opening + 1:at]
                + '__repair_base' + source[stop:])
        found.append(text)
    return found[:2]


def _hardware(source, name, span, clean, opening, end):
    found = []
    outside = clean[:span[0]] + clean[span[1]:]
    for symbol in sorted(set(re.findall(r'\bD_(A[0-9A-F]{7}|B[0-9A-F]{7})\b', clean[opening:end]))):
        address = int(symbol, 16)
        if not 0xA0000000 <= address < 0xC0000000:
            continue
        declared = re.search(r'extern\s+(?:volatile\s+)?(?P<t>[\w ]+?)\s+D_' + symbol + r'\s*;', outside)
        kind = declared['t'].strip() if declared else 's32'
        text = source
        stores = list(re.finditer(r'(?<![\w.>*&])D_' + symbol + r'(?=\s*=(?!=))', _blank(text)))
        if not stores:
            continue
        for m in reversed(stores):
            text = text[:m.start()] + f'*(volatile {kind} *)0x{symbol}' + text[m.end():]
        found.append(text)
    return found


def _used_before_set(source, name, span, clean, opening, end):
    found = []
    pattern = re.compile(r'(?m)^(?P<i>[ \t]*)(?P<lv>[^;{}\n=]+?)\s*=(?!=)(?P<rhs>[^;{}]*);[ \t]*\n'
                         r'[ \t]*(?P<t>' + IDENT + r')\s*=\s*(?P<back>[^;{}\n]+?)\s*;[ \t]*\n')
    for hit in pattern.finditer(clean, opening + 1, end):
        var, lv, back = hit['t'], hit['lv'].strip(), hit['back'].strip()
        if ' '.join(lv.split()) != ' '.join(back.split()) or not re.search(r'(?<![\w.>])' + var + r'\b', hit['rhs']):
            continue
        before = clean[opening:hit.start()]
        later = clean[hit.end():end]
        # read before anything sets it (its declaration only), and nothing reads it afterwards
        if re.search(r'(?<![\w.>])' + var + r'\s*=(?!=)', before) or re.search(r'(?<![\w.>])' + var + r'\b', later):
            continue
        lv_raw = source[hit.start('lv'):hit.end('lv')].strip()
        rhs = source[hit.start('rhs'):hit.end('rhs')]
        rhs = re.sub(r'(?<![\w.>])' + var + r'\b', '(' + lv_raw + ')', rhs)
        text = source[:hit.start()] + f'{hit["i"]}{lv_raw} ={rhs};\n' + source[hit.end():]
        found.append(_drop_declaration(text, name, var))
    return found
