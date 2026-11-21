"""Measured MIPS changes to return, call setup and local lifetimes."""

import re

from . import mips_regions
from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, NUMBER, calls, edit, integer, split_args, view
from .pattern_repairs import close


def _function(source, name):
    part = view(source, name)
    if part and (end := close(part.clean, part.opening, '{', '}')):
        part.end = end
        return part
    return None


def variants(source, name, header, toolchain, rows):
    """Offer a single structural edit for a small, specific instruction difference."""
    if not toolchain.startswith(('gcc-2.7.2-kmc', 'ido-7.1')):
        return []
    changes = [(i, want, have) for i, (kind, want, have) in enumerate(rows) if kind != ' ']
    if not 1 <= len(changes) <= 3 or any(not want or not have for _, want, have in changes):
        return []
    if toolchain.startswith('ido-7.1') and len(changes) == 2:
        family, candidate = 'drop_duplicate_call_argument', _short_call(source, name, header, rows, changes)
    elif not toolchain.startswith('gcc-2.7.2-kmc'):
        return []
    elif len(changes) == 1:
        family, candidate = 'guarded_local_return', _guarded_return(source, name, rows, changes[0])
    elif len(changes) == 2:
        family, candidate = 'post_call_index_reset', _post_call_reset(source, name, rows, changes)
    else:
        family, candidate = 'float_branch_carrier', _float_carrier(source, name, changes)
    return [(family, candidate)] if candidate else []


def _guarded_return(source, name, rows, change):
    index, want, have = change
    branch = r'(b(?:eq|ne)z \$[vtas][0-9]), (0x[0-9a-fA-F]+)'
    target, actual = re.fullmatch(branch, want), re.fullmatch(branch, have)
    if not target or not actual or target[1] != actual[1]:
        return None
    at, copy = int(target[2], 16), int(actual[2], 16)
    if (at != copy + 4 or copy % 4 or not index + 1 < copy // 4 < at // 4 < len(rows)
            or not re.fullmatch(r'move \$v0, \$s[0-7]', rows[copy // 4][1])
            or not re.fullmatch(r'lw \$ra, .+\(\$sp\)', rows[at // 4][1])):
        return None
    part = _function(source, name)
    if not part:
        return None
    tail = re.search(rf'(?m)^(?P<indent>[ \t]*)}}[ \t]*\n[ \t]*return\s+(?P<local>{IDENT});\s*$', part.body)
    guard = re.search(r'(?m)^[ \t]*if\s*\(', part.body)
    if not tail or not guard:
        return None
    start = part.opening + 1
    condition = close(part.clean, start + guard.end() - 1)
    if not condition or not (opening := re.match(r'\s*\{', part.clean[condition:])):
        return None
    brace = condition + opening.end() - 1
    if close(part.clean, brace, '{', '}') != start + tail.end('indent') + 1:
        return None
    if re.search(r'\b(?:goto|return)\b', part.body[:tail.start()]):
        return None
    local = tail['local']
    before = part.clean[start:brace]
    inside = part.clean[brace + 1:start + tail.start()]
    if (len(re.findall(rf'\b{local}\b', before)) != 1
            or not re.search(rf'\b{INTEGER}\s+{local}\s*;', before)
            or not re.search(rf'(?m)^\s*{local}\s*=\s*{IDENT}\s*\(', inside)
            or re.search(rf'(?:&\s*{local}\b|\b{INTEGER}\s+{local}\b)', inside)):
        return None
    first_return = re.search(r'(?m)^(?P<indent>[ \t]+)\S', inside)
    if not first_return:
        return None
    # The bypass skipped the write to v0, so the generated uninitialized return
    # belongs inside the guard which computes that value.
    replacement = f"{first_return['indent']}return {local};\n{tail['indent']}}}\n"
    return edit(source, [(start + tail.start(), start + tail.end(), replacement)])


def _post_call_reset(source, name, rows, changes):
    (first, setup, previous), (second, clear, current) = changes
    if (second != first + 1 or setup != current or clear != previous
            or not re.fullmatch(r'move \$a0, \$s[0-7]', setup)
            or not re.fullmatch(r'move \$s[0-7], \$zero', clear)):
        return None
    call_at = next((i for i in range(second + 1, min(len(rows), second + 4))
                    if re.fullmatch(rf'jal {IDENT}', rows[i][1])), None)
    transfers = mips_regions.CONDITIONAL | mips_regions.JUMPS | mips_regions.CALLS
    if call_at is None or any(rows[i][1].split(' ', 1)[0] in transfers
                              for i in range(second + 1, call_at)):
        return None
    name_at_call = rows[call_at][1].split()[1]
    part = _function(source, name)
    if not part or len(list(calls(part, name_at_call))) != 1:
        return None
    # Match only straight-line statements directly ahead of a result-bearing call.
    call_statement = re.compile(
        rf'(?m)^[ \t]*(?:M2C_FIELD\([^;\n]+?\)|{IDENT})\s*=\s*{name_at_call}\([^;\n]+\);')
    call = call_statement.search(part.body)
    if not call:
        return None
    resets = re.compile(rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*0;[ \t]*\n')

    # In this shape the reset precedes at most two scalar preparations for the call.
    valid = []
    for reset in resets.finditer(part.body, 0, call.start()):
        local = reset['local']
        prefix = part.body[:reset.start()]
        preparation = part.body[reset.end():call.end()]
        if (prefix.rstrip()[-1:] in (';', '{')
                and not re.search(r'\bgoto\b', prefix)
                and not re.search(rf'\b{local}\b', preparation)
                and re.fullmatch(rf'(?:[ \t]*{IDENT}\s*=[^;{{}}\n]+;\s*){{0,2}}',
                                 part.body[reset.end():call.start()])
                and len(re.findall(rf'\b{local}\b', prefix)) == 1
                and re.search(rf'\b{INTEGER}\s+{local}\s*;', prefix)):
            valid.append(reset)
    if len(valid) != 1:
        return None
    reset = valid[0]
    at = part.opening + 1
    return edit(source, [(at + reset.start(), at + reset.end(), ''),
                         (at + call.end(), at + call.end(), '\n' + source[at+reset.start():at+reset.end()].rstrip())])


def _float_carrier(source, name, changes):
    _, conversion, actual = changes[0]
    registers = re.fullmatch(r'cvt\.s\.d (\$f[0-9]+), (\$f[0-9]+)', conversion)
    if not registers:
        return None
    keep, reuse = registers.groups()
    if keep == reuse or actual != f'cvt.s.d {reuse}, {reuse}':
        return None
    _, constant, loaded = changes[1]
    _, store, stored = changes[2]
    if (constant != f'mtc1 $at, {keep}' or loaded != f'mtc1 $at, {reuse}'
            or not store.startswith(f'swc1 {keep}, ') or stored != store.replace(keep + ',', reuse + ',', 1)):
        return None
    part = _function(source, name)
    if not part:
        return None
    narrow, wide = r'(?:f32|float)', r'(?:f64|double)'
    match = re.fullmatch(
        rf'\s*{narrow}\s+(?P<result>{IDENT});\s*'
        rf'(?P<decl>{wide}\s+(?P<temp>{IDENT});)\s*'
        rf'(?P=temp)\s*=\s*\(\s*{wide}\s*\)\s*\*\s*(?P<pointer>{IDENT});\s*'
        rf'if\s*\(\s*(?P=temp)\s*<\s*{IDENT}\s*\)\s*{{\s*'
        rf'(?P=result)\s*=\s*\(\s*{narrow}\s*\)\s*\(\s*(?P=temp)\s*\+\s*{IDENT}\s*\);\s*'
        rf'}}\s*else\s*{{\s*(?P=result)\s*=\s*1\.0[fF];\s*}}\s*'
        rf'\*\s*(?P=pointer)\s*=\s*(?P=result);\s*', part.body)
    if not match or match['temp'] in {match['result'], match['pointer']}:
        return None
    signature = part.clean[:part.opening]
    if not re.search(rf'\b{re.escape(name)}\s*\([^()]*\b{narrow}\s*\*\s*{match["pointer"]}\b[^()]*\)\s*$', signature):
        return None
    start = part.opening + 1
    trailing = part.body[match.end('decl'):]
    hits = list(re.finditer(rf'\b{match["temp"]}\b', trailing))
    if len(hits) != 3:
        return None
    return edit(source, [(start + match.start('decl'), start + match.end('decl'), ''),
                         *((start + match.end('decl') + hit.start(), start + match.end('decl') + hit.end(),
                            match['result']) for hit in hits)])


def _short_call(source, name, header, rows, changes):
    (first, want, have), (last, offset, actual) = changes
    delta = re.fullmatch(rf'addiu \$a1, \$a3, ({NUMBER})', offset)
    if (want != 'move $a3, $a0' or have != 'move $a2, $a0' or not delta
            or actual != f'addiu $a1, $a2, {delta[1]}' or not first < last - 2
            or rows[last - 2][1] != 'move $a0, $a1'
            or not (callee := re.fullmatch(rf'jal ({IDENT})', rows[last - 1][1]))):
        return None
    callee = callee[1]
    if (len(rows) > 12 or sum(row[1].startswith(('jal ', 'jalr ')) for row in rows) != 1
            or any(not re.fullmatch(r'sw \$ra, .+\(\$sp\)', row[1]) for row in rows[first + 1:last - 2])
            or re.search(rf'\b{callee}\s*\(', _blank(header))):
        return None
    part = _function(source, name)
    if not part:
        return None
    signature = re.search(rf'\b{re.escape(name)}\s*\(\s*(?:{INTEGER}|M2C_UNK)\s+(?P<a>{IDENT}),\s*'
                          rf'(?:{INTEGER}|M2C_UNK)\s+(?P<b>{IDENT})\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    body = re.fullmatch(rf'\s*{callee}\s*\(\s*{signature["b"]}\s*,\s*{signature["a"]}\s*\+\s*'
                        rf'(?P<delta>{NUMBER})(?P<drop>\s*,\s*{signature["a"]})\s*\);\s*', part.body)
    prototype = re.search(rf'(?m)^[ \t]*(?:{INTEGER}|M2C_UNK|void)\s+{callee}\s*\((?P<params>[^()]+)\);'
                          rf'[ \t]*/\* extern \*/', source[:part.opening])
    if not body or integer(body['delta']) != integer(delta[1]) or not prototype:
        return None
    params = split_args(prototype['params'])
    if len(params) != 3 or not all(re.fullmatch(rf'\s*(?:{INTEGER}|M2C_UNK)\s*',
                                               prototype['params'][start:end]) for start, end in params):
        return None
    at = part.opening + 1
    return edit(source, [(at + body.start('drop'), at + body.end('drop'), ''),
                         (prototype.start('params') + params[1][1], prototype.end('params'), '')])
