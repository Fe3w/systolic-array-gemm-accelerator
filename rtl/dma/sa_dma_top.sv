// sa_dma_top: sa_dma + weight buffer + input buffer + a STORE source SRAM (docs/spec/dma.md §6).
//
// Test top for M6. The buffers' read ports and the source's write port are
// exposed so the testbench can check LOAD results and prepare STORE data. In
// M6b the source becomes the accumulator and the buffers' read ports go to the
// feeder. Purely structural.
`default_nettype none

module sa_dma_top #(
    parameter  int S         = 8,
    parameter  int DATA_W    = 8,
    parameter  int ACC_W     = 32,
    parameter  int IN_DEPTH  = 256,
    parameter  int ACC_DEPTH = 256,
    parameter  int MA_W      = 32,
    localparam int BUS_W     = S * DATA_W,
    localparam int SRC_W     = S * ACC_W,
    localparam int WA_W      = (S > 1) ? $clog2(S) : 1,
    localparam int IA_W      = (IN_DEPTH > 1) ? $clog2(IN_DEPTH) : 1,
    localparam int AA_W      = (ACC_DEPTH > 1) ? $clog2(ACC_DEPTH) : 1,
    localparam int BA_W      = (IA_W > AA_W) ? IA_W : AA_W
) (
    input  wire logic             clk,
    input  wire logic             rst,
    // descriptor
    input  wire logic             start,
    input  wire logic             dir,
    input  wire logic             target,
    input  wire logic [ MA_W-1:0] mem_addr,
    input  wire logic [ MA_W-1:0] mem_stride,
    input  wire logic [   BA_W:0] rows,
    input  wire logic [ BA_W-1:0] buf_addr,
    output logic                  busy,
    output logic                  done,
    output logic                  start_dropped,
    // memory channels
    output logic                  rd_req_valid,
    input  wire logic             rd_req_ready,
    output logic      [ MA_W-1:0] rd_req_addr,
    input  wire logic             rd_resp_valid,
    output logic                  rd_resp_ready,
    input  wire logic [BUS_W-1:0] rd_resp_data,
    output logic                  wr_req_valid,
    input  wire logic             wr_req_ready,
    output logic      [ MA_W-1:0] wr_req_addr,
    output logic      [BUS_W-1:0] wr_req_data,
    // testbench access
    input  wire logic             wb_re,
    input  wire logic [ WA_W-1:0] wb_raddr,
    output logic      [BUS_W-1:0] wb_rdata,
    input  wire logic             ib_re,
    input  wire logic [ IA_W-1:0] ib_raddr,
    output logic      [BUS_W-1:0] ib_rdata,
    input  wire logic             src_we,
    input  wire logic [ AA_W-1:0] src_waddr,
    input  wire logic [SRC_W-1:0] src_wdata
);

  logic             wb_we, ib_we, src_re;
  logic [ WA_W-1:0] wb_waddr;
  logic [ IA_W-1:0] ib_waddr;
  logic [ AA_W-1:0] src_raddr;
  logic [BUS_W-1:0] wb_wdata, ib_wdata;
  logic [SRC_W-1:0] src_rdata;

  sa_dma #(
      .S        (S),
      .DATA_W   (DATA_W),
      .ACC_W    (ACC_W),
      .IN_DEPTH (IN_DEPTH),
      .ACC_DEPTH(ACC_DEPTH),
      .MA_W     (MA_W)
  ) u_dma (
      .clk          (clk),
      .rst          (rst),
      .start        (start),
      .dir          (dir),
      .target       (target),
      .mem_addr     (mem_addr),
      .mem_stride   (mem_stride),
      .rows         (rows),
      .buf_addr     (buf_addr),
      .busy         (busy),
      .done         (done),
      .start_dropped(start_dropped),
      .rd_req_valid (rd_req_valid),
      .rd_req_ready (rd_req_ready),
      .rd_req_addr  (rd_req_addr),
      .rd_resp_valid(rd_resp_valid),
      .rd_resp_ready(rd_resp_ready),
      .rd_resp_data (rd_resp_data),
      .wr_req_valid (wr_req_valid),
      .wr_req_ready (wr_req_ready),
      .wr_req_addr  (wr_req_addr),
      .wr_req_data  (wr_req_data),
      .wb_we        (wb_we),
      .wb_waddr     (wb_waddr),
      .wb_wdata     (wb_wdata),
      .ib_we        (ib_we),
      .ib_waddr     (ib_waddr),
      .ib_wdata     (ib_wdata),
      .src_re       (src_re),
      .src_raddr    (src_raddr),
      .src_rdata    (src_rdata)
  );

  sa_sram #(.WIDTH(BUS_W), .DEPTH(S)) u_wbuf (
      .clk(clk), .we(wb_we), .waddr(wb_waddr), .wdata(wb_wdata),
      .re(wb_re), .raddr(wb_raddr), .rdata(wb_rdata)
  );

  sa_sram #(.WIDTH(BUS_W), .DEPTH(IN_DEPTH)) u_ibuf (
      .clk(clk), .we(ib_we), .waddr(ib_waddr), .wdata(ib_wdata),
      .re(ib_re), .raddr(ib_raddr), .rdata(ib_rdata)
  );

  sa_sram #(.WIDTH(SRC_W), .DEPTH(ACC_DEPTH)) u_src (
      .clk(clk), .we(src_we), .waddr(src_waddr), .wdata(src_wdata),
      .re(src_re), .raddr(src_raddr), .rdata(src_rdata)
  );

endmodule

`default_nettype wire
