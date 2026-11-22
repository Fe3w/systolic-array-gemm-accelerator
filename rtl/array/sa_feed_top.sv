// sa_feed_top: weight buffer + input buffer + sa_feeder + sa_array (docs/spec/buffers.md §6).
//
// Test/integration top for M5. The buffers' write ports are exposed so a
// testbench (later: the DMA, M6) can fill them; the feeder runs LOAD_W / STREAM
// commands that read the buffers into the array. Purely structural.
`default_nettype none

module sa_feed_top #(
    parameter  int S        = 4,
    parameter  int IN_DEPTH = 256,
    parameter  int DATA_W   = 8,
    parameter  int ACC_W    = 32,
    localparam int ROW_W    = S * DATA_W,
    localparam int WA_W     = (S > 1) ? $clog2(S) : 1,
    localparam int IA_W     = (IN_DEPTH > 1) ? $clog2(IN_DEPTH) : 1
) (
    input  wire logic                    clk,
    input  wire logic                    rst,
    // buffer write ports
    input  wire logic                    wb_we,
    input  wire logic [        WA_W-1:0] wb_waddr,
    input  wire logic [       ROW_W-1:0] wb_wdata,
    input  wire logic                    ib_we,
    input  wire logic [        IA_W-1:0] ib_waddr,
    input  wire logic [       ROW_W-1:0] ib_wdata,
    // command
    input  wire logic                    start,
    input  wire logic                    op,
    input  wire logic [        IA_W-1:0] base,
    input  wire logic [          IA_W:0] rows,
    output logic                         busy,
    output logic                         done,
    output logic                         start_dropped,
    // array outputs
    output logic                         c_valid,
    output logic      [S-1:0][ACC_W-1:0] c_row
);

  logic                    wb_re, ib_re;
  logic [        WA_W-1:0] wb_raddr;
  logic [        IA_W-1:0] ib_raddr;
  logic [       ROW_W-1:0] wb_rdata, ib_rdata;
  logic                    w_load, a_valid;
  logic [S-1:0][DATA_W-1:0] w_row, a_row;

  sa_sram #(
      .WIDTH(ROW_W),
      .DEPTH(S)
  ) u_wbuf (
      .clk  (clk),
      .we   (wb_we),
      .waddr(wb_waddr),
      .wdata(wb_wdata),
      .re   (wb_re),
      .raddr(wb_raddr),
      .rdata(wb_rdata)
  );

  sa_sram #(
      .WIDTH(ROW_W),
      .DEPTH(IN_DEPTH)
  ) u_ibuf (
      .clk  (clk),
      .we   (ib_we),
      .waddr(ib_waddr),
      .wdata(ib_wdata),
      .re   (ib_re),
      .raddr(ib_raddr),
      .rdata(ib_rdata)
  );

  sa_feeder #(
      .S       (S),
      .IN_DEPTH(IN_DEPTH),
      .DATA_W  (DATA_W)
  ) u_feeder (
      .clk          (clk),
      .rst          (rst),
      .start        (start),
      .op           (op),
      .base         (base),
      .rows         (rows),
      .busy         (busy),
      .done         (done),
      .start_dropped(start_dropped),
      .wb_re        (wb_re),
      .wb_raddr     (wb_raddr),
      .wb_rdata     (wb_rdata),
      .ib_re        (ib_re),
      .ib_raddr     (ib_raddr),
      .ib_rdata     (ib_rdata),
      .w_load       (w_load),
      .w_row        (w_row),
      .a_valid      (a_valid),
      .a_row        (a_row)
  );

  sa_array #(
      .S     (S),
      .DATA_W(DATA_W),
      .ACC_W (ACC_W)
  ) u_array (
      .clk    (clk),
      .rst    (rst),
      .w_load (w_load),
      .w_row  (w_row),
      .a_valid(a_valid),
      .a_row  (a_row),
      .c_valid(c_valid),
      .c_row  (c_row)
  );

endmodule

`default_nettype wire
