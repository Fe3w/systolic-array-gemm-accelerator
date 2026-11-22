// sa_ctrl: command controller for sa_core (docs/spec/ctrl.md §2-§4).
//
// M13: an in-order dispatcher with two units that run concurrently, the DMA
// (LOAD_A, STORE, the transfer part of LOAD_W) and the feeder (COMPUTE, the array
// load part of LOAD_W). Each command waits only for the unit it needs and for
// its real dependencies on the command in flight on the other unit:
//
//   IDLE --accept--> CHECK --> DECIDE --error--> IDLE
//                                    --ok-----> ISSUE --start--> IDLE
//                                                     (LOAD_W: --DMA start--> FEED_W --feeder start--> IDLE)
//
//   LOAD_A  : DMA free; not while a COMPUTE that reads overlapping input rows streams (WAR)
//   STORE   : DMA free; no COMPUTE in flight; store gate (last COMPUTE done + 2S + 3, M11b)
//   LOAD_W  : DMA free; not while the previous LOAD_W still reads the weight buffer;
//             then feeder free, its own DMA done, reload gate (last COMPUTE done + 2S - 5)
//   COMPUTE : feeder free; not while a LOAD_A writes overlapping input rows (RAW),
//             not while a STORE reads the accumulator (shared read port, WAR)
// The accumulator tags its rows (sa_core, M13), so COMPUTE after COMPUTE needs no gap.
// Errors (spec §1): sticky err + first err_code since err_clear; the command is
// dropped and the controller returns to IDLE.
`default_nettype none

module sa_ctrl #(
    parameter  int S      = 8,
    localparam int CNT_W  = 48   // counters: 2^48 cycles is ~38 days at 85 MHz (M11b)
) (
    input  wire logic             clk,
    input  wire logic             rst,
    // command port
    input  wire logic             cmd_valid,
    output logic                  cmd_ready,
    input  wire sa_pkg::cmd_t             cmd,
    // status
    input  wire logic             err_clear,
    output logic                  err,
    output logic      [      2:0] err_code,
    output logic                  busy,
    // performance counters (spec §4)
    output logic      [CNT_W-1:0] cycles_total,
    output logic      [CNT_W-1:0] cycles_dma,
    output logic      [CNT_W-1:0] cycles_compute,
    output logic      [CNT_W-1:0] macs_issued,
    // sa_core DMA command
    output logic                  dma_start,
    output logic                  dma_dir,
    output logic                  dma_target,
    output logic      [ sa_pkg::MA_W-1:0] dma_mem_addr,
    output logic      [ sa_pkg::MA_W-1:0] dma_mem_stride,
    output logic      [   sa_pkg::BA_W:0] dma_rows,
    output logic      [ sa_pkg::BA_W-1:0] dma_buf_addr,
    input  wire logic             dma_busy,
    input  wire logic             dma_done,
    // sa_core feeder command + accumulator config
    output logic                  f_start,
    output logic                  f_op,
    output logic      [ sa_pkg::BA_W-1:0] f_base,
    output logic      [   sa_pkg::BA_W:0] f_rows,
    output logic                  acc_mode,
    output logic      [ sa_pkg::BA_W-1:0] acc_base,
    input  wire logic             f_busy,
    input  wire logic             f_done
);


  // Sequencing gaps (docs/spec/acc.md §2, M7b constants).
  localparam int RELOAD_GAP = (2 * S - 5 > 0) ? 2 * S - 5 : 0;
  localparam int STORE_GAP = 2 * S + 3;  // last accumulator write at done + 2S + 2 (M11b)
  localparam logic DMA_LOAD = 1'b0, DMA_STORE = 1'b1;
  localparam logic TGT_WBUF = 1'b0, TGT_IBUF = 1'b1;
  localparam logic F_LOAD_W = 1'b0, F_STREAM = 1'b1;

  // M11c (D-028): CHECK registers the error code, DECIDE acts on it, so the
  // 256-bit written-row check no longer feeds the state and error registers in
  // the same cycle. Cost: one cycle per command.
  typedef enum logic [2:0] {
    IDLE,
    CHECK,
    DECIDE,
    ISSUE,
    FEED_W
  } state_t;

  // What is running on each unit (M13).
  localparam logic [1:0] K_LOAD_W = 2'd0, K_LOAD_A = 2'd1, K_STORE = 2'd2;

  state_t           state_q;
  sa_pkg::cmd_t             cmd_q;
  // In-flight bookkeeping (set by the unit's start, cleared by its done).
  logic             dma_act_q, f_act_q;
  logic [      1:0] dma_kind_q;   // K_*
  logic             f_comp_q;     // the feeder runs a COMPUTE (else a LOAD_W)
  logic [sa_pkg::BA_W-1:0] dma_lo_q, f_lo_q;  // first input-buffer row
  logic [      9:0] dma_hi_q, f_hi_q;          // first + rows
  logic             have_w_q;     // a LOAD_W has completed since reset
  logic             err_q;
  logic [      2:0] err_code_q;
  logic [CNT_W-1:0] now_q;        // free-running cycle counter
  // Gates after a COMPUTE's done d: open from cycle d + GAP. Down-counters loaded
  // with GAP - 1 at d (open when 0) replace M8's 48-bit "now >= d + GAP" compares,
  // which limited sa_top's Fmax once they fed the dispatcher (M13).
  localparam int GW = $clog2(STORE_GAP + 1);
  localparam int RELOAD_LD = (RELOAD_GAP > 0) ? RELOAD_GAP - 1 : 0;
  localparam int STORE_LD  = STORE_GAP - 1;
  logic [GW-1:0]    reload_cnt_q, store_cnt_q;
  logic [CNT_W-1:0] first_q, last_store_q, cyc_dma_q, cyc_comp_q, macs_q;
  logic             first_seen_q, store_seen_q;

  logic       accept;
  logic [2:0] check_code;  // error code for cmd_q (0 = none)
  logic [2:0] check_code_q;  // ... registered in CHECK, used in DECIDE
  // buf_addr + rows, acc_addr + rows (up to 255 + 511), registered at accept so the
  // adders are off the dispatch path (M11c timing, D-028).
  logic [9:0] buf_end, acc_end;
  logic       is_load_w, is_load_a, is_compute, is_store;
  // Rows written since reset (M11b): input-buffer rows by LOAD_A, accumulator
  // rows by COMPUTE. A command that reads a row never written is error 5.
  logic [sa_pkg::DEPTH-1:0] ibuf_wr_q, acc_wr_q;
  // Row masks [addr, addr + rows) of the command, computed from the incoming cmd at
  // accept and registered, so CHECK only needs an AND-reduce (timing, M11b).
  logic [sa_pkg::DEPTH-1:0] buf_mask_d, acc_mask_d, buf_mask, acc_mask;
  logic [9:0] in_buf_end, in_acc_end;
  logic [CNT_W-1:0] macs_inc_q;  // S^2 * rows of the latched command
  logic             upd_ibuf_q, upd_acc_q;  // apply the bitmap update one cycle after DECIDE
  logic             reads_unwritten;
  logic             dma_free, f_free, ov_dma, ov_f;
  logic             dma_ok, comp_ok, feed_w_ok;

  assign cmd_ready = (state_q == IDLE);
  assign accept    = cmd_valid && cmd_ready;
  assign busy      = (state_q != IDLE) || dma_act_q || f_act_q;

  assign is_load_w  = (cmd_q.op == sa_pkg::OP_LOAD_W);
  assign is_load_a  = (cmd_q.op == sa_pkg::OP_LOAD_A);
  assign is_compute = (cmd_q.op == sa_pkg::OP_COMPUTE);
  assign is_store   = (cmd_q.op == sa_pkg::OP_STORE);

  // ---------------- error check (CHECK state), lowest code wins ----------------
  always_comb begin
    if (!(is_load_w || is_load_a || is_compute || is_store)) begin
      check_code = sa_pkg::ERR_OPCODE;
    end else if ((!is_load_w && (cmd_q.rows == '0 || 32'(cmd_q.rows) > sa_pkg::DEPTH)) ||
                 (is_load_w && 32'(cmd_q.rows) > S)) begin
      check_code = sa_pkg::ERR_ROWS;
    end else if (!is_load_w && (32'(buf_end) > sa_pkg::DEPTH || (is_compute && 32'(acc_end) > sa_pkg::DEPTH))) begin
      check_code = sa_pkg::ERR_RANGE;
    end else if (is_compute && !have_w_q) begin
      check_code = sa_pkg::ERR_NO_WEIGHTS;
    end else if (reads_unwritten) begin
      check_code = sa_pkg::ERR_UNWRITTEN;
    end else begin
      check_code = sa_pkg::ERR_NONE;
    end
  end

  assign in_buf_end = 10'(cmd.buf_addr) + 10'(cmd.rows);
  assign in_acc_end = 10'(cmd.acc_addr) + 10'(cmd.rows);
  always_comb begin
    for (int i = 0; i < sa_pkg::DEPTH; i++) begin
      buf_mask_d[i] = (i >= int'(cmd.buf_addr)) && (i < int'(in_buf_end));
      acc_mask_d[i] = (i >= int'(cmd.acc_addr)) && (i < int'(in_acc_end));
    end
  end

  always_comb begin
    reads_unwritten =
        (is_compute && ((buf_mask & ~ibuf_wr_q) != '0)) ||
        (is_compute && (cmd_q.acc_mode == 1'b1) && ((acc_mask & ~acc_wr_q) != '0)) ||
        (is_store && ((buf_mask & ~acc_wr_q) != '0));
  end

  // ---------------- dispatch conditions (M13) ----------------
  assign dma_free = !dma_act_q && !dma_busy;
  assign f_free   = !f_act_q && !f_busy;
  // [buf_addr, buf_end) of the command overlaps the in-flight unit's rows
  assign ov_dma = (10'(cmd_q.buf_addr) < dma_hi_q) && (10'(dma_lo_q) < buf_end);
  assign ov_f   = (10'(cmd_q.buf_addr) < f_hi_q) && (10'(f_lo_q) < buf_end);

  always_comb begin
    dma_ok = 1'b0;
    if (dma_free) begin
      if (is_load_a) dma_ok = !(f_act_q && f_comp_q && ov_f);
      else if (is_store) dma_ok = !(f_act_q && f_comp_q) && (store_cnt_q == '0);
      else if (is_load_w) dma_ok = !(f_act_q && !f_comp_q);
    end
  end
  assign comp_ok   = f_free && !(dma_act_q && ((dma_kind_q == K_LOAD_A && ov_dma) ||
                                              dma_kind_q == K_STORE));
  assign feed_w_ok = f_free && !dma_act_q && (reload_cnt_q == '0);

  // ---------------- unit commands ----------------
  assign dma_start      = (state_q == ISSUE) && !is_compute && dma_ok;
  assign dma_dir        = is_store ? DMA_STORE : DMA_LOAD;
  assign dma_target     = is_load_a ? TGT_IBUF : TGT_WBUF;
  assign dma_mem_addr   = cmd_q.mem_addr;
  assign dma_mem_stride = cmd_q.mem_stride;
  // LOAD_W: rows = 0 means a full tile; 1..S-1 reads only the real rows (M11b).
  assign dma_rows       = (is_load_w && cmd_q.rows == '0) ? (sa_pkg::BA_W + 1)'(S) : cmd_q.rows;
  assign dma_buf_addr   = is_load_w ? '0 : cmd_q.buf_addr;

  assign f_start  = ((state_q == ISSUE) && is_compute && comp_ok) ||
                    ((state_q == FEED_W) && feed_w_ok);
  assign f_op     = is_compute ? F_STREAM : F_LOAD_W;
  assign f_base   = cmd_q.buf_addr;
  assign f_rows   = cmd_q.rows;
  assign acc_mode = cmd_q.acc_mode;
  assign acc_base = cmd_q.acc_addr;

  // ---------------- FSM and bookkeeping ----------------
  always_ff @(posedge clk) begin
    if (rst) begin
      state_q      <= IDLE;
      dma_act_q    <= 1'b0;
      f_act_q      <= 1'b0;
      have_w_q     <= 1'b0;
      err_q        <= 1'b0;
      err_code_q   <= sa_pkg::ERR_NONE;
      now_q        <= '0;
      reload_cnt_q <= '0;
      store_cnt_q  <= '0;
      first_seen_q <= 1'b0;
      store_seen_q <= 1'b0;
      cyc_dma_q    <= '0;
      cyc_comp_q   <= '0;
      macs_q       <= '0;
      ibuf_wr_q    <= '0;
      acc_wr_q     <= '0;
      upd_ibuf_q   <= 1'b0;
      upd_acc_q    <= 1'b0;
    end else begin
      // Bitmap updates are applied one cycle after DECIDE (registered enables keep
      // the 256-bit check off the 256-flop update path); the next command's CHECK
      // is at least two cycles later, so it always sees the updated bitmaps.
      upd_ibuf_q <= 1'b0;
      upd_acc_q  <= 1'b0;
      if (upd_ibuf_q) ibuf_wr_q <= ibuf_wr_q | buf_mask;
      if (upd_acc_q) acc_wr_q <= acc_wr_q | acc_mask;
      // macs_issued is also updated one cycle after DECIDE (M13 timing: the 48-bit add
      // sat behind the 256-bit error check); macs_inc_q is held until the next accept.
      if (upd_acc_q) macs_q <= macs_q + macs_inc_q;
      now_q      <= now_q + 1'b1;
      cyc_dma_q  <= cyc_dma_q + CNT_W'(dma_busy);
      cyc_comp_q <= cyc_comp_q + CNT_W'(f_busy);
      if (err_clear) begin
        err_q      <= 1'b0;
        err_code_q <= sa_pkg::ERR_NONE;
      end
      if (accept && !first_seen_q) begin
        first_seen_q <= 1'b1;
      end

      // Units: in flight from start to done (a start never coincides with its done:
      // every transfer has at least one row).
      if (dma_start) dma_act_q <= 1'b1;
      else if (dma_done) begin
        dma_act_q <= 1'b0;
        if (dma_kind_q == K_STORE) store_seen_q <= 1'b1;
      end
      if (reload_cnt_q != '0) reload_cnt_q <= reload_cnt_q - 1'b1;
      if (store_cnt_q != '0) store_cnt_q <= store_cnt_q - 1'b1;
      if (f_start) f_act_q <= 1'b1;
      else if (f_done) begin
        f_act_q <= 1'b0;
        if (f_comp_q) begin
          reload_cnt_q <= GW'(RELOAD_LD);
          store_cnt_q  <= GW'(STORE_LD);
        end
      end

      case (state_q)
        IDLE: if (accept) state_q <= CHECK;
        CHECK: state_q <= DECIDE;
        DECIDE: begin
          if (check_code_q != sa_pkg::ERR_NONE) begin
            err_q <= 1'b1;
            if (!err_q || err_clear) err_code_q <= check_code_q;
            state_q <= IDLE;
          end else begin
            upd_acc_q <= is_compute;
            upd_ibuf_q <= is_load_a;
            // Program order: a COMPUTE after this LOAD_W uses its weights (error 4).
            if (is_load_w) have_w_q <= 1'b1;
            state_q <= ISSUE;
          end
        end
        ISSUE: begin
          if (dma_start && is_load_w) state_q <= FEED_W;
          else if (dma_start || f_start) state_q <= IDLE;
        end
        FEED_W: if (f_start) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end

  // Datapath-like registers (not reset; qualified by the control bits above).
  always_ff @(posedge clk) begin
    if (state_q == CHECK) check_code_q <= check_code;
    if (accept) begin
      cmd_q      <= cmd;
      buf_mask   <= buf_mask_d;
      buf_end    <= in_buf_end;
      acc_end    <= in_acc_end;
      acc_mask   <= acc_mask_d;
      macs_inc_q <= CNT_W'(S * S) * CNT_W'(cmd.rows);  // one constant multiply per command
    end
    if (accept && !first_seen_q) begin
      first_q <= now_q;
    end
    if (dma_act_q && dma_done && dma_kind_q == K_STORE) begin
      last_store_q <= now_q;
    end
    if (dma_start) begin
      dma_kind_q <= is_store ? K_STORE : (is_load_a ? K_LOAD_A : K_LOAD_W);
      dma_lo_q   <= cmd_q.buf_addr;
      dma_hi_q   <= buf_end;
    end
    if (f_start) begin
      f_comp_q <= is_compute;
      f_lo_q   <= cmd_q.buf_addr;
      f_hi_q   <= buf_end;
    end
  end

  assign err            = err_q;
  assign err_code       = err_code_q;
  assign cycles_total   = store_seen_q ? (last_store_q - first_q + 1'b1) : '0;
  assign cycles_dma     = cyc_dma_q;
  assign cycles_compute = cyc_comp_q;
  assign macs_issued    = macs_q;

endmodule

`default_nettype wire
