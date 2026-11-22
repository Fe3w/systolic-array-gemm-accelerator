// sa_acc: int32 accumulator buffer with a read-modify-write pipeline (docs/spec/acc.md §1).
//
//   cycle t   : c_valid with a row and its own tag (c_mode, c_addr = p; M13: the tag
//               travels with the row, so rows of different COMPUTEs may follow each
//               other in consecutive cycles); ACCUMULATE also reads row p
//   cycle t+1 : the BRAM read data is registered (M11b: cuts the BRAM clock-to-out
//               -> 32-bit add path that limited Fmax, results/synth/sa_core_S8_d4aedec*.json)
//   cycle t+2 : write c_row (OVERWRITE) or old[p] + c_row (ACCUMULATE, per element,
//               ACC_W-bit wrap) to row p
// Same-row rule: an ACCUMULATE row must arrive >= 3 cycles after the last write
// request to that row (write in t+2; read-first SRAM). The feeder spaces COMPUTEs
// by >= 4 cycles and rows of one COMPUTE are distinct, so this always holds.
// The STORE port (st_*) shares the SRAM read port; a STORE must not overlap a
// COMPUTE's outputs (spec rule; the controller enforces it from M8).
`default_nettype none

module sa_acc #(
    parameter  int S         = 8,
    parameter  int ACC_W     = 32,
    parameter  int ACC_DEPTH = 256,
    localparam int ROW_W     = S * ACC_W,
    localparam int AA_W      = (ACC_DEPTH > 1) ? $clog2(ACC_DEPTH) : 1
) (
    input  wire logic                    clk,
    input  wire logic                    rst,
    // array outputs with their per-row tag (M13)
    input  wire logic                    c_valid,
    input  wire logic                    c_mode,     // 0 = OVERWRITE, 1 = ACCUMULATE
    input  wire logic [        AA_W-1:0] c_addr,
    input  wire logic [S-1:0][ACC_W-1:0] c_row,
    // STORE read port
    input  wire logic                    st_re,
    input  wire logic [        AA_W-1:0] st_raddr,
    output logic      [       ROW_W-1:0] st_rdata
);

  localparam logic MODE_ACCUMULATE = 1'b1;

  // Stage 1 (cycle t+1): the arriving row with its own address and mode.
  logic                    s1_valid_q, s1_mode_q;
  logic [        AA_W-1:0] s1_addr_q;
  logic [S-1:0][ACC_W-1:0] s1_row_q;
  // Stage 2 (cycle t+2): plus the registered old row.
  logic                    s2_valid_q, s2_mode_q;
  logic [        AA_W-1:0] s2_addr_q;
  logic [S-1:0][ACC_W-1:0] s2_row_q, s2_old_q;

  logic                    rmw_re;
  logic                    mem_re;
  logic [        AA_W-1:0] mem_raddr;
  logic [       ROW_W-1:0] mem_rdata;
  logic [S-1:0][ACC_W-1:0] new_row;

  assign rmw_re    = c_valid && (c_mode == MODE_ACCUMULATE);
  assign mem_re    = rmw_re || st_re;
  assign mem_raddr = rmw_re ? c_addr : st_raddr;

  always_ff @(posedge clk) begin
    if (rst) begin
      s1_valid_q <= 1'b0;
      s2_valid_q <= 1'b0;
    end else begin
      s1_valid_q <= c_valid;
      s2_valid_q <= s1_valid_q;
    end
  end

  always_ff @(posedge clk) begin
    s1_addr_q <= c_addr;
    s1_mode_q <= c_mode;
    s1_row_q  <= c_row;
    s2_addr_q <= s1_addr_q;
    s2_mode_q <= s1_mode_q;
    s2_row_q  <= s1_row_q;
    s2_old_q  <= mem_rdata;  // the read issued in cycle t returns in t+1
  end

  // Element-wise add with ACC_W-bit wrap (D-004a), or pass-through for OVERWRITE.
  always_comb begin
    for (int i = 0; i < S; i++) begin
      new_row[i] = (s2_mode_q == MODE_ACCUMULATE) ? s2_old_q[i] + s2_row_q[i] : s2_row_q[i];
    end
  end

  sa_sram #(
      .WIDTH(ROW_W),
      .DEPTH(ACC_DEPTH)
  ) u_mem (
      .clk  (clk),
      .we   (s2_valid_q),
      .waddr(s2_addr_q),
      .wdata(new_row),
      .re   (mem_re),
      .raddr(mem_raddr),
      .rdata(mem_rdata)
  );

  assign st_rdata = mem_rdata;

endmodule

`default_nettype wire
