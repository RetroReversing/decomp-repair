"""Recover stack requests whose result is written by a message recipient."""

import re

from .integer_repair_support import IDENT, NUMBER, integer, view
from .pattern_repairs import close

MAKE = 'osCreateMesgQueue'
SEND = 'osSendMesg'
RECEIVE = 'osRecvMesg'
P = '__repair_message_'


def evidence(lines):
    """Bind the queue, request, and returned word to the target's call arguments."""
    lines = [' '.join(line.split()) for line in lines if not line.endswith(':') and not line.startswith(('glabel ', 'endlabel '))]
    sites = [i for i, line in enumerate(lines) if line.startswith(('jal ', 'jalr '))]
    if [lines[i] for i in sites] != [f'jal {name}' for name in (MAKE, SEND, RECEIVE)]:
        return None
    create, send, recv = sites
    guard = re.fullmatch(rf'lui \$v0, %hi\((?P<ready>{IDENT})\)\n'
                         r'lw \$v0, %lo\((?P=ready)\)\(\$v0\)', '\n'.join(lines[:2]))
    if not guard or create < 2 or recv + 2 >= len(lines):
        return None
    queue = re.fullmatch(rf'addiu \$a0, \$sp, ({NUMBER})', lines[create - 2])
    buffer = re.fullmatch(rf'addiu \$a1, \$sp, ({NUMBER})', lines[create - 1])
    result = re.fullmatch(rf'lw \$v0, ({NUMBER})\(\$sp\)', lines[recv + 2])
    route = re.search(
        rf'lui \$a0, %hi\((?P<mailbox>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=mailbox)\)\n'
        rf'addiu \$a1, \$sp, (?P<request>{NUMBER})\naddiu \$a2, \$zero, (?:1|0x1)\n',
        '\n'.join(lines[create+2:send]))
    if not all((queue, buffer, result, route)):
        return None
    if not all(re.fullmatch(r'addiu \$a2, \$zero, (?:1|0x1)', lines[i + 1]) for i in (create, recv)):
        return None
    q, b, ret = (integer(match[1]) for match in (queue, buffer, result))
    request = integer(route['request'])
    saved_queue = re.fullmatch(rf'sw (?P<reg>\$s[0-7]), (?P<offset>{NUMBER})\(\$sp\)', lines[send+1])
    if not saved_queue or integer(saved_queue['offset']) != request + 4:
        return None
    reg = re.escape(saved_queue['reg'])
    if (recv != send + 4
            or not re.fullmatch(rf'(?:move \$a0, {reg}|addu \$a0, {reg}, \$zero)', lines[send+2])
            or lines[send+3] not in ('move $a1, $zero', 'addu $a1, $zero, $zero')
            or not any(re.fullmatch(rf'addiu {reg}, \$sp, ({NUMBER})', line) and integer(line.rsplit(' ', 1)[1]) == q
                       for line in lines[create+2:send])):
        return None
    stores = [(m[1], integer(m[3])) for line in lines[create+2:send]
              if (m := re.fullmatch(rf'(sb|sh|sw) (\$\w+), ({NUMBER})\(\$sp\)', line))]
    small = q + 24 == request and request + 16 == b
    extended = request + 24 == q and q + 24 == b
    expected = {('sh', request), ('sw', request + 8)}
    if extended:
        expected.update((('sb', request + 16), ('sh', request + 18)))
    if (not (small or extended) or request + 12 != ret or len(expected) != len(stores) or set(stores) != expected
            or min(q, b, request) < 16 or any(x % 4 or x > 96 for x in (q, b, request))):
        return None
    branch = 'bnez' if extended else 'beqz'
    if not any(re.fullmatch(rf'{branch} \$v0, \S+', line) for line in lines[2:create - 2]):
        return None
    return q, b, request, extended, route['mailbox'], guard['ready']


def rewrite(source, name, context, lines):
    shapes = evidence(lines)
    if not shapes or P in source + context or not (part := view(source, name)):
        return None
    q, b, request, extended, mailbox, ready = shapes
    queue, buffer, command, back, data, result, flag, extra = (
        f'sp{offset:X}' for offset in (q, b, request, request+4, request+8, request+12, request+16, request+18))
    signature = re.search(rf'\bs32\s+{re.escape(name)}\((?P<args>[^()]*)\)\s*$', part.clean[:part.opening])
    if not signature or not (end := close(part.clean, part.opening, '{', '}')):
        return None
    params = signature['args']
    args = re.fullmatch(rf's8 ({IDENT}), s32 ({IDENT}), s16 ({IDENT})' if extended else rf's32 ({IDENT})', params)
    if not args and (not extended or params != 'void'):
        return None
    statements = ' '.join(part.clean[part.opening + 1:end - 1].split())
    if extended:
        declarations = (f's16 {command}; M2C_UNK *{back}; s32 {data}; s8 {flag}; s16 {extra}; '
                        f'M2C_UNK {queue}; M2C_UNK {buffer}; ')
        prefix = rf'if \({ready} == 0\) {{ return -1; }} '
        tail = ''
    else:
        declarations = f'M2C_UNK {queue}; s16 {command}; M2C_UNK *{back}; s32 {data}; M2C_UNK {buffer}; '
        prefix = rf'if \({ready} != 0\) {{ '
        tail = ' } return 0;'
    match = re.fullmatch(
        re.escape(declarations) + prefix + re.escape(f'{MAKE}(&{queue}, &{buffer}, 1); ')
        + rf'(?P<fields>(?:{IDENT} = (?:{NUMBER}|{IDENT}); )+)'
        + re.escape(f'{back} = &{queue}; {SEND}(&{mailbox}, &{command}, 1); {RECEIVE}(&{queue}, 0, 1); return {result};' + tail),
        statements)
    if not match:
        return None
    writes = re.findall(r'(\w+) = (\w+);', match['fields'])
    kind = dict(writes).get(command, '')
    expected = {data: args[2 if extended else 1] if args else '0'}
    if extended:
        expected.update({flag: args[1] if args else '0', extra: args[3] if args else '0'})
    if (not re.fullmatch(NUMBER, kind) or integer(kind) > 32767 or len(writes) != len(expected) + 1
            or any(dict(writes).get(key) != value for key, value in expected.items())
            or not any((m := re.fullmatch(rf'addiu \$\w+, \$zero, ({NUMBER})', ' '.join(line.split())))
                       and integer(m[1]) == integer(kind) for line in lines)):
        return None
    labels = {command: 'type', data: 'data', flag: 'flag', extra: 'extra'}
    if extended:
        record = f'''    struct {{
        s16 type;
        s16 padding;
        s32 queue;
        s32 data;
        s32 result;
        s8 flag;
        s8 padding2;
        s16 extra;
    }} {P}request;
    s32 {P}queue[6];
    s32 {P}buffer;
'''
        helper_params = f's16 {P}kind' + (', ' + params if args else '')
        opening = (f'static inline s32 {P}call({helper_params}) {{\n'
                   f'{record}\n    if ({ready} == 0) return -1;\n')
        close_wrapper = f'\n{signature[0].strip()} {{ return {P}call({", ".join([kind, *(args.groups() if args else ())])}); }}'
        create_buffer = f'{P}queue, &{P}buffer'
        queue_arg = f'{P}queue'
        queue_field = f'(s32){P}queue'
    else:
        opening = (f'{signature[0].strip()} {{\n    u8 {P}queue[24];\n    u32 {P}buffer[1];\n'
                   f'    struct {{ s16 type; s16 pad; void *queue; s32 data; s32 result; }} {P}request;\n\n'
                   f'    if ({ready} == 0) return 0;\n')
        close_wrapper = ''
        queue_arg = f'(s32 *){P}queue'
        create_buffer = f'{queue_arg}, (s32 *){P}buffer'
        queue_field = f'{P}queue'
    assignments = ''.join(
        f'    {P}request.{labels[key]} = {P+"kind" if extended and key == command else value};\n'
        for key, value in writes)
    return (source[:signature.start()] + opening + f'    {MAKE}({create_buffer}, 1);\n'
            + assignments + f'    {P}request.queue = {queue_field};\n'
            + f'    {SEND}(&{mailbox}, (s16 *)&{P}request, 1);\n    {RECEIVE}({queue_arg}, 0, 1);\n'
            + f'    return {P}request.result;\n}}' + close_wrapper + source[end:])
