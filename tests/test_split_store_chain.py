"""The temporaries m2c splits a chained assignment and a compound update into, written back."""
import re

from decomprepair.split_store_chain import COMPOUND, EXPRESSION, REREAD, SCATTERED, TOGETHER, variants

CODE = '''typedef short s16;
typedef unsigned short u16;
typedef signed char s8;
typedef int s32;
void step(void *p)
{
    s16 kept;
    s16 value;
    s32 phase;

    do {
    phase = (*(s32 *)((char *)(p) + 0x30)) + 0x400;
    (*(s32 *)((char *)(p) + 0x30)) = phase;
    value = (*(u16 *)((char *)(p) + 0x14)) + 0x21;
    (*(s16 *)((char *)(p) + 0x12)) = value;
    kept = (*(s16 *)((char *)(p) + 0x12));
    (*(s8 *)((char *)(p) + 0x63)) = (~(phase >> 8));
    (*(s8 *)((char *)(p) + 0x62)) = (~(phase >> 8));
    (*(u16 *)((char *)(p) + 0x14)) = (u16) value;
    (*(s16 *)((char *)(p) + 0x16)) = value;
    (*(s16 *)((char *)(p) + 0x20)) = (*(s16 *)((char *)(p) + 0x12)) * 3;
    } while (0);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def children(code=CODE):
    found = {}
    for family, text in variants(code, 'step'):
        found.setdefault(family, []).append(squash(text))
    return found


def test_scattered_stores_of_a_local_become_one_chain_in_store_order():
    inline = children()[SCATTERED][0]
    assert ('(*(s16 *)((char *)(p) + 0x16)) = (*(u16 *)((char *)(p) + 0x14)) = (*(s16 *)((char *)(p) + 0x12)) = '
            '(*(u16 *)((char *)(p) + 0x14)) + 0x21; kept =') in inline
    assert 'value = (*(u16' not in inline


def test_adjacent_stores_of_one_expression_and_the_staged_compound():
    found = children()
    assert ('(*(s8 *)((char *)(p) + 0x62)) = (*(s8 *)((char *)(p) + 0x63)) = (~(phase >> 8));') in found[EXPRESSION][0]
    compound = found[COMPOUND][0]
    assert '((*(s32 *)((char *)(p) + 0x30))) += 0x400;' in compound or '(*(s32 *)((char *)(p) + 0x30)) += 0x400;' in compound
    assert '~(((*(s32 *)((char *)(p) + 0x30))) >> 8)' in compound or '~((*(s32 *)((char *)(p) + 0x30)) >> 8)' in compound


def test_the_member_is_reread_through_the_local_and_all_steps_come_together():
    found = children()
    assert '(*(s16 *)((char *)(p) + 0x20)) = kept * 3;' in found[REREAD][0].replace('(kept)', 'kept')
    together = found[TOGETHER]
    assert all('do {' not in text for text in together[::2]) and any('do {' in text for text in together)


def test_a_call_another_base_or_a_read_of_a_moved_member_declines():
    def scattered(line):
        code = CODE.replace('    kept = (*(s16 *)((char *)(p) + 0x12));\n', f'    {line}\n')
        return ' '.join(children(code).get(SCATTERED, []))
    for line in ('touch(p);', 'kept = (*(s16 *)((char *)(p) + 0x16));', 'kept = (*(s16 *)((char *)(q) + 0x40));',
                 'kept = *q;', 'p = 0;'):
        assert '(*(s16 *)((char *)(p) + 0x12)) = (*(u16' not in scattered(line), line
        assert '(*(s16 *)((char *)(p) + 0x12)) = value; ' in scattered(line) or not scattered(line), line


FENCED = '''typedef unsigned short u16;
typedef signed char s8;
typedef int s32;
void step(void *p)
{
    s32 phase;
    s32 scale;

    do { *(s32 *)((char *)p + 0x34) += 1; } while (0);
    phase = *(s32 *)((char *)p + 0x3C) + 0x2000;
    *(s32 *)((char *)p + 0x3C) = phase;
    scale = (u16)(*(u16 *)((char *)p + 0x10) + 0x1E);
    *(u16 *)((char *)p + 0x10) = scale;
    *(u16 *)((char *)p + 0xE) = scale;
    do { *(s8 *)((char *)p + 0x73) = (~(phase >> 0xC)); } while (0);
    *(s8 *)((char *)p + 0x72) = (~(phase >> 0xC));
}
'''


def _together(code):
    return [re.sub(r'\s+', '', text) for family, text in variants(code, 'step') if family == TOGETHER]


def test_a_block_left_by_an_opened_fence_does_not_end_the_run():
    for code in (FENCED, FENCED.replace('do { ', '{ ').replace(' } while (0);', ' }')):
        best = [text for text in _together(code) if '+=0x2000;' in text]
        assert best, 'no child writes the stored sum as a compound update'
        assert any('*(s8*)((char*)p+0x72)=*(s8*)((char*)p+0x73)=(~(' in text for text in best)
        assert any('(u16)(*(u16*)((char*)p+0x10)+0x1E)' in text and 'scale=' not in text for text in best)


def test_the_body_of_a_condition_keeps_its_braces():
    code = FENCED.replace('do { *(s32 *)((char *)p + 0x34) += 1; } while (0);',
                          'if (p != 0)\n    { *(s32 *)((char *)p + 0x34) += 1; }')
    assert any('if(p!=0){*(s32*)((char*)p+0x34)+=1;}' in text for text in _together(code))
