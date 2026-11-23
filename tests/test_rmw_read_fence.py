"""rmw_read_fence: a global's increment after a may-alias store, read before the store behind a loop note (60 -> 0)."""
from decomprepair import rmw_read_fence as f

SOURCE = '''typedef struct { u8 pad[16]; u32 color; } Item;
extern u16 gTick;
extern u16 gAlpha;

void pulse(Item *current) {
    u32 m;
    u32 packed;
    m = current->color & (~255);
    packed = m | (gAlpha << 3);
    *((volatile u32 *) (&current->color)) = packed;
    gTick++;
}
'''


def test_the_counter_is_read_in_a_one_shot_scope_before_the_store():
    ((family, text),) = f.variants(SOURCE, 'pulse')
    assert family == f.FAMILY
    body = text.split('void pulse')[1]
    assert 'u16 rmw_c;' in body
    order = [body.index(x) for x in ('packed = m | (gAlpha << 3);', 'do {', 'rmw_c = gTick;', '} while (0);',
                                     '*((volatile u32 *) (&current->color)) = packed;', 'gTick = rmw_c + 1;')]
    assert order == sorted(order)
    assert 'gTick++' not in body


def test_other_increment_spellings_and_the_header_type():
    assert 'gTick = rmw_c + 2;' in f.variants(SOURCE.replace('gTick++;', 'gTick += 2;'), 'pulse')[0][1]
    assert 'gTick = rmw_c + 1;' in f.variants(SOURCE.replace('gTick++;', 'gTick = gTick + 1;'), 'pulse')[0][1]
    moved = SOURCE.replace('extern u16 gTick;\n', '')
    assert f.variants(moved, 'pulse') == []
    assert 's32 rmw_c;' in f.variants(moved, 'pulse', header='extern s32 gTick;\n')[0][1]


def test_shapes_it_leaves_alone():
    assert f.variants(SOURCE.replace('*((volatile u32 *) (&current->color)) = packed;', 'current->color = packed;'),
                      'pulse') == []
    assert f.variants(SOURCE.replace('= packed;', '= packed + gTick;'), 'pulse') == []
    assert f.variants(SOURCE.replace('extern u16 gTick;', 'extern u16 *gTick;'), 'pulse') == []
    assert f.variants(SOURCE.replace('extern u16 gTick;', 'extern volatile u16 gTick;'), 'pulse') == []
    assert f.variants(SOURCE, 'missing') == []


def test_the_module_declares_itself_for_the_registry():
    assert f.REPAIR['variants'] is f.variants and f.REPAIR['families'] == f.FAMILIES
    assert f.REPAIR['needs'] == ('source', 'name', 'header')


def test_the_retired_shared_local_shape_is_covered_by_the_fence():
    """volatile_rmw_counter_share (retired) wrote the counter into the masked value's local: two deaths, a global
    pseudo, 25 at best on the function both were measured on, where this family reached 0. Its exact shape is fenced."""
    import importlib.util
    assert importlib.util.find_spec('decomprepair.volatile_rmw_counter_share') is None
    source = ('typedef struct { u8 pad[16]; u32 color; } Item;\nextern u16 gTick;\nextern u16 gAlpha;\n\n'
              'void pulse(Item *current) {\n'
              '    *((volatile u32 *) (&current->color)) = (current->color & (~255)) | (gAlpha << 3);\n'
              '    gTick++;\n}\n')
    ((family, text),) = f.variants(source, 'pulse')
    body = text.split('void pulse')[1]
    assert 'rmw_c = gTick;' in body and 'gTick = rmw_c + 1;' in body
