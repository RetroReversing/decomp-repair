"""An earlier rewrite's `__repair_result_NAME` copy, put back as NAME, and a constant initializer moved into its guard.

A repair once split a variable into `__repair_result_var_s1`, declared without a value and set only on one path, so
the C read an uninitialised local where the game's variable was set to 0 first. Put back, the variable is set before
the `if` that guards everything reading it; the game set it there inside the guard (in the branch's delay slot): an N64
function was exact with `var_s1 = 0;` as the guarded block's first statement. Offered: the copy undone, and that with
an initializer `v = CONSTANT;` right before an `if (...) {` moved into the block when nothing after the block reads v.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'result_debris'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def _undo(source):
    names = set(re.findall(r'\b__repair_result_(' + IDENT + r')\b', source))
    text = source
    for name in names:
        if not re.search(r'(?m)^[ \t]*[\w ]+?[\s*]+' + name + r'\s*;', text):
            continue
        text = re.sub(r'(?m)^[ \t]*[\w ]+?[\s*]+__repair_result_' + name + r'\s*;[ \t]*\n', '', text)
        text = re.sub(r'\b__repair_result_' + name + r'\b', name, text)
    return text


def _guarded(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for m in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<var>' + IDENT + r')\s*=\s*(?P<value>-?(?:0[xX][0-9a-fA-F]+|\d+))'
                         r'\s*;[ \t]*\n(?P<if>[ \t]*if\s*\()', clean[opening:end]):
        cond_open = opening + m.start('if') + m.group('if').index('(')
        cond_close = close(clean, cond_open)
        block = re.match(r'\s*\{', clean[cond_close:end]) if cond_close else None
        if not block or re.search(r'\b' + m['var'] + r'\b', clean[cond_open:cond_close]):
            continue
        block_open = cond_close + block.end() - 1
        block_close = close(clean, block_open, '{', '}')
        if not block_close or re.match(r'\s*else\b', clean[block_close:end]) \
                or re.search(r'(?<![\w.>])' + m['var'] + r'\b', clean[block_close:end]):
            continue
        line = source[opening + m.start():opening + m.start('if')]
        inner = re.match(r'[ \t]*', source[block_open + 1:].lstrip('\n'))[0]
        text = (source[:opening + m.start()] + source[opening + m.start('if'):block_open + 1] + '\n' + inner
                + line.strip() + source[block_open + 1:])
        out.append(text)
    return out


def variants(source, name):
    result = []
    undone = _undo(source)
    for text in ([undone] if undone != source else []) + _guarded(undone, name):
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result[:3]
