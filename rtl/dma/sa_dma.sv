// sa_dma: one-descriptor-at-a-time DMA between the memory channels and the
// on-chip buffers (docs/spec/dma.md §3).
//
//   LOAD  : read request i -> address mem_addr + i*mem_stride; response i (in
//           order) is written to buffer row buf_addr + i in the cycle it arrives.
//   STORE : source row buf_addr + i (1-cycle read) is sent as BEATS = ACC_W/DATA_W
//           write beats to mem_addr + i*mem_stride + b*S. The next row is read in
//           the cycle the current row's last beat is accepted (no gap).
//
// Handshakes (docs/CONVENTIONS.md): rd_req_valid and wr_req_valid come from registers only,
// never from *_ready; their payloads change only after a handshake.
// Timing with an always-ready memory, start in cycle t:
//   LOAD  R rows, read latency L : done in t + R + L
//   STORE R rows                 : done in t + 4R + 1   (BEATS = 4)
`default_nettype none

module sa_dma #(
    parameter  int S         = 8,
    parameter  int DATA_W    = 8,
    parameter  int ACC_W     = 32,
    parameter  int IN_DEPTH  = 256,
    parameter  int ACC_DEPTH = 256,
    parameter  int MA_W      = 32,
    localparam int BUS_W     = S * DATA_W,         // one input row per beat (D-019)
    localparam int SRC_W     = S * ACC_W,          // one accumulator row
    localparam int BEATS     = ACC_W / DATA_W,     // beats per accumulator row
    localparam int BEAT_W    = (BEATS > 1) ? $clog2(BEATS) : 1,
    localparam int WA_W      = (S > 1) ? $clog2(S) : 1,
    localparam int IA_W      = (IN_DEPTH > 1) ? $clog2(IN_DEPTH) : 1,
    localparam int AA_W      = (ACC_DEPTH > 1) ? $clog2(ACC_DEPTH) : 1,
    localparam int BA_W      = (IA_W > AA_W) ? IA_W : AA_W,
    localparam int CNT_W     = BA_W + 1
) (
    input  wire logic             clk,
    input  wire logic             rst,
    // descriptor (accepted when start && !busy)
    input  wire logic             start,
    input  wire logic             dir,            // 0 = LOAD, 1 = STORE
    input  wire logic             target,         // LOAD: 0 = weight buffer, 1 = input buffer
    input  wire logic [ MA_W-1:0] mem_addr,
    input  wire logic [ MA_W-1:0] mem_stride,
    input  wire logic [CNT_W-1:0] rows,
    input  wire logic [ BA_W-1:0] buf_addr,
    output logic                  busy,
    output logic                  done,
    output logic                  start_dropped,
    // memory read channels
    output logic                  rd_req_valid,
    input  wire logic             rd_req_ready,
    output logic      [ MA_W-1:0] rd_req_addr,
    input  wire logic             rd_resp_valid,
    output logic                  rd_resp_ready,
    input  wire logic [BUS_W-1:0] rd_resp_data,
    // memory write channel
    output logic                  wr_req_valid,
    input  wire logic             wr_req_ready,
    output logic      [ MA_W-1:0] wr_req_addr,
    output logic      [BUS_W-1:0] wr_req_data,
    // buffer write ports (LOAD)
    output logic                  wb_we,
    output logic      [ WA_W-1:0] wb_waddr,
    output logic      [BUS_W-1:0] wb_wdata,
    output logic                  ib_we,
    output logic      [ IA_W-1:0] ib_waddr,
    output logic      [BUS_W-1:0] ib_wdata,
    // STORE source read port (1-cycle latency, rdata holds while re = 0)
    output logic                  src_re,
    output logic      [ AA_W-1:0] src_raddr,
    input  wire logic [SRC_W-1:0] src_rdata
);

  localparam logic DIR_LOAD = 1'b0;
  localparam logic DIR_STORE = 1'b1;
  localparam logic TGT_WBUF = 1'b0;
  localparam logic TGT_IBUF = 1'b1;

  typedef enum logic {
    IDLE,
    RUN
  } state_t;

  // Control (reset).
  state_t state_q;
  logic   row_valid_q;      // STORE: src_rdata holds a row with beats still to send
  logic   start_dropped_q;

  // Descriptor and progress (written on accept; not reset).
  logic             dir_q, target_q;
  logic [ MA_W-1:0] addr_q;       // LOAD: next request address; STORE: current row address
  logic [ MA_W-1:0] stride_q;
  logic [CNT_W-1:0] issue_left_q; // LOAD: requests to issue; STORE: rows to read from the source
  logic [CNT_W-1:0] resp_left_q;  // LOAD: responses still expected
  logic [ BA_W-1:0] ptr_q;        // LOAD: next buffer row to write; STORE: next source row
  logic [BEAT_W-1:0] beat_q;      // STORE: beat index within the current row

  logic run, loading, storing, accept;
  logic rd_hs, resp_hs, wr_hs, last_beat_hs;
  logic done_load, done_store;

  assign run     = (state_q == RUN);
  assign loading = run && (dir_q == DIR_LOAD);
  assign storing = run && (dir_q == DIR_STORE);
  assign busy    = run;
  assign accept  = start && !busy;

  // ---------------- LOAD ----------------
  assign rd_req_valid  = loading && (issue_left_q != '0);  // registers only
  assign rd_req_addr   = addr_q;
  assign rd_resp_ready = 1'b1;  // a response is always written to a buffer at once
  assign rd_hs         = rd_req_valid && rd_req_ready;
  assign resp_hs       = loading && rd_resp_valid;  // responses only exist for our requests

  assign wb_we    = resp_hs && (target_q == TGT_WBUF);
  assign ib_we    = resp_hs && (target_q == TGT_IBUF);
  assign wb_waddr = ptr_q[WA_W-1:0];
  assign ib_waddr = ptr_q[IA_W-1:0];
  assign wb_wdata = rd_resp_data;
  assign ib_wdata = rd_resp_data;

  // done: the last response arrives, or a rows = 0 LOAD has nothing to wait for.
  assign done_load = loading && ((resp_hs && (resp_left_q == CNT_W'(1))) || (resp_left_q == '0));

  // ---------------- STORE ----------------
  assign wr_req_valid = row_valid_q;  // a register
  assign wr_req_addr  = addr_q + (MA_W'(beat_q) * MA_W'(S));
  assign wr_req_data  = src_rdata[beat_q*BUS_W+:BUS_W];
  assign wr_hs        = wr_req_valid && wr_req_ready;
  assign last_beat_hs = wr_hs && (beat_q == BEAT_W'(BEATS - 1));

  // Read the next source row when no row is being sent, or in the cycle the
  // current row's last beat is accepted (its data is no longer needed after this edge).
  assign src_re    = storing && (issue_left_q != '0) && (!row_valid_q || last_beat_hs);
  assign src_raddr = ptr_q[AA_W-1:0];

  // done: the last beat of the last row is accepted, or a rows = 0 STORE.
  assign done_store = storing && ((last_beat_hs && (issue_left_q == '0)) ||
                                  ((issue_left_q == '0) && !row_valid_q));

  assign done          = done_load || done_store;
  assign start_dropped = start_dropped_q;

  // ---------------- registers ----------------
  always_ff @(posedge clk) begin
    if (rst) begin
      state_q         <= IDLE;
      row_valid_q     <= 1'b0;
      start_dropped_q <= 1'b0;
    end else begin
      start_dropped_q <= start && busy;
      case (state_q)
        IDLE:    if (accept) state_q <= RUN;
        RUN:     if (done) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
      if (src_re) begin
        row_valid_q <= 1'b1;
      end else if (last_beat_hs) begin
        row_valid_q <= 1'b0;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (accept) begin
      dir_q        <= dir;
      target_q     <= target;
      addr_q       <= mem_addr;
      stride_q     <= mem_stride;
      issue_left_q <= rows;
      resp_left_q  <= rows;
      ptr_q        <= buf_addr;
      beat_q       <= '0;
    end else begin
      // LOAD progress
      if (rd_hs) begin
        addr_q       <= addr_q + stride_q;
        issue_left_q <= issue_left_q - 1'b1;
      end
      if (resp_hs) begin
        ptr_q       <= ptr_q + 1'b1;
        resp_left_q <= resp_left_q - 1'b1;
      end
      // STORE progress
      if (src_re) begin
        ptr_q        <= ptr_q + 1'b1;
        issue_left_q <= issue_left_q - 1'b1;
      end
      if (wr_hs) begin
        beat_q <= last_beat_hs ? '0 : beat_q + 1'b1;
      end
      if (last_beat_hs) begin
        addr_q <= addr_q + stride_q;
      end
    end
  end

endmodule

`default_nettype wire
