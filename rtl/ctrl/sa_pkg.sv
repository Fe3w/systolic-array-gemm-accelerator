// sa_pkg: command format shared by sa_ctrl and the Python compiler (docs/spec/ctrl.md §1, D-021).
//
// Mirrored field by field by compiler/sysarray/commands.py; the pytest
// compiler/tests/test_commands.py parses this file and fails if they differ.
`default_nettype none

// `make lint` passes this package to every module's lint run; most modules use
// none of it, so unused-parameter warnings are waived for the package only.
/* verilator lint_off UNUSEDPARAM */
package sa_pkg;

  localparam int OP_W   = 3;   // 4 opcodes used; 4..7 are reported as unknown
  localparam int MA_W   = 32;  // memory byte address / stride
  localparam int ROWS_W = 9;   // 0..511 (valid 1..256)
  localparam int BA_W   = 8;   // buffer row address (depth 256, D-016)
  localparam int DEPTH  = 256;

  typedef enum logic [OP_W-1:0] {
    OP_LOAD_W  = 3'd0,
    OP_LOAD_A  = 3'd1,
    OP_COMPUTE = 3'd2,
    OP_STORE   = 3'd3
  } op_t;

  // Fields MSB first: 3 + 1 + 32 + 32 + 9 + 8 + 8 = 93 bits.
  typedef struct packed {
    op_t op;
    logic acc_mode;              // COMPUTE: 0 = OVERWRITE, 1 = ACCUMULATE
    logic [MA_W-1:0] mem_addr;
    logic [MA_W-1:0] mem_stride;
    logic [ROWS_W-1:0] rows;
    logic [BA_W-1:0] buf_addr;   // LOAD_A / COMPUTE: input-buffer row; STORE: accumulator row
    logic [BA_W-1:0] acc_addr;   // COMPUTE: accumulator row
  } cmd_t;

  // Written out (not $bits) so Yosys can parse the package: 3 + 1 + 32 + 32 + 9 + 8 + 8.
  localparam int CMD_W = OP_W + 1 + 2 * MA_W + ROWS_W + 2 * BA_W;

  // Error codes (sticky err_code), lowest applicable code wins.
  localparam logic [2:0] ERR_NONE       = 3'd0;
  localparam logic [2:0] ERR_OPCODE     = 3'd1;
  localparam logic [2:0] ERR_ROWS       = 3'd2;
  localparam logic [2:0] ERR_RANGE      = 3'd3;
  localparam logic [2:0] ERR_NO_WEIGHTS = 3'd4;
  localparam logic [2:0] ERR_UNWRITTEN  = 3'd5;  // reads buffer/accumulator rows never written

endpackage
/* verilator lint_on UNUSEDPARAM */

`default_nettype wire
