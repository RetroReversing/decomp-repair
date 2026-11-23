import re

from decomprepair import loop_chain_cache
from decomprepair.loop_chain_cache import FAMILY, variants

CHAIN = '*((s32 **) (((char *) arg1) + 0x24))'
SOURCE = """void walk(void *arg1, void *rec) {
    s32 i;
    s32 off;

    i = 0;
    if (inline_fn(*((u16 *) (((char *) (*((s32 **) (((char *) arg1) + 0x24)))) + 4))) > 0) {
        off = 0;
        do {
            visit((*((s32 *) (((char *) (*((s32 **) (((char *) arg1) + 0x24)))) + 0))) + off, rec);
            i += 1;
            off += 12;
        } while (i < ((s32) (*((u16 *) (((char *) (*((s32 **) (((char *) arg1) + 0x24)))) + 4)))));
    }
    done(rec);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_the_chain_of_a_guard_body_and_test_goes_through_one_local_read_again_at_the_bottom():
    children = variants(SOURCE, 'walk')
    assert len(children) == 1 and children[0][0] == FAMILY
    text = _flat(children[0][1])
    local = '__repair_chain_arg1_0x24'
    assert f's32 *{local};' in text
    assert f'i = 0; {local} = {CHAIN}; if (inline_fn(*((u16 *) (((char *) ({local})) + 4))) > 0) {{' in text
    assert f'visit((*((s32 *) (((char *) ({local})) + 0))) + off, rec);' in text
    assert f'off += 12; {local} = {CHAIN}; }} while (i < ((s32) (*((u16 *) (((char *) ({local})) + 4)))));' in text
    # one read before the guard, one at the bottom: the chain is spelled out nowhere else
    assert text.count(CHAIN) == 2


def test_nothing_when_the_body_does_not_name_the_chain_or_the_pointer_moves():
    no_body = SOURCE.replace('visit((*((s32 *) (((char *) (*((s32 **) (((char *) arg1) + 0x24)))) + 0))) + off, rec);', 'visit(off, rec);')
    assert variants(no_body, 'walk') == []
    moved = SOURCE.replace('i += 1;', 'arg1 = rec;')
    assert variants(moved, 'walk') == []
    assert variants('void f(s32 *p) { while (*p) { g(); } }', 'f') == []


def test_the_family_is_registered():
    from decomprepair import registry
    assert any(entry.module.endswith('loop_chain_cache') for entry in registry.declared())
    assert loop_chain_cache.REPAIR['needs'] == ('source', 'name')
