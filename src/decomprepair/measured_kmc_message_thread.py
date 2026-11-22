"""Recover stack buffers and loop control in a measured KMC message thread."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = _shape('''
    M2C_UNK @client; M2C_UNK @messages; s32 @message;
    s32 (*@callback)(s32); void *@node;
    @create(&@queue, &@messages, 8);
    @add(&@client, &@queue, 3);
    @loop:
    @receive(&@queue, &@message, 1);
    @node = @head;
    if (@node == NULL) { goto @loop; }
    do {
        @callback = M2C_FIELD(@node, s32 (**)(s32), 4);
        if ((@callback != NULL) && (@callback(@message) != 0)) { goto @loop; }
        @node = M2C_FIELD(@node, void **, 0);
    } while (@node != NULL);
    goto @loop;
''')


def variants(source, name, header, rows):
    if not 35 <= len(rows) <= 40:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('addiu $sp, $sp, -80', 'addiu $sp, $sp, -40') not in changes
            or ('addiu $a1, $sp, 32', 'addiu $a1, $sp, 16') not in changes
            or ('addiu $a1, $sp, 64', 'addiu $a1, $sp, 24') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if (not draft or not re.search(rf'\bvoid {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])):
        return []
    if (not re.search(rf'addiu \$a1, \$sp, 32\nsw \$ra, 76\(\$sp\)\njal {re.escape(draft["create"])}\n'
                      r'addiu \$a2, \$zero, 8', target)
            or not re.search(rf'addiu \$a0, \$sp, 16\nmove \$a1, \$s0\njal {re.escape(draft["add"])}\n'
                             r'addiu \$a2, \$zero, 3', target)
            or not re.search(rf'addiu \$a1, \$sp, 64\njal {re.escape(draft["receive"])}\n'
                             r'addiu \$a2, \$zero, 1', target)
            or not re.search(rf'bnez \$s0, 88\nnop\nj {re.escape(name)}\+52\nnop', target)):
        return []
    client, messages, message, callback, node = (draft[key] for key in ('client', 'messages', 'message', 'callback', 'node'))
    if len({client, messages, message, callback, node}) != 5:
        return []
    queue, head = draft['queue'], draft['head']
    body = (f'\n    M2C_UNK {client}[4];\n    M2C_UNK {messages}[8];\n    s32 {message};\n'
            f'    s32 (*{callback})(s32);\n    void *{node};\n\n'
            f'    {draft["create"]}(&{queue}, {messages}, 8);\n    {draft["add"]}({client}, &{queue}, 3);\n'
            f'    for (;;) {{\n        {draft["receive"]}(&{queue}, &{message}, 1);\n'
            f'        {node} = {head};\n        while ({node} != NULL) {{\n'
            f'            {callback} = M2C_FIELD({node}, s32 (**)(s32), 4);\n'
            f'            if (({callback} != NULL) && ({callback}({message}) != 0)) break;\n'
            f'            {node} = M2C_FIELD({node}, void **, 0);\n        }}\n    }}\n')
    fixed = edit(source, [(part.opening + 1, part.end - 1, body)])
    return [('measured_message_thread_stack_and_loop', fixed)]
