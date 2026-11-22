// sa_pe: weight-stationary processing element (docs/spec/pe.md).
//
// Every rising edge (two-stage MAC since M7b, D-022):
//   prod_q   <= a_valid_in ? a_in * w_q : 0                    // stage 1: multiply
//   psum_out <= psum_in + sext(prod_q)                         // stage 2: add, ACC_W wrap
//   a_out    <= a_in
//   a_valid_out <= a_valid_in                                  // cleared by rst
//   w_q      <= w_load ? w_in : w_q                            // shift chain (D-012)
// w_out = w_q feeds w_in of the PE below during weight loading.
//
// Latency: a_out / a_valid_out 1 cycle after a_in; psum_out 2 cycles after a_in
// and 1 cycle after psum_in (the PE above delivers psum_in exactly then, because
// the array skews activations by one cycle per row: docs/spec/pe.md §4.2).
// Reset (D-005a): synchronous, active-high; only a_valid is reset. a_out, prod_q
// and psum_out are qualified by valids; a stale prod_q after reset is only ever
// added to a psum that no valid row uses. w_q is written by LOAD_W before COMPUTE.
`default_nettype none

module sa_pe #(
    parameter int DATA_W = 8,   // activation and weight width (signed)
    parameter int ACC_W  = 32   // partial-sum width (signed), > 2*DATA_W
) (
    input  wire logic                     clk,
    input  wire logic                     rst,
    // weight load / shift chain
    input  wire logic                     w_load,
    input  wire logic signed [DATA_W-1:0] w_in,
    output logic signed      [DATA_W-1:0] w_out,
    // activations, moving right
    input  wire logic signed [DATA_W-1:0] a_in,
    input  wire logic                     a_valid_in,
    output logic signed      [DATA_W-1:0] a_out,
    output logic                          a_valid_out,
    // partial sums, moving down
    input  wire logic signed [ ACC_W-1:0] psum_in,
    output logic signed      [ ACC_W-1:0] psum_out
);

  localparam int PROD_W = 2 * DATA_W;  // a signed DATA_W x DATA_W product always fits

  logic signed [DATA_W-1:0] w_q;
  logic signed [DATA_W-1:0] a_q;
  logic                     a_valid_q;
  logic signed [ ACC_W-1:0] psum_q;

  logic signed [PROD_W-1:0] a_ext, w_ext;  // operands sign-extended to the product width
  logic signed [PROD_W-1:0] product;       // a_in * w_q, exact
  logic signed [PROD_W-1:0] prod_d;        // product, or 0 when the activation is invalid
  logic signed [PROD_W-1:0] prod_q;        // stage-1 register (M7b, D-022)
  logic signed [ ACC_W-1:0] prod_ext;      // prod_q sign-extended to ACC_W
  logic signed [ ACC_W-1:0] psum_d;

  always_comb begin
    // Explicit sign extension so the multiply is signed and full width on both
    // operands (no implicit width rules to remember).
    a_ext       = $signed({{(PROD_W - DATA_W) {a_in[DATA_W-1]}}, a_in});
    w_ext       = $signed({{(PROD_W - DATA_W) {w_q[DATA_W-1]}}, w_q});
    product     = a_ext * w_ext;  // low PROD_W bits; exact since |a*w| <= 2^(PROD_W-2)
    prod_d      = a_valid_in ? product : '0;  // D-011: invalid activation adds 0
    // Stage 2 (one cycle later): add the registered product to psum_in.
    prod_ext    = $signed({{(ACC_W - PROD_W) {prod_q[PROD_W-1]}}, prod_q});
    psum_d      = psum_in + prod_ext;         // wraps modulo 2^ACC_W (D-004a)
  end


  // Stage-1 register. Default: a plain register. With `SA_ECP5_DSP` (synthesis,
  // scripts/synth/ecp5.py) it is the ECP5 MULT18X18D's own output register, which
  // removes the DSP -> fabric routing from the critical path (M11b issue 9).
  // Both forms are simulated by tb/pe and tb/array (the DSP form with the
  // behavioural model tb/models/MULT18X18D.v).
`ifdef SA_ECP5_DSP
  logic [17:0] dsp_a, dsp_b;
  logic [35:0] dsp_p;
  assign dsp_a = 18'($signed(a_in));
  assign dsp_b = 18'($signed(w_q));
  // Synchronous reset clears the product when the activation is invalid (D-011).
  MULT18X18D #(
      .REG_OUTPUT_CLK("CLK0"),
      .REG_OUTPUT_CE ("CE0"),
      .REG_OUTPUT_RST("RST0"),
      .RESETMODE     ("SYNC")
  ) u_mul (
      .A0(dsp_a[0]), .A1(dsp_a[1]), .A2(dsp_a[2]), .A3(dsp_a[3]), .A4(dsp_a[4]), .A5(dsp_a[5]), .A6(dsp_a[6]), .A7(dsp_a[7]), .A8(dsp_a[8]), .A9(dsp_a[9]), .A10(dsp_a[10]), .A11(dsp_a[11]), .A12(dsp_a[12]), .A13(dsp_a[13]), .A14(dsp_a[14]), .A15(dsp_a[15]), .A16(dsp_a[16]), .A17(dsp_a[17]),
      .B0(dsp_b[0]), .B1(dsp_b[1]), .B2(dsp_b[2]), .B3(dsp_b[3]), .B4(dsp_b[4]), .B5(dsp_b[5]), .B6(dsp_b[6]), .B7(dsp_b[7]), .B8(dsp_b[8]), .B9(dsp_b[9]), .B10(dsp_b[10]), .B11(dsp_b[11]), .B12(dsp_b[12]), .B13(dsp_b[13]), .B14(dsp_b[14]), .B15(dsp_b[15]), .B16(dsp_b[16]), .B17(dsp_b[17]),
      .SIGNEDA(1'b1), .SIGNEDB(1'b1), .CLK0(clk), .CE0(1'b1), .RST0(!a_valid_in),
      .P0(dsp_p[0]), .P1(dsp_p[1]), .P2(dsp_p[2]), .P3(dsp_p[3]), .P4(dsp_p[4]), .P5(dsp_p[5]), .P6(dsp_p[6]), .P7(dsp_p[7]), .P8(dsp_p[8]), .P9(dsp_p[9]), .P10(dsp_p[10]), .P11(dsp_p[11]), .P12(dsp_p[12]), .P13(dsp_p[13]), .P14(dsp_p[14]), .P15(dsp_p[15]), .P16(dsp_p[16]), .P17(dsp_p[17]), .P18(dsp_p[18]), .P19(dsp_p[19]), .P20(dsp_p[20]), .P21(dsp_p[21]), .P22(dsp_p[22]), .P23(dsp_p[23]), .P24(dsp_p[24]), .P25(dsp_p[25]), .P26(dsp_p[26]), .P27(dsp_p[27]), .P28(dsp_p[28]), .P29(dsp_p[29]), .P30(dsp_p[30]), .P31(dsp_p[31]), .P32(dsp_p[32]), .P33(dsp_p[33]), .P34(dsp_p[34]), .P35(dsp_p[35])
  );
  assign prod_q = dsp_p[PROD_W-1:0];
  // The behavioural gated product and the upper DSP product bits (always the sign
  // extension of a 16-bit product) have no use in this form.
  /* verilator lint_off UNUSEDSIGNAL */
  logic unused_dsp;
  assign unused_dsp = ^{prod_d, dsp_p[35:PROD_W]};
  /* verilator lint_on UNUSEDSIGNAL */
`else
  always_ff @(posedge clk) begin
    prod_q <= prod_d;  // stage 1: multiply (the gate is D-011)
  end
`endif

  // Control: the only reset flop.
  always_ff @(posedge clk) begin
    if (rst) begin
      a_valid_q <= 1'b0;
    end else begin
      a_valid_q <= a_valid_in;
    end
  end

  // Datapath: not reset (D-005a).
  always_ff @(posedge clk) begin
    a_q    <= a_in;
    psum_q <= psum_d;  // stage 2: add
    if (w_load) begin
      w_q <= w_in;
    end
  end

  assign w_out       = w_q;
  assign a_out       = a_q;
  assign a_valid_out = a_valid_q;
  assign psum_out    = psum_q;

endmodule

`default_nettype wire
