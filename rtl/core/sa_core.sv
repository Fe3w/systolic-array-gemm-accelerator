// sa_core: DMA + weight/input buffers + feeder + array + accumulator (docs/spec/acc.md §2).
//
// Purely structural. The DMA fills the buffers (LOAD) and drains the
// accumulator (STORE); the feeder reads the buffers into the array; the
// accumulator collects the array's output rows. Commands arrive on separate
// DMA and feeder ports. The accumulator configuration (mode, base row) is
// latched when the feeder accepts a STREAM and turned into a per-row tag
// (mode, base + j) next to the row's a_valid; the tag is delayed by the array
// latency 2S so it arrives with the row's c_valid (M13, removes D-024's gap). Sequencing rules (reload after
// drain, STORE after the last accumulator write) are the user's job until the
// M8 controller.
`default_nettype none

module sa_core #(
    parameter  int S         = 8,
    parameter  int DATA_W    = 8,
    parameter  int ACC_W     = 32,
    parameter  int IN_DEPTH  = 256,
    parameter  int ACC_DEPTH = 256,
    parameter  int MA_W      = 32,
    localparam int BUS_W     = S * DATA_W,
    localparam int WA_W      = (S > 1) ? $clog2(S) : 1,
    localparam int IA_W      = (IN_DEPTH > 1) ? $clog2(IN_DEPTH) : 1,
    localparam int AA_W      = (ACC_DEPTH > 1) ? $clog2(ACC_DEPTH) : 1,
    localparam int BA_W      = (IA_W > AA_W) ? IA_W : AA_W
) (
    input  wire logic             clk,
    input  wire logic             rst,
    // DMA descriptor
    input  wire logic             dma_start,
    input  wire logic             dma_dir,
    input  wire logic             dma_target,
    input  wire logic [ MA_W-1:0] dma_mem_addr,
    input  wire logic [ MA_W-1:0] dma_mem_stride,
    input  wire logic [   BA_W:0] dma_rows,
    input  wire logic [ BA_W-1:0] dma_buf_addr,
    output logic                  dma_busy,
    output logic                  dma_done,
    output logic                  dma_dropped,
    // feeder command (+ accumulator config for STREAM)
    input  wire logic             f_start,
    input  wire logic             f_op,
    input  wire logic [ IA_W-1:0] f_base,
    input  wire logic [   IA_W:0] f_rows,
    input  wire logic             acc_mode,
    input  wire logic [ AA_W-1:0] acc_base,
    output logic                  f_busy,
    output logic                  f_done,
    output logic                  f_dropped,
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
    output logic      [BUS_W-1:0] wr_req_data
);

  localparam logic OP_STREAM = 1'b1;

  // buffer ports
  logic                     wb_we, ib_we, wb_re, ib_re;
  logic [         WA_W-1:0] wb_waddr, wb_raddr;
  logic [         IA_W-1:0] ib_waddr, ib_raddr;
  logic [        BUS_W-1:0] wb_wdata, ib_wdata, wb_rdata, ib_rdata;
  // feeder -> array -> accumulator
  logic                     w_load, a_valid, c_valid;
  logic [S-1:0][DATA_W-1:0] w_row, a_row;
  logic [S-1:0][ ACC_W-1:0] c_row;
  logic                     acc_cfg_valid;
  // per-row accumulator tag (M13)
  logic                     tag_mode_q;
  logic [         AA_W-1:0] tag_ptr_q;
  logic                     c_tag_valid;
  logic [           AA_W:0] c_tag;      // {mode, address}
  // DMA STORE <-> accumulator
  logic                     src_re;
  logic [         AA_W-1:0] src_raddr;
  logic [      S*ACC_W-1:0] src_rdata;

  sa_dma #(
      .S(S), .DATA_W(DATA_W), .ACC_W(ACC_W), .IN_DEPTH(IN_DEPTH), .ACC_DEPTH(ACC_DEPTH),
      .MA_W(MA_W)
  ) u_dma (
      .clk(clk), .rst(rst),
      .start(dma_start), .dir(dma_dir), .target(dma_target), .mem_addr(dma_mem_addr),
      .mem_stride(dma_mem_stride), .rows(dma_rows), .buf_addr(dma_buf_addr),
      .busy(dma_busy), .done(dma_done), .start_dropped(dma_dropped),
      .rd_req_valid(rd_req_valid), .rd_req_ready(rd_req_ready), .rd_req_addr(rd_req_addr),
      .rd_resp_valid(rd_resp_valid), .rd_resp_ready(rd_resp_ready), .rd_resp_data(rd_resp_data),
      .wr_req_valid(wr_req_valid), .wr_req_ready(wr_req_ready), .wr_req_addr(wr_req_addr),
      .wr_req_data(wr_req_data),
      .wb_we(wb_we), .wb_waddr(wb_waddr), .wb_wdata(wb_wdata),
      .ib_we(ib_we), .ib_waddr(ib_waddr), .ib_wdata(ib_wdata),
      .src_re(src_re), .src_raddr(src_raddr), .src_rdata(src_rdata)
  );

  sa_sram #(.WIDTH(BUS_W), .DEPTH(S)) u_wbuf (
      .clk(clk), .we(wb_we), .waddr(wb_waddr), .wdata(wb_wdata),
      .re(wb_re), .raddr(wb_raddr), .rdata(wb_rdata)
  );

  sa_sram #(.WIDTH(BUS_W), .DEPTH(IN_DEPTH)) u_ibuf (
      .clk(clk), .we(ib_we), .waddr(ib_waddr), .wdata(ib_wdata),
      .re(ib_re), .raddr(ib_raddr), .rdata(ib_rdata)
  );

  sa_feeder #(.S(S), .IN_DEPTH(IN_DEPTH), .DATA_W(DATA_W)) u_feeder (
      .clk(clk), .rst(rst),
      .start(f_start), .op(f_op), .base(f_base), .rows(f_rows),
      .busy(f_busy), .done(f_done), .start_dropped(f_dropped),
      .wb_re(wb_re), .wb_raddr(wb_raddr), .wb_rdata(wb_rdata),
      .ib_re(ib_re), .ib_raddr(ib_raddr), .ib_rdata(ib_rdata),
      .w_load(w_load), .w_row(w_row), .a_valid(a_valid), .a_row(a_row)
  );

  sa_array #(.S(S), .DATA_W(DATA_W), .ACC_W(ACC_W)) u_array (
      .clk(clk), .rst(rst),
      .w_load(w_load), .w_row(w_row), .a_valid(a_valid), .a_row(a_row),
      .c_valid(c_valid), .c_row(c_row)
  );

  // The accumulator configuration is latched when the feeder accepts a STREAM.
  assign acc_cfg_valid = f_start && !f_busy && (f_op == OP_STREAM);

  // Tag of the row entering the array: the STREAM's mode and base + j. A new STREAM
  // is accepted only after the previous one's last a_valid (feeder busy), so the
  // latch never changes under a row of the previous STREAM.
  always_ff @(posedge clk) begin
    if (acc_cfg_valid) begin
      tag_mode_q <= acc_mode;
      tag_ptr_q  <= acc_base;
    end else if (a_valid) begin
      tag_ptr_q <= tag_ptr_q + 1'b1;
    end
  end

  // Array latency: a_valid in cycle t -> c_valid in t + 2S (docs/spec/array.md §4.2).
  sa_reg #(.W(AA_W + 1), .D(2 * S)) u_tag (
      .clk(clk), .rst(rst),
      .in_valid(a_valid), .in_data({tag_mode_q, tag_ptr_q}),
      .out_valid(c_tag_valid), .out_data(c_tag)
  );

  // c_tag_valid equals c_valid by construction (checked by tb/core via the
  // results); only c_valid qualifies the accumulator.
  /* verilator lint_off UNUSEDSIGNAL */
  logic unused_tag_valid;
  assign unused_tag_valid = c_tag_valid;
  /* verilator lint_on UNUSEDSIGNAL */

  sa_acc #(.S(S), .ACC_W(ACC_W), .ACC_DEPTH(ACC_DEPTH)) u_acc (
      .clk(clk), .rst(rst),
      .c_valid(c_valid), .c_mode(c_tag[AA_W]), .c_addr(c_tag[AA_W-1:0]), .c_row(c_row),
      .st_re(src_re), .st_raddr(src_raddr), .st_rdata(src_rdata)
  );

endmodule

`default_nettype wire
