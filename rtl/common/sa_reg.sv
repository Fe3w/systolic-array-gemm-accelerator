// sa_reg: W-bit, D-stage pipeline register with a valid bit.
//
// out_data / out_valid equal in_data / in_valid delayed by exactly D clock cycles.
// D = 0 is a plain wire. Used for PE hops, input skew lines and output de-skew.
//
// Reset (D-005): synchronous, active-high `rst` clears every valid bit. The data
// registers are NOT reset: their contents only matter when the matching valid bit
// is set, and leaving them unreset saves area and reset fan-out.
`default_nettype none

module sa_reg #(
    parameter int W = 8,  // data width in bits, >= 1
    parameter int D = 1   // number of register stages, >= 0
) (
    input  wire logic         clk,
    input  wire logic         rst,
    input  wire logic         in_valid,
    input  wire logic [W-1:0] in_data,
    output logic              out_valid,
    output logic      [W-1:0] out_data
);

  if (D == 0) begin : g_wire
    assign out_valid = in_valid;
    assign out_data  = in_data;

    // clk and rst are intentionally unused when there are no stages.
    /* verilator lint_off UNUSEDSIGNAL */
    logic unused_ok;
    assign unused_ok = clk ^ rst;
    /* verilator lint_on UNUSEDSIGNAL */
  end else begin : g_pipe
    logic [D-1:0] valid_q;          // valid_q[i] = in_valid delayed by i+1 cycles
    logic [W-1:0] data_q  [0:D-1];  // data_q[i]  = in_data  delayed by i+1 cycles

    always_ff @(posedge clk) begin
      if (rst) begin
        valid_q <= '0;
      end else begin
        valid_q[0] <= in_valid;
        for (int i = 1; i < D; i++) begin
          valid_q[i] <= valid_q[i-1];
        end
      end
    end

    always_ff @(posedge clk) begin
      data_q[0] <= in_data;
      for (int i = 1; i < D; i++) begin
        data_q[i] <= data_q[i-1];
      end
    end

    assign out_valid = valid_q[D-1];
    assign out_data  = data_q[D-1];
  end

endmodule

`default_nettype wire
