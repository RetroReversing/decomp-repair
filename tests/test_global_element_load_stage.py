"""A global's element stored last, read into a local above the statement before it."""
from decomprepair import global_element_load_stage as p
from decomprepair import registry

SOURCE = '''extern u8 gTags[];
void flip(Thing *thing)
{
    thing->velX = -thing->velX;
    thing->velY = -thing->velY;
    thing->state = gTags[3];
    apply(thing);
}
'''


def test_the_read_goes_above_the_statement_before_first():
    children = [child for _, child in p.variants(SOURCE, 'flip')]
    assert len(children) == 2
    assert 'u8 temp_copy;' in children[0]
    assert ('    thing->velX = -thing->velX;\n    temp_copy = gTags[3];\n    thing->velY = -thing->velY;\n'
            '    thing->state = temp_copy;\n') in children[0]


def test_the_header_may_declare_the_global():
    assert p.variants(SOURCE.replace('extern u8 gTags[];\n', ''), 'flip', 'extern u8 gTags[];\n')


def test_declined_without_a_type_or_past_a_call_or_a_write_of_it():
    unknown = SOURCE.replace('extern u8 gTags[];\n', '')
    call = SOURCE.replace('    thing->state', '    ping();\n    thing->state')
    written = SOURCE.replace('    thing->state', '    gTags[3] = 0;\n    thing->state')
    for source in (unknown, call, written):
        assert p.variants(source, 'flip') == [], source


def test_the_module_declares_itself():
    assert any(repair.module == 'global_element_load_stage' for repair in registry.declared())
