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


RESULT_COPY = 'shared_result_copy'


def _result_copy_evidence(rows):
    """The skipped-loop path and the loop exit should copy the same register."""
    registers = r'\$(?:a[0-3]|s[0-7]|v[01])'
    move = re.compile(rf'move ({registers}), ({registers}|\$zero)')
    skipped = set()
    for i, (_, target, candidate) in enumerate(rows):
        want, actual = move.fullmatch(target), move.fullmatch(candidate)
        if not want or not actual or want[1] == actual[1]:
            continue
        if (i and actual[2] == '$zero' and want[2] != '$zero'
                and rows[i - 1][1] == rows[i - 1][2]
                and rows[i - 1][1].startswith('beqz ')):
            skipped.add(want.groups() + (actual[1],))
        if i + 1 < len(rows) and want[2] == actual[2] != '$zero':
            _, wanted_branch, actual_branch = rows[i + 1]
            if (want.groups() + (actual[1],) in skipped
                    and wanted_branch.startswith(f'bnez {want[1]}, ')
                    and actual_branch.startswith(f'bnez {actual[1]}, ')):
                return True
    return False


def result_copy_variants(source, name, rows):
    """Share the result copy after the outer guard when both skip paths agree."""
    from .integer_repair_support import IDENT, edit, locals_for, view

    if not _result_copy_evidence(rows) or not (part := view(source, name)):
        return []
    prefix = re.compile(
        rf'(?<=[;{{}}])\s*(?P<flag>{IDENT})\s*=\s*0\s*;'
        rf'\n[ \t]*if\s*\(\s*{IDENT}\s*!=\s*NULL\s*\)\s*{{'
        rf'\s*(?P<result>{IDENT})\s*=\s*(?P=flag)\s*;'
        rf'\s*if\s*\(\s*M2C_FIELD\(\s*{IDENT}\s*,\s*void\s*\*\*\s*,\s*(?:0x[0-9a-fA-F]+|\d+)\s*\)'
        rf'\s*!=\s*NULL\s*\)\s*{{'
    )
    locals_by_name = {decl['name']: decl for decl in locals_for(part)}
    variants = []
    for entry in prefix.finditer(part.clean, part.opening + 1, part.end):
        result, flag = entry['result'], entry['flag']
        if result == flag or not all(key in locals_by_name and locals_by_name[key].start() < entry.start()
                                    for key in (result, flag)):
            continue
        end = close(part.clean, entry.end() - 1, '{', '}')
        if end is None:
            continue
        exit_copy = re.match(
            rf'(?P<outer_close>\s*}})(?P<else>\s*else\s*{{)\s*(?P<label>{IDENT})\s*:(?P<copy_indent>\s*)'
            rf'{result}\s*=\s*{flag}\s*;(?P<close>\s*}})\s*if\s*\(\s*{result}\s*==\s*0\s*\)',
            part.clean[end:],
        )
        if not exit_copy:
            continue
        label = exit_copy['label']
        if not re.search(rf'(?<=[;}}])\s*goto\s+{label}\s*;\s*}}$', part.clean[entry.end():end]):
            continue
        # Both skip paths retain the initialized flag. The loop path already
        # jumps to the copy, so moving the label preserves its exit as well.
        edits = [(end + exit_copy.start(field), end + exit_copy.end(field), '') for field in ('else', 'close')]
        indent = exit_copy['outer_close'].rsplit('\n', 1)[-1][:-1]
        start, stop = (end + index for index in exit_copy.span('copy_indent'))
        if source[start:stop] == exit_copy['copy_indent'] and '\n' in exit_copy['copy_indent']:
            edits.append((start, stop, '\n' + indent))
        variants.append((RESULT_COPY, edit(source, edits)))
    return variants
