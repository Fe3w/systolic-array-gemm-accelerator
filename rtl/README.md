# rtl/

Synthesizable SystemVerilog only (rules in `docs/CONVENTIONS.md`). One module per file,
file name = module name, modules prefixed `sa_`. Suggested layout as blocks appear:

- `common/` small reusable pieces (pipeline registers, skew lines)
- `pe/` processing element `sa_pe`
- `array/` `sa_array`, skew/de-skew
- `mem/` buffer models, accumulator
- `dma/` DMA engine
- `ctrl/` command decoder and controller FSM
- `top/` `sa_top`

Every module needs a spec in `docs/spec/` and a cocotb test in `tb/` before it is written.
