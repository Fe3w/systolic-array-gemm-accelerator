// sa_top: command controller + core (docs/spec/ctrl.md §5). Purely structural.
//
// The command port is a plain sa_pkg::CMD_W-bit vector (sa_pkg::cmd_t packed, MSB first)
// so testbenches and the compiler drive one integer per command.
`default_nettype none

module sa_top #(
    parameter  int S     = 8,
    localparam int BUS_W = S * 8
) (
    input  wire logic             clk,
    input  wire logic             rst,
    // commands
    input  wire logic             cmd_valid,
    output logic                  cmd_ready,
    input  wire logic [sa_pkg::CMD_W-1:0] cmd,
    // status and counters
    input  wire logic             err_clear,
    output logic                  err,
    output logic      [      2:0] err_code,
    output logic                  busy,
    output logic      [     47:0] cycles_total,
    output logic      [     47:0] cycles_dma,
    output logic      [     47:0] cycles_compute,
    output logic      [     47:0] macs_issued,
    // memory channels
    output logic                  rd_req_valid,
    input  wire logic             rd_req_ready,
    output logic      [ sa_pkg::MA_W-1:0] rd_req_addr,
    input  wire logic             rd_resp_valid,
    output logic                  rd_resp_ready,
    input  wire logic [BUS_W-1:0] rd_resp_data,
    output logic                  wr_req_valid,
    input  wire logic             wr_req_ready,
    output logic      [ sa_pkg::MA_W-1:0] wr_req_addr,
    output logic      [BUS_W-1:0] wr_req_data
);


  sa_pkg::cmd_t            cmd_s;
  logic            dma_start, dma_dir, dma_target, dma_busy, dma_done, dma_dropped;
  logic [sa_pkg::MA_W-1:0] dma_mem_addr, dma_mem_stride;
  logic [  sa_pkg::BA_W:0] dma_rows, f_rows;
  logic [sa_pkg::BA_W-1:0] dma_buf_addr, f_base, acc_base;
  logic            f_start, f_op, f_busy, f_done, f_dropped, acc_mode;

  assign cmd_s = sa_pkg::cmd_t'(cmd);

  sa_ctrl #(.S(S)) u_ctrl (
      .clk(clk), .rst(rst),
      .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd(cmd_s),
      .err_clear(err_clear), .err(err), .err_code(err_code), .busy(busy),
      .cycles_total(cycles_total), .cycles_dma(cycles_dma),
      .cycles_compute(cycles_compute), .macs_issued(macs_issued),
      .dma_start(dma_start), .dma_dir(dma_dir), .dma_target(dma_target),
      .dma_mem_addr(dma_mem_addr), .dma_mem_stride(dma_mem_stride), .dma_rows(dma_rows),
      .dma_buf_addr(dma_buf_addr), .dma_busy(dma_busy), .dma_done(dma_done),
      .f_start(f_start), .f_op(f_op), .f_base(f_base), .f_rows(f_rows),
      .acc_mode(acc_mode), .acc_base(acc_base), .f_busy(f_busy), .f_done(f_done)
  );

  sa_core #(.S(S), .IN_DEPTH(sa_pkg::DEPTH), .ACC_DEPTH(sa_pkg::DEPTH), .MA_W(sa_pkg::MA_W)) u_core (
      .clk(clk), .rst(rst),
      .dma_start(dma_start), .dma_dir(dma_dir), .dma_target(dma_target),
      .dma_mem_addr(dma_mem_addr), .dma_mem_stride(dma_mem_stride), .dma_rows(dma_rows),
      .dma_buf_addr(dma_buf_addr), .dma_busy(dma_busy), .dma_done(dma_done),
      .dma_dropped(dma_dropped),
      .f_start(f_start), .f_op(f_op), .f_base(f_base), .f_rows(f_rows),
      .acc_mode(acc_mode), .acc_base(acc_base),
      .f_busy(f_busy), .f_done(f_done), .f_dropped(f_dropped),
      .rd_req_valid(rd_req_valid), .rd_req_ready(rd_req_ready), .rd_req_addr(rd_req_addr),
      .rd_resp_valid(rd_resp_valid), .rd_resp_ready(rd_resp_ready),
      .rd_resp_data(rd_resp_data),
      .wr_req_valid(wr_req_valid), .wr_req_ready(wr_req_ready), .wr_req_addr(wr_req_addr),
      .wr_req_data(wr_req_data)
  );

  // The controller only starts a unit when it is idle, so the "start while busy"
  // flags can never fire; they are kept unconnected on purpose.
  /* verilator lint_off UNUSEDSIGNAL */
  logic unused_dropped;
  assign unused_dropped = dma_dropped ^ f_dropped;
  /* verilator lint_on UNUSEDSIGNAL */

endmodule

`default_nettype wire
