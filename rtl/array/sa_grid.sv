// sa_grid: S x S grid of sa_pe, weight-stationary, no skew (docs/spec/array.md, D-014).
//
//   PE(r, c) takes  a, a_valid  from PE(r, c-1)  (west edge: a_in[r], a_valid_in[r])
//                   psum, w     from PE(r-1, c)  (north edge: 0 and w_in[c])
//   South edge: psum_out[c] = bottom PE's psum_out; valid_out[c] = its a_valid_out
//   delayed one cycle (the add stage of the two-stage MAC).
//
// Inputs must already be skewed: A[m][r] enters row r in cycle t0 + m + r
// (sa_array does that). Column c then shows row m in cycle t0 + m + S + c + 1
// (two-stage MAC since M7b).
// The grid's only own registers are the S column valids on the south edge.
`default_nettype none

module sa_grid #(
    parameter int S      = 4,   // array side, >= 1
    parameter int DATA_W = 8,
    parameter int ACC_W  = 32
) (
    input  wire logic                     clk,
    input  wire logic                     rst,
    input  wire logic                     w_load,
    input  wire logic [S-1:0][DATA_W-1:0] w_in,        // top of each column
    input  wire logic [S-1:0][DATA_W-1:0] a_in,        // west edge, one per row
    input  wire logic [S-1:0]             a_valid_in,  // west edge, one per row
    output logic      [S-1:0][ ACC_W-1:0] psum_out,    // south edge, one per column
    output logic      [S-1:0]             valid_out    // south edge, qualifies psum_out
);

  // Inter-PE nets. Index [r][c] is the output of PE(r, c).
  logic signed [DATA_W-1:0] a_q    [S][S];
  logic                     av_q   [S][S];
  logic signed [ ACC_W-1:0] psum_q [S][S];
  logic signed [DATA_W-1:0] w_q    [S][S];

  for (genvar r = 0; r < S; r++) begin : g_row
    for (genvar c = 0; c < S; c++) begin : g_col
      logic signed [DATA_W-1:0] a_west;
      logic                     av_west;
      logic signed [ ACC_W-1:0] psum_north;
      logic signed [DATA_W-1:0] w_north;

      // West neighbour, or the grid's west edge for column 0.
      if (c == 0) begin : g_west_edge
        assign a_west  = a_in[r];
        assign av_west = a_valid_in[r];
      end else begin : g_west_pe
        assign a_west  = a_q[r][c-1];
        assign av_west = av_q[r][c-1];
      end

      // North neighbour, or the grid's north edge for row 0.
      if (r == 0) begin : g_north_edge
        assign psum_north = '0;
        assign w_north    = w_in[c];
      end else begin : g_north_pe
        assign psum_north = psum_q[r-1][c];
        assign w_north    = w_q[r-1][c];
      end

      sa_pe #(
          .DATA_W(DATA_W),
          .ACC_W (ACC_W)
      ) u_pe (
          .clk        (clk),
          .rst        (rst),
          .w_load     (w_load),
          .w_in       (w_north),
          .w_out      (w_q[r][c]),
          .a_in       (a_west),
          .a_valid_in (av_west),
          .a_out      (a_q[r][c]),
          .a_valid_out(av_q[r][c]),
          .psum_in    (psum_north),
          .psum_out   (psum_q[r][c])
      );
    end
  end

  // South edge. With the two-stage MAC (M7b) the bottom PE's sum appears one
  // cycle after its a_valid_out, so the column valid is delayed by one register.
  logic [S-1:0] valid_out_q;

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_out_q <= '0;
    end else begin
      for (int c = 0; c < S; c++) begin
        valid_out_q[c] <= av_q[S-1][c];
      end
    end
  end

  for (genvar c = 0; c < S; c++) begin : g_south
    assign psum_out[c]  = psum_q[S-1][c];
    assign valid_out[c] = valid_out_q[c];
  end

  // The east edge (a_q/av_q of column S-1) and the bottom row's w_q have no
  // consumer: activations leave the grid and weights stop at the last row.
  // Synthesis removes those flops' fan-out; Verilator does not flag partly used arrays.

endmodule

`default_nettype wire
