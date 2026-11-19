"""An assignment m2c wrote twice because gcc copied it into a branch's delay slot.

When the block after an `if` starts with `v0 = arg0 * 2`, gcc 2.7.2 may fill the `beqz` delay slot with that
instruction and repeat it at the end of the taken arm, after a call clobbered `$v0`. m2c reads both copies:

    var_v0 = arg0 * 2;
    if (func_8008C1B0() & 0xFF) {
        func_8008C590(arg0);
        var_v0 = arg0 * 2;
    }
    ... var_v0 ...

The source computed it once, after the `if`. Kept as m2c wrote it, the value lives across the call in a saved
register, and an N64 function differed in 83 of 91 instructions. Moving it after the `if` is exact in meaning when
the value is plain arithmetic of variables that neither the condition nor the arm changes, and nothing but the
arm's last statement mentions the variable before it.

A comparison (`var_v0 = arg0 != 0`) is offered written where it's used as well, when that's once: carried in a
variable it stayed one, in a saved register, where the game computed it in the condition.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'delay_slot_duplicate'
FAMILIES = (FAMILY,)
# a value: no assignment (`=` alone) and no statement end; comparisons (`!=`, `==`, `<=`, `>=`) are values too
VALUE = r'(?:[^;=!<>]|[!<>=]=|[<>]|!(?!=))+'


def _assigned(name, text):
    return re.search(r'(?<![\w.>])' + name + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + name + r'\b|\b'
                     + name + r'\s*(?:\+\+|--)', text)


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
    pattern = r'(?m)^([ \t]*)(' + IDENT + r')\s*=(?!=)\s*(' + VALUE + r');[ \t]*\n[ \t]*if\s*\('
    for hit in re.finditer(pattern, clean[opening+1:end]):
        start = opening + 1 + hit.start()
        var, value = hit[2], hit[3].strip()
        # plain arithmetic of variables and numbers: no loads, calls or side effects
        if re.search(r'[*\[]\s*\(|->|\[|\(\s*\*|\b' + IDENT + r'\s*\(', value.replace(' * ', ' MUL ')) \
                or not re.fullmatch(r'[\w\s()+\-*/%&|^<>~!=]+', value) or '++' in value or '--' in value:
            continue
        cond_open = opening + 1 + hit.end() - 1
        cond_close = close(clean, cond_open)
        block = re.match(r'\s*{', clean[cond_close:end]) if cond_close else None
        if not block:
            continue
        block_open = cond_close + block.end() - 1
        block_close = close(clean, block_open, '{', '}')
        if not block_close or re.match(r'\s*else\b', clean[block_close:end]):
            continue
        arm = clean[block_open+1:block_close-1]
        last = re.search(r'\n([ \t]*)' + var + r'\s*=(?!=)\s*(' + VALUE + r');\s*$', arm)
        if not last or ' '.join(last[2].split()) != ' '.join(value.split()):
            continue
        before_last = arm[:last.start()]
        condition = clean[cond_open:cond_close]
        names = set(re.findall(r'(?<![\w.])' + IDENT, re.sub(r'\b0[xX][0-9a-fA-F]+\b', '', value)))
        if re.search(r'\b' + var + r'\b', condition + before_last) or var in names:
            continue
        if any(_assigned(n, condition + before_last) or re.search(r'&\s*' + n + r'\b', clean[opening:end]) for n in names):
            continue
        line_end = clean.find('\n', start) + 1
        last_start = block_open + 1 + last.start()
        last_end = clean.find(';', block_open + 1 + last.end(2)) + 1
        text = (source[:start] + source[line_end:last_start] + source[last_end:block_close]
                + '\n' + hit[1] + source[start + len(hit[1]):line_end - 1] + source[block_close:])
        result.append((FAMILY, text))
        if re.search(r'[!=<>]=|(?<![<>])[<>](?![<>=])', value) and (inlined := _inlined(text, var, value, names, start + (last_start - line_end) + (block_close - last_end))):
            result.append((FAMILY, inlined))
    return result[:4]


def _inlined(text, var, value, names, at):
    """The moved value written where it's used, when that's once: a comparison carried in a variable stayed one
    (`andi v0,s0,1` on a saved register, an N64 function at 92%) where the game computed it in the condition."""
    clean = _blank(text)
    line = re.compile(r'\n[ \t]*' + var + r'\s*=(?!=)[^;]*;').match(clean, at)
    if not line:
        return None
    rest = clean[line.end():]
    uses = list(re.finditer(r'(?<![\w.>])' + var + r'\b', rest))
    if len(uses) != 1 or _assigned(var, rest):
        return None
    use = line.end() + uses[0].start()
    if any(_assigned(n, clean[line.end():use]) for n in names) or re.search(r'\b(?:for|while|do|goto)\b|\bcase\b|\}',
                                                                           clean[line.end():use]):
        return None
    out = text[:use] + '(' + value + ')' + text[use + len(var):]
    out = out[:line.start()] + out[line.end():]
    declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', _blank(out))
    if declared and len(re.findall(r'(?<![\w.>])' + var + r'\b', _blank(out))) == 1:
        out = out[:declared.start()] + out[declared.end():]
    return out
