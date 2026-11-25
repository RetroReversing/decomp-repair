#!/usr/bin/env python3
"""Compile the library's hot, pure modules with Cython, next to their sources (optional).

The modules in NATIVE are the ones nearly every repair family imports (the statement scanner, the C source helpers,
the MIPS readers): each trial calls them thousands of times. Cython compiles them unchanged from plain Python, so
there is one source of truth. Python's import system prefers a compiled `<name>.<abi>.so` to `<name>.py` in the same
folder, so building is all it takes, and deleting the `.so` files (`--clean`) restores the interpreted modules.

Without Cython or a C compiler nothing is built and nothing changes. `DECOMPREPAIR_NATIVE=0` has no effect at import
(the choice is which files exist), so tests run both ways by building and cleaning.

    build_native.py            build every module in NATIVE into src/decomprepair/
    build_native.py --clean    remove the compiled modules
"""
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "decomprepair"

# Add a module here once its tests pass compiled. Keep to modules that don't read their own source or `__file__`.
NATIVE = [
    "integer_repair_support",
    "pattern_repairs",
    "csource",
    "mips",
    "local_flow",
    "line_scan",
    "integer_abi",
    "mips_returns",
    "call_lifetime_repairs",
    "operand_lifetime_repairs",
    "large_stack_drafts",
    "compiler_phase_repairs",
    "measured_stack_drafts",
    "clamp_return_local",
    "allocator_call_guards",
    "pointer_pair_repairs",
    "c_scan",
    "m2cfix",
    "goto_structure_repairs",
    "arm_block_support",
    "target_call_arity_repairs",
    "loop_address_hoist_repairs",
    "identical_arm_collapse_repairs",
    "target_memory_repairs",
    "case_temporary_repairs",
    "branch_call_support",
    "mips_addresses",
    "shared_default_drafts",
    "stack_read_retry",
    "frame_padding_repairs",
    "equal_value_flow",
    "loaded_byte_repairs",
    "reassigned_local_inline",
    "hand_found_support",
    "permuter_macro_effects",
    "mips_regions",
    "narrow_store_repairs",
    "trig_axis_reuse",
    "balanced_clamp_predicates",
    "float_literal_global",
    "declaration_scope_sink_repairs",
    "phase_lifetime_repairs",
    "compiler_shape_repairs",
    "passthrough_argument_repairs",
    "sdk_io_repairs",
    "local_inline_repairs",
    "target_conversion_order_repairs",
    "balanced_float_predicate_return",
    "display_cursor_record_repairs",
    "float_bit_argument_repairs",
]


def compiled() -> list[Path]:
    return [p for name in NATIVE for p in PACKAGE.glob(f"{name}.*") if p.suffix in (".so", ".pyd")]


def clean() -> None:
    for path in compiled():
        path.unlink()


def main(argv: list[str]) -> int:
    clean()
    if "--clean" in argv:
        return 0
    try:
        from Cython.Build import cythonize
        from setuptools import Extension
        from setuptools.dist import Distribution
    except ImportError:
        print("Cython or setuptools is unavailable: the library stays interpreted.")
        return 0
    built = 0
    for name in NATIVE:
        # one module at a time: a module Cython can't translate stays interpreted without blocking the others
        with tempfile.TemporaryDirectory(prefix="decomprepair-native-") as work:
            try:
                extensions = cythonize([Extension(f"decomprepair.{name}", [str(PACKAGE / f"{name}.py")])],
                                       build_dir=work, quiet=True, compiler_directives={"language_level": "3"})
                dist = Distribution({"ext_modules": extensions, "package_dir": {"": "src"},
                                     "packages": ["decomprepair"]})
                command = dist.get_command_obj("build_ext")
                command.build_lib = work
                command.build_temp = str(Path(work) / "tmp")
                command.ensure_finalized()
                command.run()
            except (Exception, SystemExit) as error:  # no C compiler or headers, or code Cython can't translate
                print(f"{name}: not built, stays interpreted ({str(error)[:200]})")
                continue
            for path in Path(work).rglob("decomprepair/*"):
                if path.suffix in (".so", ".pyd"):
                    (PACKAGE / path.name).write_bytes(path.read_bytes())
                    built += 1
    print(f"Built {built} native modules into {PACKAGE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
