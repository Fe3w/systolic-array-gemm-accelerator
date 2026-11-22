// sa_array: S x S weight-stationary array with input skew and output de-skew
// (docs/spec/array.md, D-014).
//
//   a_row (all S elements in one cycle) --skew: row r delayed r cycles--> sa_grid
//   sa_grid column c --de-skew: delayed S-1-c cycles--> c_row[c]
//
// A valid a_row presented in cycle t appears as c_row with c_valid = 1 in cycle
// t + 2S (2S - 1 before the M7b two-stage MAC; asserted by tb/array). Weights load through
// the per-column shift chain (D-012): S cycles of w_load, last weight row first.
// Usage rules (no compute during load, reload after drain, D-015): spec §3.
`default_nettype none

module sa_array #(
    parameter int S      = 4,
    parameter int DATA_W = 8,
    parameter int ACC_W  = 32
) (
    input  wire logic                     clk,
    input  wire logic                     rst,
    input  wire logic                     w_load,
    input  wire logic [S-1:0][DATA_W-1:0] w_row,
    input  wire logic                     a_valid,
    input  wire logic [S-1:0][DATA_W-1:0] a_row,
    output logic                          c_valid,
    output logic      [S-1:0][ ACC_W-1:0] c_row
);

  // Skewed grid inputs and raw grid outputs.
  logic [S-1:0][DATA_W-1:0] grid_a;
  logic [S-1:0]             grid_a_valid;
  logic [S-1:0][ ACC_W-1:0] grid_psum;
  logic [S-1:0]             grid_valid;
  // Only deskew_valid[0] drives c_valid; the other columns' de-skewed valids are
  // identical by construction and left unused (see c_valid below).
  /* verilator lint_off UNUSEDSIGNAL */
  logic [S-1:0]             deskew_valid;
  /* verilator lint_on UNUSEDSIGNAL */

  // Input skew: row r is delayed by r cycles (row 0 is a wire).
  for (genvar r = 0; r < S; r++) begin : g_skew
    sa_reg #(
        .W(DATA_W),
        .D(r)
    ) u_skew (
        .clk      (clk),
        .rst      (rst),
        .in_valid (a_valid),
        .in_data  (a_row[r]),
        .out_valid(grid_a_valid[r]),
        .out_data (grid_a[r])
    );
  end

  sa_grid #(
      .S     (S),
      .DATA_W(DATA_W),
      .ACC_W (ACC_W)
  ) u_grid (
      .clk       (clk),
      .rst       (rst),
      .w_load    (w_load),
      .w_in      (w_row),
      .a_in      (grid_a),
      .a_valid_in(grid_a_valid),
      .psum_out  (grid_psum),
      .valid_out (grid_valid)
  );

  // Output de-skew: column c is delayed by S-1-c cycles (column S-1 is a wire),
  // so every column of one activation row leaves in the same cycle.
  for (genvar c = 0; c < S; c++) begin : g_deskew
    sa_reg #(
        .W(ACC_W),
        .D(S - 1 - c)
    ) u_deskew (
        .clk      (clk),
        .rst      (rst),
        .in_valid (grid_valid[c]),
        .in_data  (grid_psum[c]),
        .out_valid(deskew_valid[c]),
        .out_data (c_row[c])
    );
  end

  // All de-skewed valids are equal by construction (same row, same cycle); use
  // column 0's. The others stay unconnected (synthesis removes their flops); the
  // tests check every column's data, so a misaligned column would fail.
  assign c_valid = deskew_valid[0];

endmodule

`default_nettype wire
