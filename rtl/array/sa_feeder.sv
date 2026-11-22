// sa_feeder: runs one LOAD_W or STREAM command, reading a buffer into sa_array
// (docs/spec/buffers.md §3-§4).
//
//   LOAD_W : read weight-buffer rows S-1 .. 0, one per cycle; each row reaches the
//            array as w_load / w_row one cycle later (1-cycle SRAM read, D-017).
//   STREAM : read input-buffer rows base .. base+rows-1; each reaches the array as
//            a_valid / a_row one cycle later.
//
// An output register (M7b, D-022) sits between the buffers and the array, so a
// row reaches the array two cycles after its buffer read; this cuts the
// BRAM clock-to-out -> PE multiply-add path measured in M7.
// Timing (start in cycle t, S = array side, M = rows):
//   LOAD_W : w_load in t+3 .. t+S+2, done in t+S+2, busy in t+1 .. t+S+2
//   STREAM : a_valid in t+3 .. t+M+2, done in t+M+2 (M = 0: done in t+1)
// The feeder does not enforce the array's reload rule (D-015): the controller does.
`default_nettype none

module sa_feeder #(
    parameter  int S        = 4,
    parameter  int IN_DEPTH = 256,
    parameter  int DATA_W   = 8,
    localparam int WA_W     = (S > 1) ? $clog2(S) : 1,
    localparam int IA_W     = (IN_DEPTH > 1) ? $clog2(IN_DEPTH) : 1,
    localparam int CNT_W    = (IA_W + 1 > $clog2(S + 1)) ? IA_W + 1 : $clog2(S + 1)
) (
    input  wire logic                     clk,
    input  wire logic                     rst,
    // command (accepted when start && !busy)
    input  wire logic                     start,
    input  wire logic                     op,             // 0 = LOAD_W, 1 = STREAM
    input  wire logic [         IA_W-1:0] base,
    input  wire logic [           IA_W:0] rows,
    output logic                          busy,
    output logic                          done,
    output logic                          start_dropped,
    // weight buffer read port
    output logic                          wb_re,
    output logic      [         WA_W-1:0] wb_raddr,
    input  wire logic [     S*DATA_W-1:0] wb_rdata,
    // input buffer read port
    output logic                          ib_re,
    output logic      [         IA_W-1:0] ib_raddr,
    input  wire logic [     S*DATA_W-1:0] ib_rdata,
    // to sa_array
    output logic                          w_load,
    output logic      [S-1:0][DATA_W-1:0] w_row,
    output logic                          a_valid,
    output logic      [S-1:0][DATA_W-1:0] a_row
);

  localparam logic OP_LOAD_W = 1'b0;
  localparam logic OP_STREAM = 1'b1;

  typedef enum logic {
    IDLE,
    RUN
  } state_t;

  // Control registers (reset).
  state_t state_q;
  logic   inflight_q;       // a buffer read issued last cycle: its data is on rdata now
  logic   last_q;           // ... and it was the command's last read
  logic   start_dropped_q;
  logic   out_valid_q;      // the output register holds an array input this cycle
  logic   out_last_q;       // ... and it is the command's last one

  // Output data register (not reset: qualified by out_valid_q).
  logic [S-1:0][DATA_W-1:0] w_row_q, a_row_q;
  // LOAD_W with rows = r in 1..S-1 (M11b): only weight rows 0..r-1 are real; rows
  // r..S-1 are presented as zero, so stale buffer contents never reach the array.
  logic [WA_W:0]            wreal_q;   // number of real weight rows of this LOAD_W
  logic                     zero_q;    // the read in flight is a padding row

  // Command registers (written on accept; not reset).
  logic             op_q;
  logic [ WA_W-1:0] waddr_q;      // next weight row to read (counts down)
  logic [ IA_W-1:0] iaddr_q;      // next input row to read (counts up)
  logic [CNT_W-1:0] remaining_q;  // reads still to issue

  logic accept;  // start accepted this cycle
  logic issue;   // a read is issued this cycle

  assign busy   = (state_q == RUN) || inflight_q || out_valid_q;
  assign accept = start && !busy;
  assign issue  = (state_q == RUN) && (remaining_q != '0);

  always_ff @(posedge clk) begin
    if (rst) begin
      state_q         <= IDLE;
      inflight_q      <= 1'b0;
      last_q          <= 1'b0;
      out_valid_q     <= 1'b0;
      out_last_q      <= 1'b0;
      start_dropped_q <= 1'b0;
    end else begin
      inflight_q      <= issue;
      last_q          <= issue && (remaining_q == CNT_W'(1));
      out_valid_q     <= inflight_q;
      out_last_q      <= inflight_q && last_q;
      start_dropped_q <= start && busy;
      case (state_q)
        IDLE: if (accept) state_q <= RUN;
        // Leave RUN after issuing the last read (or at once when rows = 0).
        RUN:  if (remaining_q <= CNT_W'(1)) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  always_ff @(posedge clk) begin
    if (accept) begin
      op_q        <= op;
      waddr_q     <= WA_W'(S - 1);
      wreal_q     <= (rows == '0 || 32'(rows) >= S) ? (WA_W + 1)'(S) : (WA_W + 1)'(rows);
      iaddr_q     <= base;
      remaining_q <= (op == OP_LOAD_W) ? CNT_W'(S) : CNT_W'(rows);
    end else if (issue) begin
      waddr_q     <= waddr_q - 1'b1;
      iaddr_q     <= iaddr_q + 1'b1;
      remaining_q <= remaining_q - 1'b1;
    end
  end

  // Buffer read ports.
  assign wb_re    = issue && (op_q == OP_LOAD_W);
  assign wb_raddr = waddr_q;
  assign ib_re    = issue && (op_q == OP_STREAM);
  assign ib_raddr = iaddr_q;

  // Output register: buffer rdata registered once more. op_q is stable until
  // busy drops, so it still qualifies the last row in the output stage.
  always_ff @(posedge clk) begin
    zero_q     <= (WA_W + 1)'(waddr_q) >= wreal_q;
    w_row_q    <= zero_q ? '0 : wb_rdata;
    a_row_q <= ib_rdata;
  end

  assign w_load  = out_valid_q && (op_q == OP_LOAD_W);
  assign a_valid = out_valid_q && (op_q == OP_STREAM);
  assign w_row   = w_row_q;
  assign a_row   = a_row_q;

  // done: the last array input is presented this cycle, or a rows = 0 command
  // reaches RUN with nothing to read.
  assign done = out_last_q || ((state_q == RUN) && (remaining_q == '0));
  assign start_dropped = start_dropped_q;

endmodule

`default_nettype wire
