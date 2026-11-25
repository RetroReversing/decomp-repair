from decomprepair import registry
from decomprepair.array_index_from_one import FAMILY, REPAIR, variants

SOURCE = """void fill(f32 *out, s32 i) {
    Vec3 pts[4];
    pts[0].x = 1.0f;
    pts[3].y = out[0];
    *out = pts[i].x;
}
"""


def kids(source=SOURCE, asm=''):
    return [c for f, c in variants(source, 'fill', asm=asm) if f == FAMILY]


def test_the_array_grows_by_one_and_every_index_moves_up():
    child = kids()[0]
    assert 'Vec3 pts[5];' in child
    assert 'pts[1].x = 1.0f;' in child and 'pts[4].y' in child and 'pts[i + 1].x' in child


def test_a_bare_use_or_an_address_leaves_it_alone():
    assert not kids(SOURCE.replace('*out = pts[i].x;', 'use(pts);'))
    assert not kids(SOURCE.replace('*out = pts[i].x;', 'use(&pts);'))
    assert 'use(&pts[2]);' in kids(SOURCE.replace('*out = pts[i].x;', 'use(&pts[1]);'))[0]


def test_the_assembly_gate_wants_the_frame_addressed():
    assert kids(asm='lw $v0, 0x10($sp)\n')
    assert not kids(asm='addu $v0, $a0, $a1\n')


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
