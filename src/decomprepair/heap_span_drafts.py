"""Recover byte pointers and integer distances in a linked-block span walk."""

import re
from textwrap import dedent, indent

from .integer_repair_support import IDENT, NUMBER, integer, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close
from .stack_read_retry import _decimal

FAMILY = 'kmc_heap_span'

_TARGET = re.compile(
    r'addu \$v1, \$a0, \$zero\nlbu \$v0, -(?P<flag>\d+)\(\$v1\)\n'
    r'beqz \$v0, (?P<single>\.L\w+)\naddiu \$a0, \$a0, -(?P<header>\d+)\n'
    r'addiu \$a0, \$a0, (?P=header)\nbeqz \$a0, (?P<exit>\.L\w+)\n'
    r'addu (?P<sum>\$(?:a1|v1)), \$zero, \$zero\n(?P<loop>\.L\w+):\n'
    r'lbu \$v0, (?P<free>\d+)\(\$a0\)\nbnez \$v0, (?P<skip>\.L\w+)\nnop\n'
    r'lw \$v0, 0\(\$a0\)\naddiu \$v0, \$v0, -(?P=header)\n'
    r'(?:subu \$v0, \$v0, \$a0\naddu (?P=sum), (?P=sum), \$v0\n'
    r'|(?P<max>subu \$v1, \$v0, \$a0\nsltu \$v0, (?P=sum), \$v1\n'
    r'bnel \$v0, \$zero, (?P=skip)\naddu (?P=sum), \$v1, \$zero\n))'
    r'(?P=skip):\nlw \$a0, 0\(\$a0\)\nbeqz \$a0, (?P=exit)\nnop\nj (?P=loop)\nnop\n'
    r'(?P=single):\nlw \$v0, -(?P=header)\(\$v1\)\nsubu \$v0, \$v0, \$a0\n'
    r'addiu (?P=sum), \$v0, -(?P<overhead>\d+)\n(?P=exit):\njr \$ra\naddu \$v0, (?P=sum), \$zero'
)


def _target(asm):
    if not asm or 'subu' not in asm or 'lbu' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel ')))
    match = _TARGET.fullmatch(_decimal(text))
    if match and len({match[key] for key in ('single', 'exit', 'loop', 'skip')}) == 4:
        return match
    return None


def applies(asm):
    return _target(asm) is not None


_DISTANCE = r'\(M2C_FIELD\((?P=cursor), void \*\*, 0\) - (?P=header)\) - (?P=cursor)'


def _source(arg, is_max):
    update = (
        rf'(?P=span) = (?P<distance>{_DISTANCE}); '
        r'if \((?P=total) < (?P=span)\) \{ (?P=total) = (?P=span); \} '
        if is_max else rf'(?P=total) \+= (?P<distance>{_DISTANCE}); '
    )
    return re.compile(
        (rf'u32 (?P<span>{IDENT}); ' if is_max else '')
        + rf'[su]32 (?P<total>{IDENT}); void \*(?P<base>{IDENT}); void \*(?P<cursor>{IDENT}); '
        rf'(?P=base) = {arg} - (?P<header>{NUMBER}); if \(M2C_FIELD\({arg}, u8 \*, (?P<flag>-{NUMBER})\) != 0\) \{{ '
        r'(?P=cursor) = (?P=base) \+ (?P=header); (?P=total) = 0; if \((?P=cursor) != NULL\) \{ '
        rf'(?P<loop>loop_\d+): if \(M2C_FIELD\((?P=cursor), u8 \*, (?P<free>{NUMBER})\) == 0\) \{{ '
        + update
        + rf'\}} (?P=cursor) = M2C_FIELD\((?P=cursor), void \*\*, 0\); if \((?P=cursor) != NULL\) \{{ goto (?P=loop); \}} '
        rf'\}} \}} else \{{ (?P=total) = \(M2C_FIELD\({arg}, s32 \*, -(?P=header)\) - (?P=base)\) - '
        rf'(?P<overhead>{NUMBER}); \}} return (?P=total);'
    )



def rewrite(source, name, asm, header=''):
    if not source or 'void **' not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    closing = close(part.clean, part.opening, '{', '}') if part else None
    if not closing:
        return None
    is_max = target['max'] is not None
    ctype = 'u32' if is_max else 's32'
    sig = re.search(rf'\b{ctype}\s+{re.escape(name)}\s*\(\s*(?P<type>void) \*(?P<arg>{IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig or re.search(rf'\b{re.escape(name)}\s*\(', header + part.clean[:sig.start()]):
        return None
    arg = sig['arg']
    draft = _source(arg, is_max).fullmatch(' '.join(part.clean[part.opening + 1:closing - 1].split()))
    if not draft or any(abs(integer(draft[key])) != int(target[key]) for key in ('header', 'flag', 'free', 'overhead')):
        return None
    total, cursor = draft['total'], draft['cursor']
    if len({arg, total, cursor, draft['base'], draft.groupdict().get('span')}) != 5:
        return None
    span = draft.groupdict().get('span')
    distance = f'M2C_FIELD({arg}, s32 *, 0) - ({draft["header"]} + (s32){arg})'
    update = (f'{span} = {distance};\n                if ({total} < {span}) {{ {total} = {span}; }}'
              if span else f'{total} += {distance};')
    body = dedent(f'''
        {f'u32 {span};' if span else ''}
        {ctype} {total};
        u8 *{cursor};

        {cursor} = {arg};
        {arg} = {arg} - {draft['header']};
        if (M2C_FIELD({cursor}, u8 *, {draft['flag']}) != 0) {{
            {arg} = {arg} + {draft['header']};
            {total} = 0;
            if ({arg} != NULL) {{
                do {{
                    if (M2C_FIELD({arg}, u8 *, {draft['free']}) == 0) {{
                        {update}
                    }}
                    {arg} = M2C_FIELD({arg}, u8 **, 0);
                }} while ({arg} != NULL);
            }}
        }} else {{
            {total} = (M2C_FIELD({cursor}, s32 *, -{draft['header']}) - (s32){arg}) - {draft['overhead']};
        }}
        return {total};
    ''').strip()
    return (source[:sig.start('type')] + 'u8' + source[sig.end('type'):part.opening + 1]
            + '\n' + indent(body, '    ') + '\n' + source[closing - 1:])
