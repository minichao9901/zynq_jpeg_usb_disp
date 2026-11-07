`timescale 1ns / 1ps
// Single-scan, 8-bit baseline JPEG front end. Bytes are consumed only on
// valid/ready; a marker stops refill until the decoder reaches its boundary.
module jpeg_entropy (
    input clk, input reset,
    input [7:0] byte_data, input byte_valid, input byte_last, output byte_ready,
    input [9:0] width, input [8:0] height,
    output reg h2, output reg v2, output reg gray,
    output reg done, output reg error,
    input [1:0] tile_free, output reserve, output reg bank,
    output [9:0] tile_x, output [8:0] tile_y,
    input idct_ready, output coeff_valid, output [15:0] coeff,
    output [5:0] coeff_index, output block_end, output [31:0] block_tag
);
    localparam SOI_FF=0, SOI=1, MARK_FF=2, MARK=3, LEN_HI=4, LEN_LO=5,
        SKIP=6, SOF=7, SOS=8, QT_SEL=9, QT_DATA=10, HT_SEL=11, HT_COUNT=12,
        HT_DATA=13, DRI=14, TILE=15, BLOCK=16, LOOK=17, SYMBOL=18, VALUE=19,
        COEFF=20, EOB=21, BOUNDARY=22, HALT=23;
    reg [4:0] state;
    reg [7:0] marker;
    reg [15:0] seg;
    reg [7:0] idx;
    reg sof_seen, dri_seen;
    reg [7:0] gray_id;
    reg [1:0] qsel [0:2];
    reg [1:0] qt_id;
    reg [3:0] qt_defined, ht_defined;
    reg [1:0] ht_id;
    reg [2:0] dc_table, ac_table;
    reg [15:0] restart_interval, restart_left;
    reg [2:0] restart_seq;
    reg expect_eoi;

    // Each code length stores a disjoint canonical range plus the address
    // bias into that table's 256-byte symbol RAM. Compare lengths in parallel.
    reg [15:0] first_code [0:63], limit_code [0:63];
    reg [7:0] code_bias [0:63];
    reg [7:0] symbols [0:1023], quant [0:255];
    reg [16:0] build_code;
    reg [8:0] build_count, symbols_left;
    wire [16:0] build_next = build_code + {9'b0,byte_data};
    wire [16:0] build_bound = 17'd1 << (idx[3:0]+5'd1);
    wire [8:0] count_next = build_count + {1'b0,byte_data};

    reg [9:0] mcu_x;
    reg [8:0] mcu_y;
    reg [2:0] block_no;
    reg [6:0] zig;
    wire [2:0] yblocks = v2 ? 3'd4 : h2 ? 3'd2 : 3'd1;
    wire last_block = gray || block_no == yblocks+3'd1;
    wire [1:0] comp = block_no < yblocks ? 2'd0 : block_no == yblocks ? 2'd1 : 2'd2;
    wire [10:0] next_x = {1'b0,mcu_x} + (h2 ? 11'd16 : 11'd8);
    wire [9:0] next_y = {1'b0,mcu_y} + (v2 ? 10'd16 : 10'd8);
    wire end_row = next_x >= {1'b0,width};
    wire end_image = end_row && next_y >= {1'b0,height};
    assign tile_x = mcu_x;
    assign tile_y = mcu_y;
    assign reserve = state == TILE && tile_free[bank];

    reg [39:0] bits;
    reg [5:0] bit_count;
    reg ff_pending, marker_pending;
    reg [7:0] scan_marker;
    reg scan_marker_last, source_end;
    wire scan = state >= TILE && state <= BOUNDARY;
    assign byte_ready = (state < TILE) ||
        (scan && !marker_pending && bit_count <= 6'd32 && !source_end);
    wire byte_take = byte_valid && byte_ready;
    wire append_byte = scan && byte_take && (ff_pending ? byte_data == 0 : byte_data != 8'hff);
    wire [39:0] appended = bits | ({byte_data | {8{ff_pending}},32'b0} >> bit_count);

    wire [1:0] lookup_table = zig == 0 ? {1'b0,dc_table[comp]} : {1'b1,ac_table[comp]};
    wire [15:0] match_len;
    genvar k;
    generate for (k=0;k<16;k=k+1) begin: widths
        wire [15:0] prefix = bits[39:24] >> (15-k);
        localparam [3:0] K = k;
        assign match_len[k] = prefix >= first_code[{lookup_table,K}] &&
            prefix < limit_code[{lookup_table,K}];
    end endgenerate
    reg [4:0] chosen;
    integer i;
    always @* begin
        chosen = 0;
        for (integer n=0;n<16;n=n+1)
            if (match_len[n]) chosen = chosen | (n+1);
    end
    reg [4:0] huff_len;
    reg [7:0] sym;
    wire [3:0] huff_idx = huff_len[3:0]-1'b1;
    wire [15:0] code = bits[39:24] >> (5'd16-huff_len);
    wire [7:0] symbol_addr = code[7:0] + code_bias[{lookup_table,huff_idx}];
    wire [3:0] size = sym[3:0];
    wire [6:0] run_index = zig + {3'b0,sym[7:4]};
    wire [8:0] zig_address = {1'b0,run_index[5:0],2'b0} + {2'b0,run_index[5:0],1'b0};
    wire [5:0] used_bits = {1'b0,huff_len} + {2'b0,size};
    wire [31:0] sample_bits = bits[39:8] << huff_len;
    wire [11:0] magnitude = sample_bits >> (6'd32-{2'b0,size});
    wire [11:0] sign_bit = 12'd1 << (size-1'b1);
    wire signed [12:0] delta = size == 0 ? 13'sd0 : (|(magnitude & sign_bit)) ?
        $signed({1'b0,magnitude}) : $signed({1'b0,magnitude}) + 13'sd1 - $signed(13'd1 << size);
    reg signed [11:0] dc_pred [0:2];
    wire signed [12:0] dc_new = $signed(dc_pred[comp]) + delta;
    wire do_value = state == VALUE && bit_count >= used_bits;
    wire valid_pad = bit_count <= 7 &&
        ((bits[39:32] | (8'hff >> bit_count)) == 8'hff);
    reg signed [12:0] coeff_raw;
    reg [7:0] qvalue;
    reg [5:0] natural_index;
    reg [6:0] next_zig;
    wire signed [21:0] dequantized = coeff_raw * $signed({1'b0,qvalue});
    wire product_ok = dequantized >= -22'sd4096 && dequantized <= 22'sd4095;

    assign coeff_valid = state == COEFF && product_ok;
    assign coeff = dequantized[15:0];
    assign coeff_index = natural_index;
    assign block_end = state == EOB;
    assign block_tag = {8'b0,last_block,bank,mcu_y,mcu_x,block_no};

    // JPEG zig-zag position to IDCT row-major index.
    localparam [383:0] ZIGZAG = {
        6'd63,6'd62,6'd55,6'd47,6'd54,6'd61,6'd60,6'd53,
        6'd46,6'd39,6'd31,6'd38,6'd45,6'd52,6'd59,6'd58,
        6'd51,6'd44,6'd37,6'd30,6'd23,6'd15,6'd22,6'd29,
        6'd36,6'd43,6'd50,6'd57,6'd56,6'd49,6'd42,6'd35,
        6'd28,6'd21,6'd14,6'd7,6'd6,6'd13,6'd20,6'd27,
        6'd34,6'd41,6'd48,6'd40,6'd33,6'd26,6'd19,6'd12,
        6'd5,6'd4,6'd11,6'd18,6'd25,6'd32,6'd24,6'd17,
        6'd10,6'd3,6'd2,6'd9,6'd16,6'd8,6'd1,6'd0
    };

    task reject;
    begin
        error <= 1;
        state <= HALT;
    end
    endtask

    always @(posedge clk) begin
        if (reset) begin
            state <= SOI_FF;
            marker <= 0; seg <= 0; idx <= 0;
            sof_seen <= 0; dri_seen <= 0; gray_id <= 0;
            qt_defined <= 0; ht_defined <= 0; qt_id <= 0; ht_id <= 0;
            dc_table <= 0; ac_table <= 0;
            h2 <= 0; v2 <= 0; gray <= 0; done <= 0; error <= 0;
            restart_interval <= 0; restart_left <= 0; restart_seq <= 0; expect_eoi <= 0;
            mcu_x <= 0; mcu_y <= 0; bank <= 0; block_no <= 0; zig <= 0;
            bits <= 0; bit_count <= 0; ff_pending <= 0; marker_pending <= 0;
            scan_marker <= 0; scan_marker_last <= 0; source_end <= 0;
            for (i=0;i<3;i=i+1) begin
                dc_pred[i] <= 0;
                qsel[i] <= 0;
            end
        end else begin
            if (byte_take && byte_last) source_end <= 1;
            if (scan) begin
                if (append_byte || do_value) begin
                    bits <= (append_byte ? appended : bits) << (do_value ? used_bits : 6'd0);
                    bit_count <= bit_count + (append_byte ? 6'd8 : 6'd0) -
                        (do_value ? used_bits : 6'd0);
                end
                if (byte_take) begin
                    if (ff_pending && byte_data != 0 && byte_data != 8'hff) begin
                        marker_pending <= 1;
                        scan_marker <= byte_data;
                        scan_marker_last <= byte_last;
                    end
                    ff_pending <= byte_data == 8'hff;
                end
            end

            if (byte_take && state < TILE) begin
                if (seg != 0) seg <= seg-1'b1;
                case (state)
                    SOI_FF: if (byte_data == 8'hff) state <= SOI; else reject;
                    SOI: if (byte_data == 8'hd8) state <= MARK_FF; else reject;
                    MARK_FF: if (byte_data == 8'hff) state <= MARK; else reject;
                    MARK: if (byte_data != 8'hff) begin
                        marker <= byte_data;
                        state <= LEN_HI;
                        if (byte_data != 8'hc0 && byte_data != 8'hc4 && byte_data != 8'hdb &&
                            byte_data != 8'hda && byte_data != 8'hdd && byte_data != 8'hfe &&
                            byte_data[7:4] != 4'he) reject;
                    end
                    LEN_HI: begin seg <= {byte_data,8'b0}; state <= LEN_LO; end
                    LEN_LO: begin
                        seg <= {seg[15:8],byte_data}-16'd2;
                        idx <= 0;
                        case (marker)
                            8'hc0: begin
                                state <= SOF;
                                gray <= byte_data == 11;
                                if (sof_seen || seg[15:8] != 0 ||
                                    (byte_data != 11 && byte_data != 17)) reject;
                            end
                            8'hda: begin
                                state <= SOS;
                                if (!sof_seen || {seg[15:8],byte_data} != (gray ? 16'd8 : 16'd12)) reject;
                            end
                            8'hdb: state <= QT_SEL;
                            8'hc4: state <= HT_SEL;
                            8'hdd: begin
                                state <= DRI;
                                if (dri_seen || {seg[15:8],byte_data} != 4) reject;
                            end
                            default: state <= {seg[15:8],byte_data} == 2 ? MARK_FF : SKIP;
                        endcase
                        if ({seg[15:8],byte_data} < 2) reject;
                    end
                    SKIP: if (seg == 1) state <= MARK_FF;
                    SOF: begin
                        idx <= idx+1'b1;
                        case (idx)
                            0: if (byte_data != 8) reject;
                            1: if (byte_data != {7'b0,height[8]}) reject;
                            2: if (byte_data != height[7:0]) reject;
                            3: if (byte_data != {6'b0,width[9:8]}) reject;
                            4: if (byte_data != width[7:0]) reject;
                            5: if (byte_data != (gray ? 8'd1 : 8'd3)) reject;
                            6: begin gray_id <= byte_data; if (!gray && byte_data != 1) reject; end
                            7: begin
                                h2 <= byte_data[5]; v2 <= byte_data[1];
                                if ((gray && byte_data != 8'h11) ||
                                    (byte_data != 8'h11 && byte_data != 8'h21 && byte_data != 8'h22)) reject;
                            end
                            8,11,14: begin
                                qsel[idx == 8 ? 0 : idx == 11 ? 1 : 2] <= byte_data[1:0];
                                if (seg == 1) begin sof_seen <= 1; state <= MARK_FF; end
                                if (byte_data > 3) reject;
                            end
                            9: if (byte_data != 2) reject;
                            12: if (byte_data != 3) reject;
                            10,13: if (byte_data != 8'h11) reject;
                            default: reject;
                        endcase
                    end
                    QT_SEL: begin
                        qt_id <= byte_data[1:0]; idx <= 0; state <= QT_DATA;
                        if (byte_data > 3 || seg < 65) reject;
                    end
                    QT_DATA: begin
                        idx <= idx+1'b1;
                        if (idx == 63) begin
                            qt_defined[qt_id] <= 1;
                            state <= seg == 1 ? MARK_FF : QT_SEL;
                        end
                        if (byte_data == 0) reject;
                    end
                    HT_SEL: begin
                        ht_id <= {byte_data[4],byte_data[0]};
                        build_code <= 0; build_count <= 0; idx <= 0; state <= HT_COUNT;
                        if ((byte_data & 8'hee) != 0 || seg < 18) reject;
                    end
                    HT_COUNT: begin
                        first_code[{ht_id,idx[3:0]}] <= build_code[15:0];
                        limit_code[{ht_id,idx[3:0]}] <= build_next[15:0];
                        code_bias[{ht_id,idx[3:0]}] <= build_count[7:0]-build_code[7:0];
                        build_count <= count_next;
                        build_code <= build_next << 1;
                        idx <= idx+1'b1;
                        if (idx == 15) begin
                            state <= HT_DATA;
                            idx <= 0;
                            symbols_left <= count_next;
                            if (count_next == 0 || count_next >= seg) reject;
                        end
                        if (build_next >= build_bound || count_next > (ht_id[1] ? 9'd162 : 9'd12))
                            reject;
                    end
                    HT_DATA: begin
                        idx <= idx+1'b1;
                        symbols_left <= symbols_left-1'b1;
                        if (symbols_left == 1) begin
                            ht_defined[ht_id] <= 1;
                            state <= seg == 1 ? MARK_FF : HT_SEL;
                        end
                        if (ht_id[1] ? ((byte_data[3:0] == 0 && byte_data != 0 && byte_data != 8'hf0) ||
                            byte_data[3:0] > 10) : byte_data > 11) reject;
                    end
                    DRI: begin
                        restart_interval <= {restart_interval[7:0],byte_data};
                        if (seg == 1) begin dri_seen <= 1; state <= MARK_FF; end
                    end
                    SOS: begin
                        idx <= idx+1'b1;
                        if (seg == 3 && byte_data != 0) reject;
                        else if (seg == 2 && byte_data != 63) reject;
                        else if (seg == 1) begin
                            state <= TILE;
                            restart_left <= restart_interval;
                            if (byte_data != 0) reject;
                        end else if (seg > 3) case (idx)
                            0: if (byte_data != (gray ? 8'd1 : 8'd3)) reject;
                            1: if (byte_data != (gray ? gray_id : 8'd1)) reject;
                            3: if (byte_data != 2) reject;
                            5: if (byte_data != 3) reject;
                            2,4,6: begin
                                dc_table[(idx-2)>>1] <= byte_data[4];
                                ac_table[(idx-2)>>1] <= byte_data[0];
                                if ((byte_data & 8'hee) != 0 || !ht_defined[{1'b0,byte_data[4]}] ||
                                    !ht_defined[{1'b1,byte_data[0]}] || !qt_defined[qsel[(idx-2)>>1]]) reject;
                            end
                            default: reject;
                        endcase
                    end
                    default: reject;
                endcase
                if (byte_last) reject;
            end

            case (state)
                TILE: if (reserve) state <= BLOCK;
                BLOCK: if (idct_ready) begin zig <= 0; state <= LOOK; end
                LOOK: if (bit_count >= 27 || marker_pending || source_end) begin
                    huff_len <= chosen;
                    state <= SYMBOL;
                    if (chosen == 0 || bit_count < chosen) reject;
                end
                SYMBOL: state <= VALUE;
                VALUE: if (do_value) begin
                    if (zig == 0) begin
                        dc_pred[comp] <= dc_new[11:0];
                        coeff_raw <= dc_new;
                        natural_index <= 0; next_zig <= 1;
                        state <= COEFF;
                        if (dc_new < -13'sd1024 || dc_new > 13'sd1023) reject;
                    end else if (sym == 0) state <= EOB;
                    else if (sym == 8'hf0) begin
                        zig <= run_index+1'b1;
                        state <= run_index == 63 ? EOB : LOOK;
                        if (run_index > 63) reject;
                    end else begin
                        coeff_raw <= delta;
                        natural_index <= ZIGZAG[zig_address +: 6];
                        next_zig <= run_index+1'b1;
                        state <= COEFF;
                        if (run_index > 63) reject;
                    end
                end else if (marker_pending || source_end) reject;
                COEFF: begin
                    zig <= next_zig;
                    state <= next_zig == 64 ? EOB : LOOK;
                    if (!product_ok) reject;
                end
                EOB: if (last_block) begin
                    block_no <= 0; bank <= !bank;
                    if (end_row) begin mcu_x <= 0; mcu_y <= next_y[8:0]; end
                    else mcu_x <= next_x[9:0];
                    if (restart_interval != 0) restart_left <= restart_left-1'b1;
                    expect_eoi <= end_image;
                    state <= end_image || (restart_interval != 0 && restart_left == 1) ? BOUNDARY : TILE;
                end else begin
                    block_no <= block_no+1'b1;
                    state <= BLOCK;
                end
                BOUNDARY: if (marker_pending) begin
                    if (!valid_pad) reject;
                    else if (expect_eoi) begin
                        if (scan_marker == 8'hd9 && scan_marker_last) begin done <= 1; state <= HALT; end
                        else reject;
                    end else if (scan_marker == {5'b11010,restart_seq} && !scan_marker_last) begin
                        bits <= 0; bit_count <= 0; marker_pending <= 0;
                        restart_left <= restart_interval; restart_seq <= restart_seq+1'b1;
                        for (i=0;i<3;i=i+1) dc_pred[i] <= 0;
                        state <= TILE;
                    end else reject;
                end else if (bit_count > 7 || source_end) reject;
                default: ;
            endcase
        end
    end

    always @(posedge clk) begin
        if (byte_take && state == QT_DATA)
            quant[{qt_id,idx[5:0]}] <= byte_data;
        if (byte_take && state == HT_DATA)
            symbols[{ht_id,idx}] <= byte_data;
        if (state == SYMBOL)
            sym <= symbols[{lookup_table,symbol_addr}];
        if (do_value)
            qvalue <= quant[{qsel[comp],zig == 0 ? 6'b0 : run_index[5:0]}];
    end
endmodule
