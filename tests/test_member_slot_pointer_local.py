"""A member slot accessed twice in a block, held in a pointer local."""
from decomprepair import member_slot_pointer_local as t

SOURCE = '''void f(void *obj)
{
    void *p;
    s32 i;

    p = obj;
    i = 0;
    do
    {
        if ((*((void **) (((char *) p) + 0x418))) == NULL)
        {
            *((void **) (((char *) p) + 0x418)) = make(i);
            if (*((void **) (((char *) p) + 0x418)) != NULL)
            {
                use(*((void **) (((char *) p) + 0x418)), i);
            }
        }
        p += 4;
        i += 1;
    }
    while (i < 4);
}
'''


def test_the_slot_is_a_local_in_the_block_that_holds_the_accesses():
    # A 1133-instruction effect spawner: 7905 -> 6798 with the store and the later read through `slot`, the test before
    # the block left as written (loop.c then derives the slot's address from the counter's giv once per iteration).
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert out
    inside = [o for o in out if 'void ** p_slot_418 = (void **) (((char *) p) + 0x418);\n' in o and 'if ((*((void **) (((char *) p) + 0x418))) == NULL)' in o]
    assert inside
    assert '(*p_slot_418) = make(i);' in inside[0] and 'use((*p_slot_418), i);' in inside[0]


def test_left_alone_when_the_base_changes_or_there_is_one_access():
    single = 'void f(void *p)\n{\n    if (g)\n    {\n        *((void **) (((char *) p) + 8)) = 0;\n    }\n}\n'
    assert t.variants(single, 'f') == []
    # the base is assigned inside the block that would hold the local: no child for that block
    changed = SOURCE.replace('make(i);', 'make(i); p = other;')
    assert all('void ** p_slot_418 = (void **) (((char *) p) + 0x418);\n            (*p_slot_418) = make' not in o
               for _, o in t.variants(changed, 'f'))


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'member_slot_pointer_local' for r in registry.declared())
