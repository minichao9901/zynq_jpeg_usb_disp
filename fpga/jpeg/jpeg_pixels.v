`timescale 1ns / 1ps
// Two reserved MCU banks absorb the IDCT's non-stallable output. Each bank
// stays owned until its last visible sample has entered the colour pipeline.
module jpeg_pixels (
    input clk, input reset,
    input [9:0] width, input [8:0] height,
    input h2, input v2, input gray,
    input reserve, input bank, input [9:0] tile_x, input [8:0] tile_y,
    output [1:0] tile_free,
    input idct_valid, input [31:0] idct_data, input [5:0] idct_index, input [31:0] idct_tag,
    output pixel_valid, input pixel_ready,
    output [9:0] pixel_x, output [8:0] pixel_y, output [23:0] pixel_bgr,
    output idle
);
    reg [1:0] owned, full;
    reg [9:0] origin_x[0:1];
    reg [8:0] origin_y[0:1];
    reg read_bank;
    reg [3:0] lx, ly;
    wire [2:0] yblocks = v2 ? 3'd4 : h2 ? 3'd2 : 3'd1;
    wire idct_bank = idct_tag[22];
    wire [2:0] idct_block = idct_tag[2:0];
    wire signed [31:0] sample = idct_data;
    wire [7:0] sample_clipped = sample > 127 ? 8'h7f : sample < -128 ? 8'h80 : sample[7:0];
    reg signed [7:0] luma[0:511], cb[0:127], cr[0:127];
    reg signed [7:0] rd_luma, rd_cb, rd_cr;
    wire [1:0] rd_yblock = {ly[3],lx[3]};
    wire [2:0] chroma_x = h2 ? lx[3:1] : lx[2:0];
    wire [2:0] chroma_y = v2 ? ly[3:1] : ly[2:0];
    wire [9:0] x = origin_x[read_bank] + {6'b0,lx};
    wire [8:0] y = origin_y[read_bank] + {5'b0,ly};
    wire last_x = lx == (h2 ? 4'd15 : 4'd7) || x == width-1'b1;
    wire last_y = ly == (v2 ? 4'd15 : 4'd7) || y == height-1'b1;

    reg [1:0] valid;
    reg [9:0] x0,x1;
    reg [8:0] y0,y1;
    reg signed [20:0] base, r, g1, g2, b;
    wire advance = pixel_ready || !valid[1];
    wire read_pixel = advance && full[read_bank];

    always @(posedge clk) begin
        if (idct_valid) begin
            if (idct_block < yblocks)
                luma[{idct_bank,idct_block[1:0],idct_index}] <= sample_clipped;
            else if (idct_block == yblocks)
                cb[{idct_bank,idct_index}] <= sample_clipped;
            else
                cr[{idct_bank,idct_index}] <= sample_clipped;
        end
        if (read_pixel) begin
            rd_luma <= luma[{read_bank,rd_yblock,ly[2:0],lx[2:0]}];
            rd_cb <= cb[{read_bank,chroma_y,chroma_x}];
            rd_cr <= cr[{read_bank,chroma_y,chroma_x}];
        end
        if (advance) begin
            x0 <= x; x1 <= x0; y0 <= y; y1 <= y0;
            // 12 fractional bits; add 0.5 for rounding after summation.
            base <= ($signed({{13{rd_luma[7]}},rd_luma}) <<< 12) + 21'sd526336;
            r  <= gray ? 21'sd0 : rd_cr * 14'sd5743;
            g1 <= gray ? 21'sd0 : rd_cb * -13'sd1410;
            g2 <= gray ? 21'sd0 : rd_cr * -13'sd2925;
            b  <= gray ? 21'sd0 : rd_cb * 14'sd7258;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            owned <= 0; full <= 0; read_bank <= 0; lx <= 0; ly <= 0; valid <= 0;
        end else begin
            if (reserve) begin
                owned[bank] <= 1;
                origin_x[bank] <= tile_x;
                origin_y[bank] <= tile_y;
            end
            if (idct_valid && idct_index == 63 && idct_tag[23])
                full[idct_bank] <= 1;
            if (advance)
                valid <= {valid[0],read_pixel};
            if (read_pixel) begin
                lx <= last_x ? 0 : lx+1'b1;
                if (last_x) ly <= last_y ? 0 : ly+1'b1;
                if (last_x && last_y) begin
                    owned[read_bank] <= 0;
                    full[read_bank] <= 0;
                    read_bank <= !read_bank;
                end
            end
        end
    end

    function [7:0] clip;
        input signed [21:0] val;
        begin
            clip = val < 0 ? 8'd0 : val >= 22'sd1048576 ? 8'd255 : val[19:12];
        end
    endfunction
    assign pixel_bgr = {clip($signed(base)+$signed(r)),
                        clip($signed(base)+$signed(g1)+$signed(g2)),
                        clip($signed(base)+$signed(b))};
    assign pixel_x = x1;
    assign pixel_y = y1;
    assign pixel_valid = valid[1];
    assign tile_free = ~owned;
    assign idle = owned == 0 && valid == 0;
endmodule
