"""Equal constant returns written once, the others jumping to it.

gcc 2.7.2 gives every `return 1;` its own copy of the constant load, scheduled where it falls; where the game's code
jumps from one path to the other path's return, the constant's register follows the shared tail instead. An N64
function returning 1 from two paths was 20 points off (the paths' stores took `$v1` where the game used `$v0`) and
exact once the first `return 1;` became `goto` to a label on the second. Each variant keeps one of the returns of a
repeated constant and points the others at it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_return'
FAMILIES = (FAMILY,)

RETURN = re.compile(r'\breturn\s+(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    groups = {}
    for m in RETURN.finditer(clean, opening, end):
        groups.setdefault(int(m[1], 0), []).append(m)
    result = []
    for value, found in groups.items():
        if len(found) < 2 or len(found) > 4:
            continue
        label = f'__shared_return_{abs(value)}{"n" if value < 0 else ""}'
        if label in clean:
            continue
        for keep in (found[-1], found[0]):
            text = source
            for m in sorted(found, key=lambda m: m.start(), reverse=True):
                if m is keep:
                    text = text[:m.start()] + f'{label}:\n    ' + text[m.start():]
                else:
                    text = text[:m.start()] + f'goto {label};' + text[m.end():]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result


_GLOBAL_GUARD = re.compile(
    r'lui \$v1, %hi\((?P<flag>[A-Za-z_]\w*)\)\nlw \$v1, %lo\((?P=flag)\)\(\$v1\)\n'
    r'beqz \$v1, (?P<exit>\.L\w+)\n(?:move \$v0, \$zero|addu \$v0, \$zero, \$zero)\n'
    r'lui \$v0, %hi\((?P<value>[A-Za-z_]\w*)\)\nlw \$v0, %lo\((?P=value)\)\(\$v0\)\n'
    r'(?P=exit):\njr \$ra\nnop'
)


def _global_guard(asm):
    if 'beqz' not in asm or '%hi(' not in asm:
        return None
    from .measured_stack_drafts import _lines

    return _GLOBAL_GUARD.fullmatch('\n'.join(' '.join(line.split()) for line in _lines(asm)
                                             if not line.startswith(('glabel ', 'endlabel '))))


def global_guard_applies(asm):
    return _global_guard(asm) is not None


def rewrite_global_guard(source, name, asm):
    """Expose the zero return on the branch that skips the value load."""
    if 'return' not in source or not (target := _global_guard(asm)):
        return None
    from .integer_repair_support import IDENT, edit, view

    part = view(source, name)
    if not part or not re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening]):
        return None
    flag, value = target['flag'], target['value']
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = re.fullmatch(
        rf's32 (?P<result>{IDENT}); (?P=result) = 0; if \({flag} != 0\) '
        rf'{{ (?P=result) = {value}; }} return (?P=result);',
        ' '.join(part.clean[start:end].split()))
    if not draft or draft['result'] in (flag, value):
        return None
    return edit(source, [(start, end, f'\n    if ({flag} == 0) {{\n        return 0;\n    }}\n    return {value};\n')])
