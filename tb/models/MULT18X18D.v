// Behavioural model of the Lattice ECP5 MULT18X18D for simulation only (M11b).
//
// Covers exactly the configuration sa_pe uses under `SA_ECP5_DSP`:
//   SIGNEDA = SIGNEDB = 1, inputs unregistered, output register on CLK0 with
//   CE0 enable and synchronous reset RST0 (RESETMODE "SYNC"), P = A * B (36 bits).
// Other parameter values are not modelled; the RTL never uses them. This model is
// written from the primitive's documented behaviour (Lattice TN1267), not taken
// from the vendor, so it is a recorded verification assumption (docs/DECISIONS.md D-027).
`default_nettype none
module MULT18X18D #(
    parameter REG_OUTPUT_CLK = "CLK0",
    parameter REG_OUTPUT_CE  = "CE0",
    parameter REG_OUTPUT_RST = "RST0",
    parameter RESETMODE      = "SYNC"
) (
    input  wire A17,
    input  wire A16,
    input  wire A15,
    input  wire A14,
    input  wire A13,
    input  wire A12,
    input  wire A11,
    input  wire A10,
    input  wire A9,
    input  wire A8,
    input  wire A7,
    input  wire A6,
    input  wire A5,
    input  wire A4,
    input  wire A3,
    input  wire A2,
    input  wire A1,
    input  wire A0,
    input  wire B17,
    input  wire B16,
    input  wire B15,
    input  wire B14,
    input  wire B13,
    input  wire B12,
    input  wire B11,
    input  wire B10,
    input  wire B9,
    input  wire B8,
    input  wire B7,
    input  wire B6,
    input  wire B5,
    input  wire B4,
    input  wire B3,
    input  wire B2,
    input  wire B1,
    input  wire B0,
    input  wire SIGNEDA,
    input  wire SIGNEDB,
    input  wire CLK0,
    input  wire CE0,
    input  wire RST0,
    output wire P35,
    output wire P34,
    output wire P33,
    output wire P32,
    output wire P31,
    output wire P30,
    output wire P29,
    output wire P28,
    output wire P27,
    output wire P26,
    output wire P25,
    output wire P24,
    output wire P23,
    output wire P22,
    output wire P21,
    output wire P20,
    output wire P19,
    output wire P18,
    output wire P17,
    output wire P16,
    output wire P15,
    output wire P14,
    output wire P13,
    output wire P12,
    output wire P11,
    output wire P10,
    output wire P9,
    output wire P8,
    output wire P7,
    output wire P6,
    output wire P5,
    output wire P4,
    output wire P3,
    output wire P2,
    output wire P1,
    output wire P0
);
  wire signed [17:0] a = {A17, A16, A15, A14, A13, A12, A11, A10, A9, A8, A7, A6, A5, A4, A3, A2, A1, A0};
  wire signed [17:0] b = {B17, B16, B15, B14, B13, B12, B11, B10, B9, B8, B7, B6, B5, B4, B3, B2, B1, B0};
  reg  signed [35:0] p_q;
  always @(posedge CLK0) begin
    if (RST0) p_q <= 36'sd0;
    else if (CE0) p_q <= a * b;
  end
  assign {P35, P34, P33, P32, P31, P30, P29, P28, P27, P26, P25, P24, P23, P22, P21, P20, P19, P18, P17, P16, P15, P14, P13, P12, P11, P10, P9, P8, P7, P6, P5, P4, P3, P2, P1, P0} = p_q;
  wire unused_ok = SIGNEDA & SIGNEDB;
endmodule
`default_nettype wire
