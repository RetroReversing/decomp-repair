"""A constant m2c returned through the variable that holds the result, returned directly instead.

When several failure tests share one `return -1`, m2c writes the result into a variable and the constant over it:

    if ((a == 0xFF) || ... || (temp_v0 = g(...), var_v0 = temp_v0, (temp_v0 == -1))) {
        var_v0 = -1;
    }
    return var_v0;

gcc 2.7.2 then gives both values one register and copies the constant through it, one instruction more than the
game, whose source returned the constant where the tests fail. Returning it directly, and the value it was copied
from where m2c's copy is the variable's only other assignment, matched an N64 function exactly (the plain early
return alone was further off: 335 against 115). The rewrite keeps the meaning: the arm only stored the constant
that the function then returned.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'constant_exit_return'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


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
    # the function's last statements: if (...) { v = CONSTANT; } return v;
    tail = re.search(r'\{\s*(?P<var>' + IDENT + r')\s*=\s*(?P<value>' + NUMBER
                     + r')\s*;\s*\}\s*return\s+(?P=var)\s*;\s*\}\s*$', body)
    if not tail:
        return []
    var = tail['var']
    arm_open = opening + tail.start()
    arm_close = close(clean, arm_open, '{', '}')
    # the arm belongs to an `if (...)` right before it: walk back over its condition
    cond_close = len(clean[:arm_open].rstrip())
    if clean[cond_close - 1:cond_close] != ')':
        return []
    cond_open = _opening(clean, cond_close - 1)
    keyword = re.search(r'\bif\s*$', clean[:cond_open]) if cond_open is not None else None
    if not keyword:
        return []
    # a statement of the function's own block, not the body of an else or a loop
    before = clean[opening + 1:keyword.start()].rstrip()
    if before and before[-1] not in ';{}' or re.search(r'\belse\s*$', before):
        return []
    returned_at = clean.find('return', arm_close)
    value = ' '.join(source[opening + tail.start('value'):opening + tail.end('value')].split())
    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))

    arm = ' {\n' + _indent(source, arm_open) + '    return ' + value + ';\n' + _indent(source, arm_open) + '}'
    plain = source[:cond_close] + arm + source[arm_close:]
    emit(plain)
    # m2c's copy in the condition (`v = t,`) when it's the variable's only other assignment: return `t` instead
    condition = clean[cond_open:cond_close]
    copies = list(re.finditer(r'(?<![\w.>])' + var + r'\s*=\s*(?P<from>' + IDENT + r')\s*,\s*', condition))
    others = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', clean[opening:end])
              if not opening + m.start() in range(cond_open, cond_close)]
    # the declaration, the arm's store and the return itself are the only other mentions
    if len(copies) == 1 and len(others) == 3 and not re.search(r'&\s*' + var + r'\b', clean[opening:end]):
        copy = copies[0]
        origin = copy['from']
        declared = re.search(r'(?m)^[ \t]*(?:[\w ]+?)\s+\**' + var + r'\s*;[ \t]*\n', clean[opening:cond_open])
        if declared and not _assigned_after(clean[cond_open + copy.end():cond_close], origin):
            text = (source[:cond_open + copy.start()] + source[cond_open + copy.end():cond_close] + arm
                    + source[arm_close:returned_at] + 'return ' + origin + ';'
                    + source[clean.find(';', returned_at) + 1:])
            text = text[:opening + declared.start()] + text[opening + declared.end():]
            emit(text)
    return result


def _opening(text, closing):
    depth = 0
    for pos in range(closing, -1, -1):
        depth += (text[pos] == ')') - (text[pos] == '(')
        if depth == 0:
            return pos
    return None


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _assigned_after(text, name):
    return re.search(r'(?<![\w.>])' + name + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + name + r'\b|\b'
                     + name + r'\s*(?:\+\+|--)', text)
