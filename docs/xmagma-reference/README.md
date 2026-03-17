# Magma `-x` Protocol Reference

This directory contains reference materials for the Magma `-x` (programmatic
interaction) protocol, included here for documentation purposes.

## Files

- **`API`** — Protocol specification by Geoff Bailey (December 2024).
  Authoritative reference for the tagged output format, input handling,
  state machine, and all tag types.  This is the primary document that
  `magma_kernel/protocol.py` was implemented against.

- **`xmagma.c`** — Reference C implementation of a `-x` frontend by
  Geoff Bailey.  A single-file interactive terminal client that spawns
  `magma -x`, parses tagged output, and manages I/O.  The parser
  (`parse_magma_line`), output assembler (`process_output_tag`), and
  tag dispatch logic (`process_line`) in `protocol.py` are ports of
  the corresponding functions in this file.

## Provenance

These files were written by Geoff Bailey and are distributed with Magma.
They are included here unmodified as reference documentation for
contributors working on the kernel's protocol layer.  They are **not**
part of the kernel's runtime code or build.

## Relationship to the Kernel

| Reference | Kernel equivalent |
|-----------|-------------------|
| `API` — tag table | `protocol.py` — `TAG_INFO` dict |
| `API` — input/output protocol | `protocol.py` — `MagmaProcess.send_input`, `process_until_ready` |
| `xmagma.c:parse_magma_line` | `protocol.py:parse_line` |
| `xmagma.c:process_output_tag` | `protocol.py:OutputAccumulator` |
| `xmagma.c:process_line` | `protocol.py:process_until_ready` (tag dispatch) |
| `xmagma.c:read_line_from_magma` | `protocol.py:MagmaProcess._read_line` |
| `xmagma.c:spawn_magma` | `protocol.py:MagmaProcess.start` |
