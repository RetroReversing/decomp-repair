from decomprepair import registry
from decomprepair.call_tail_store_label import FAMILY, variants

SOURCE = """void motion(void *arg0, void *rec) {
    f32 a;
    f32 b;
    a = *((f32 *) (((char *) rec) + 0x4C));
    if (check(rec) != 0) {
        a = a * cosAngle(*((f32 *) (((char *) arg0) + 0x40)));
        *((f32 *) (((char *) rec) + 0x38)) = 0.0f;
        b = a;
        *((s8 *) (((char *) rec) + 0x17E)) = (unsigned char) 2;
        requestSound(0xFF);
        *((f32 *) (((char *) rec) + 0xCC)) = 0.0f;
        goto join;
    }
    b = 1.0f;
    goto join;
    join:
    finish(arg0, b);
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'motion') if f == FAMILY]


def test_the_stores_after_the_last_call_move_into_a_block_the_arm_jumps_to():
    got = children()
    assert len(got) == 1
    child = got[0]
    arm = child[child.index('if (check'):child.index('b = 1.0f;')]
    assert arm.rstrip().endswith('requestSound(0xFF);\n        goto join_tail;\n    }')
    assert '0xCC' not in arm
    tail = child[child.index('join_tail:'):]
    assert tail.index('0xCC)) = 0.0f;') < tail.index('join:')
    # whatever reached `join` before still skips the moved store
    assert 'goto join;\n    join_tail:\n' in child


def test_a_call_among_the_following_statements_or_no_goto_leaves_the_arm_alone():
    assert children(SOURCE.replace('= 0.0f;\n        goto join;', '= f(0);\n        goto join;')) == []
    assert children(SOURCE.replace('= 0.0f;\n        goto join;\n    }', '= 0.0f;\n    }')) == []


def test_it_declares_itself():
    assert registry.get('call_tail_store_label') is not None
    assert registry.problems(registry.get('call_tail_store_label')) == []
