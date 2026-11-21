"""Recover a measured indexed callback and its surrounding loop."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names

SAVED = r'\$s[0-7]'
REG = r'\$\w+'
PREFIX = '__m2c_callback_'
BACKEDGE = re.compile(
    rf'(?m)^addiu \$a0, (?P<arg>{SAVED}), (?P<offset>{NUMBER})\n'
    rf'(?P<label>\.L\w+):\naddiu \$a1, \$sp, (?P<slot>{NUMBER})\njal (?P<receive>{IDENT})\n'
)
PROLOGUE_ADDRESS = re.compile(
    rf'(?m)^lui (?P<reg>{SAVED}), %hi\((?P<expr>{IDENT}(?: \+ {NUMBER})?)\)\n'
    r'addiu (?P=reg), (?P=reg), %lo\((?P=expr)\)'
)
INDEXED = re.compile(
    rf'(?m)^lhu (?P<work>{REG}), (?P<field>{NUMBER})\((?P<arg>{SAVED})\)\n'
    rf'lw \$a0, (?P<slot>{NUMBER})\(\$sp\)\n'
    r'sll (?P=work), (?P=work), 2\n'
    rf'addu (?P=work), (?P=work), (?P<table>{SAVED})\n'
    r'lw (?P=work), (?:0x0|0)?\((?P=work)\)\njalr (?P=work)\nnop$'
)
SOURCE_CALLS = (
    re.compile(rf'\*\(\(M2C_FIELD\((?P<arg>{IDENT}), u16 \*, (?P<field>{NUMBER})\) \* 4\) '
               rf'\+ (?P<table>{IDENT})\)\((?P<task>{IDENT})\);'),
    re.compile(rf'\(\*\(void \(\*\*\)\(void \*\)\)\(\(u8 \*\)(?P<table>{IDENT}) '
               rf'\+ M2C_FIELD\((?P<arg>{IDENT}), u16 \*, (?P<field>{NUMBER})\) \* 4\)\)\((?P<task>{IDENT})\);'),
)


def _witness(asm):
    if 'lhu' not in asm or 'jalr' not in asm or '%hi(' not in asm:
        return None
    lines = [' '.join(re.sub(r'/\*.*?\*/|#.*','',line).split()) for line in abi_register_names(asm).splitlines()]
    text = '\n'.join(filter(None,lines))
    loop = BACKEDGE.search(text)
    if not loop:
        return None
    arg = re.escape(loop['arg'])
    jump = re.search(rf'(?m)^j {re.escape(loop["label"])}\naddiu \$a0, {arg}, ({NUMBER})$',text[loop.end():])
    if not jump or integer(loop['offset']) != integer(jump[1]):
        return None
    preamble, body = text[:loop.start()],text[loop.end():loop.end()+jump.start()]
    if not re.search(rf'(?m)^(?:addu {arg}, \$a0, \$zero|move {arg}, \$a0)$',preamble):
        return None
    call = INDEXED.search(body)
    if not call or call['arg'] != loop['arg'] or integer(call['slot']) != integer(loop['slot']):
        return None
    found = list(PROLOGUE_ADDRESS.finditer(preamble))
    addresses = {hit['reg']: hit['expr'] for hit in found}
    if len(found) != len(addresses) or call['table'] not in addresses:
        return None
    return loop, call, addresses, body[call.end():]


def applies(asm):
    return _witness(asm) is not None


def _absolute(expr, resolve):
    base, _, offset = expr.partition(' + ')
    address = resolve(base)
    if address is None or not 0 <= (result := address + integer(offset or '0')) <= 0xFFFFFFFF:
        return None
    return result


def _base_bindings(part, preamble, header, addresses, table, table_address, resolve):
    pattern = re.compile(rf'(?m)^    (?P<var>{IDENT}) = (?:&(?P<raw>{IDENT}) \+ (?P<offset>{NUMBER})'
                         rf'|\(\(u8 \*\)&(?P<typed>{IDENT}) \+ (?P<toff>{NUMBER})\));')
    result = []
    for hit in pattern.finditer(part.clean,part.opening+1,preamble):
        var = hit['var']
        base,offset = (hit['raw'],hit['offset']) if hit['raw'] else (hit['typed'],hit['toff'])
        address = _absolute(f'{base} + {offset}',resolve)
        if address is None or address not in addresses:
            continue
        if not re.search(rf'\bextern M2C_UNK {base};', part.clean[:part.opening]) or re.search(rf'\b{base}\b',header):
            return None
        if not re.search(rf'(?m)^    void \*{var};$',part.body) or len(re.findall(rf'\b{var}\s*=(?!=)',part.body)) != 1:
            return None
        result.append((var,address,(*hit.span(),f'    {var} = ((u8 *)&{base} + {offset});')))
    if len(result) != 2 or (table,table_address) not in [(var,address) for var,address,_ in result]:
        return None
    return result


def rewrite(source, name, asm, header='', resolve=None):
    """Return one candidate when the callback, backedge and resident address agree."""
    if resolve is None or 'goto ' not in source or 'M2C_FIELD' not in source or PREFIX in source+header:
        return None
    witness = _witness(asm)
    part = view(source,name)
    if not witness or part is None:
        return None
    loop, indexed, addresses, rest = witness
    end = len(part.clean[:part.end].rstrip()) - 1
    back = re.search(
        rf'(?m)^    (?P<cursor>{IDENT}) = (?P<arg>{IDENT}) \+ (?P<off>{NUMBER});\n'
        rf'    goto (?P<label>{IDENT});\s*$',part.clean[part.opening+1:end])
    if not back or integer(back['off']) != integer(loop['offset']):
        return None
    if not re.search(rf'\bvoid\s+{re.escape(name)}\(void \*{back["arg"]}\)\s*$',part.clean[:part.opening]):
        return None
    begin = re.search(rf'(?m)^    {back["cursor"]} = {back["arg"]} \+ {back["off"]};\n'
                      rf'{back["label"]}:\n    {loop["receive"]}\({back["cursor"]}, &(?P<task>{IDENT}),', part.clean)
    if begin is None or not part.opening < begin.start() < part.opening+1+back.start():
        return None
    cursor = re.search(rf'(?m)^    void \*{back["cursor"]};\n', part.clean[part.opening+1:begin.start()])
    if (not cursor or len(re.findall(rf'\b{back["cursor"]}\b',part.body)) != 4
            or len(re.findall(rf'\b{back["label"]}\b',part.body)) != 2
            or re.search(r'\b(?:continue|break|return)\b',part.clean[begin.end():end])
            or len(re.findall(r'\bgoto\b',part.body)) != 1):
        return None
    found = [hit for pattern in SOURCE_CALLS for hit in pattern.finditer(part.clean,begin.end(),end)]
    if len(found) != 1:
        return None
    call = found[0]
    if (call['arg'] != back['arg'] or call['task'] != begin['task']
            or integer(call['field']) != integer(indexed['field'])):
        return None
    table_address = _absolute(addresses[indexed['table']],resolve)
    bindings = _base_bindings(part,begin.start(),header,{_absolute(expr,resolve) for expr in addresses.values()},
                              call['table'],table_address,resolve)
    if not bindings:
        return None
    resident = re.compile(rf'M2C_FIELD\({call["task"]}, void \*\*, (?P<field>{NUMBER})\) = \(void \*\) '
                          rf'\((?P<base>&{IDENT}|\(\(u8 \*\)&{IDENT}) \+ (?P<off>{NUMBER})\)\)*;')
    matches = list(resident.finditer(part.clean,call.end(),end))
    if len(matches) != 1:
        return None
    store = matches[0]
    base = store['base'].split('&')[1]
    addr = _absolute(f'{base} + {store["off"]}',resolve)
    if addr is None or addr in {address for _,address,_ in bindings}:
        return None
    registers = [reg for reg,expr in addresses.items() if _absolute(expr,resolve)==addr]
    if len(registers) != 1:
        return None
    destination = re.compile(
        rf'(?m)^lw \$a0, ({NUMBER})\(\$sp\)\n(?:sw \$a0, {NUMBER}\({SAVED}\)\n)?'
        rf'jal {IDENT}\nsw {re.escape(registers[0])}, ({NUMBER})\(\$a0\)$')
    if not any(integer(hit[1]) == integer(loop['slot']) and integer(hit[2]) == integer(store['field'])
               for hit in destination.finditer(rest)):
        return None
    alias = f'D_{addr:08X}'
    if resolve(alias) != addr or re.search(rf'\b{alias}\b',source+'\n'+header):
        return None

    top = part.opening+1
    prefix = edit(source[:begin.start()], [binding for _,_,binding in bindings]+[
        (top+cursor.start(),top+cursor.end(),f'    u8 *{PREFIX}resident;\n')])
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(',prefix)
    if not signature:
        return None
    prefix = prefix[:signature.start()]+f'extern u8 {alias};\n'+prefix[signature.start():]
    offset = back['off']
    body_start = part.clean.index(loop['receive']+'(',begin.start())
    arg_start = body_start+len(loop['receive'])+1
    active = edit(source[:top+back.start()],[
        (arg_start,arg_start+len(back['cursor']),f'{back["arg"]} + {offset}'),
        (*call.span(),f'(*(void (**)(void *))((u8 *){call["table"]} + '
          f'M2C_FIELD({call["arg"]}, u16 *, {call["field"]}) * 4))({call["task"]});'),
        (*store.span(),f'M2C_FIELD({call["task"]}, void **, {store["field"]}) = {PREFIX}resident;')
    ])[body_start:]
    body = '\n'.join('    '+line if line.strip() else line for line in ('    '+active.rstrip()).splitlines())
    return prefix+f'    {PREFIX}resident = (u8 *)&{alias};\n    for (;;) {{\n'+body+'\n    }\n'+source[end:]
