// sa_sram: behavioural 1-read / 1-write memory (docs/spec/buffers.md §1, D-017).
//
//   write: mem[waddr] <= wdata at the edge where we = 1
//   read:  rdata <= mem[raddr] at the edge where re = 1 (1-cycle latency);
//          rdata holds its value while re = 0
//   same-address read and write in one cycle: rdata gets the OLD contents
//   (read-first), because both non-blocking assignments sample mem before the edge.
//
// No reset (D-005a): contents and rdata are data, defined once written / read.
// Written in the plain style Yosys recognizes as a RAM with a registered read port.
`default_nettype none

module sa_sram #(
    parameter  int WIDTH  = 8,
    parameter  int DEPTH  = 4,
    localparam int ADDR_W = (DEPTH > 1) ? $clog2(DEPTH) : 1
) (
    input  wire logic              clk,
    input  wire logic              we,
    input  wire logic [ADDR_W-1:0] waddr,
    input  wire logic [ WIDTH-1:0] wdata,
    input  wire logic              re,
    input  wire logic [ADDR_W-1:0] raddr,
    output logic      [ WIDTH-1:0] rdata
);

  logic [WIDTH-1:0] mem[DEPTH];
  logic [WIDTH-1:0] rdata_q;

  always_ff @(posedge clk) begin
    if (we) begin
      mem[waddr] <= wdata;
    end
    if (re) begin
      rdata_q <= mem[raddr];
    end
  end

  assign rdata = rdata_q;

endmodule

`default_nettype wire
