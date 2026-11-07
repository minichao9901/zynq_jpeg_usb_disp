`timescale 1ns / 1ps
// GP0 controls the decoder. HP1 reads JPEG bytes and writes clipped BGR888
// rows at the LCD stride. At most one burst per AXI direction is outstanding.
module jpeg_dma #(
    parameter WATCHDOG_CYCLES = 12000000
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK",
       X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXI:M_AXI, ASSOCIATED_RESET aresetn" *)
    input aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST",
       X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input aresetn,

    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE" *)
    input [15:0] s_axi_awaddr,
    input [2:0] s_axi_awprot,
    input s_axi_awvalid, output s_axi_awready,
    input [31:0] s_axi_wdata, input [3:0] s_axi_wstrb,
    input s_axi_wvalid, output s_axi_wready,
    output [1:0] s_axi_bresp, output reg s_axi_bvalid, input s_axi_bready,
    input [15:0] s_axi_araddr, input [2:0] s_axi_arprot,
    input s_axi_arvalid, output s_axi_arready,
    output reg [31:0] s_axi_rdata, output [1:0] s_axi_rresp,
    output reg s_axi_rvalid, input s_axi_rready,

    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME M_AXI, PROTOCOL AXI4, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1, MAX_BURST_LENGTH 8" *)
    output reg [31:0] m_axi_araddr,
    output [7:0] m_axi_arlen, output [2:0] m_axi_arsize,
    output [1:0] m_axi_arburst, output [3:0] m_axi_arcache,
    output [2:0] m_axi_arprot, output m_axi_arlock,
    output m_axi_arvalid, input m_axi_arready,
    input [63:0] m_axi_rdata, input [1:0] m_axi_rresp, input m_axi_rlast,
    input m_axi_rvalid, output m_axi_rready,
    output reg [31:0] m_axi_awaddr,
    output [7:0] m_axi_awlen, output [2:0] m_axi_awsize,
    output [1:0] m_axi_awburst, output [3:0] m_axi_awcache,
    output [2:0] m_axi_awprot, output m_axi_awlock,
    output m_axi_awvalid, input m_axi_awready,
    output [63:0] m_axi_wdata, output [7:0] m_axi_wstrb, output m_axi_wlast,
    output m_axi_wvalid, input m_axi_wready,
    input [1:0] m_axi_bresp, input m_axi_bvalid, output m_axi_bready
);
    localparam [7:0] ERR_DESC=1, ERR_JPEG=2, ERR_READ=3, ERR_WRITE=4,
        ERR_TIMEOUT=5, ERR_ABORT=6, ERR_COUNT=7;
    localparam [1:0] RD_IDLE=0, RD_ADDR=1, RD_DATA=2;
    localparam [2:0] WR_IDLE=0, WR_OFFSET=1, WR_ALIGN=2, WR_SPLIT=3,
        WR_ADDR=4, WR_DATA=5, WR_RESP=6;
    reg [1:0] rd_state;
    reg [2:0] wr_state;
    reg active, stopping, complete;
    reg [7:0] fault;
    reg [31:0] cycles;

    // The AXI-Lite address and data channels can arrive in either order.
    reg have_aw, have_w;
    reg [15:0] control_addr;
    reg [31:0] control_data;
    reg [3:0] control_mask;
    wire reg_write = have_aw && have_w && !s_axi_bvalid;
    wire start = reg_write && control_addr == 0 && control_mask[0] && control_data[0];
    wire abort = reg_write && control_addr == 0 && control_mask[0] && control_data[1];
    assign s_axi_awready = aresetn && !have_aw && !s_axi_bvalid;
    assign s_axi_wready = aresetn && !have_w && !s_axi_bvalid;
    assign s_axi_arready = aresetn && !s_axi_rvalid;
    assign s_axi_bresp = 0;
    assign s_axi_rresp = 0;
    reg [31:0] source, length, dest, size;
    wire [9:0] width = size[9:0];
    wire [8:0] height = size[24:16];
    wire [31:0] source_padded = (length+7) & 32'hfffffff8;
    wire desc_ok = source[5:0] == 0 && source < 32'h02000000 &&
        length >= 4 && length < 32'h00400000 && source+source_padded <= 32'h02000000 &&
        dest >= 32'h02000000 && dest < 32'h02a00000 &&
        size[31:25] == 0 && size[15:10] == 0 &&
        width != 0 && width <= 800 && height != 0 && height <= 480;
    function [31:0] write_lanes;
        input [31:0] old_value, new_value;
        input [3:0] mask;
        integer i;
        begin
            for (i=0;i<4;i=i+1)
                write_lanes[i*8 +: 8] = mask[i] ? new_value[i*8 +: 8] : old_value[i*8 +: 8];
        end
    endfunction

    always @(posedge aclk) begin
        if (!aresetn) begin
            have_aw <= 0; have_w <= 0; s_axi_bvalid <= 0; s_axi_rvalid <= 0;
            source <= 0; length <= 0; dest <= 0; size <= 0;
        end else begin
            if (s_axi_awready && s_axi_awvalid) begin
                have_aw <= 1; control_addr <= s_axi_awaddr;
            end
            if (s_axi_wready && s_axi_wvalid) begin
                have_w <= 1; control_data <= s_axi_wdata; control_mask <= s_axi_wstrb;
            end
            if (s_axi_bready) s_axi_bvalid <= 0;
            if (reg_write) begin
                have_aw <= 0; have_w <= 0; s_axi_bvalid <= 1;
                if (!active) case (control_addr)
                    16'h08: source <= write_lanes(source,control_data,control_mask);
                    16'h0c: length <= write_lanes(length,control_data,control_mask);
                    16'h10: dest <= write_lanes(dest,control_data,control_mask);
                    16'h14: size <= write_lanes(size,control_data,control_mask);
                    default: ;
                endcase
            end
            if (s_axi_rready) s_axi_rvalid <= 0;
            if (s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid <= 1;
                case (s_axi_araddr)
                    16'h00: s_axi_rdata <= 32'h4a504701; // JPG, register ABI 1
                    16'h04: s_axi_rdata <= {16'b0,fault,5'b0,|fault,complete,active};
                    16'h08: s_axi_rdata <= source;
                    16'h0c: s_axi_rdata <= length;
                    16'h10: s_axi_rdata <= dest;
                    16'h14: s_axi_rdata <= size;
                    16'h18: s_axi_rdata <= cycles;
                    16'h1c: s_axi_rdata <= {13'b0,pixels_written};
                    default: s_axi_rdata <= 0;
                endcase
            end
        end
    end

    reg [18:0] pixels_written;
    reg [18:0] expected_pixels;
    reg [19:0] words_left;
    reg [21:0] bytes_left;
    reg [3:0] rd_beats, r_remaining;
    reg [3:0] rd_ptr, wr_ptr;
    wire [3:0] fifo_used = wr_ptr-rd_ptr;
    reg [63:0] fifo[0:15];
    reg [2:0] byte_index;
    wire [63:0] fifo_head = fifo[rd_ptr];
    wire [7:0] jpeg_byte = fifo_head[byte_index*8 +: 8];
    wire byte_valid = fifo_used != 0 && bytes_left != 0 && active && !stopping;
    wire byte_ready;
    wire byte_last = bytes_left == 1;
    wire byte_take = byte_valid && byte_ready;
    wire push_word = m_axi_rvalid && m_axi_rready && !stopping;
    wire read_fault = m_axi_rvalid && m_axi_rready &&
        (m_axi_rresp != 0 || m_axi_rlast != (r_remaining == 1));
    assign m_axi_arlen = {4'b0,rd_beats}-1'b1;
    assign m_axi_arburst = 2'b01;
    assign m_axi_arsize = 3'd3;
    assign m_axi_arcache = 4'b0011;
    assign m_axi_arprot = 0;
    assign m_axi_arlock = 0;
    assign m_axi_arvalid = rd_state == RD_ADDR;
    assign m_axi_rready = rd_state == RD_DATA;

    always @(posedge aclk) begin
        if (!aresetn || !active) begin
            rd_state <= RD_IDLE;
            m_axi_araddr <= source;
            words_left <= source_padded[22:3];
            bytes_left <= length[21:0];
            rd_ptr <= 0; wr_ptr <= 0; byte_index <= 0;
        end else begin
            case (rd_state)
                RD_IDLE: if (!stopping && words_left != 0 && fifo_used <= 7) begin
                    rd_beats <= words_left >= 8 ? 4'd8 : words_left[3:0];
                    rd_state <= RD_ADDR;
                end
                RD_ADDR: if (m_axi_arready) begin
                    rd_state <= RD_DATA;
                    r_remaining <= rd_beats;
                    words_left <= words_left-{16'b0,rd_beats};
                end
                RD_DATA: if (m_axi_rvalid) begin
                    r_remaining <= r_remaining-1'b1;
                    if (m_axi_rlast) begin
                        rd_state <= RD_IDLE;
                        m_axi_araddr <= m_axi_araddr+{25'b0,rd_beats,3'b0};
                    end
                end
                default: rd_state <= RD_IDLE;
            endcase
            if (push_word) wr_ptr <= wr_ptr+1'b1;
            if (byte_take) begin
                bytes_left <= bytes_left-1'b1;
                byte_index <= byte_index+1'b1;
                if (byte_index == 7 || byte_last) rd_ptr <= rd_ptr+1'b1;
            end
        end
    end
    always @(posedge aclk)
        if (push_word) fifo[wr_ptr] <= m_axi_rdata;

    wire core_reset = !aresetn || !active || stopping;
    wire h2,v2,gray,jpeg_done,jpeg_error,reserve,bank,idct_ready,coeff_valid,block_end;
    wire [1:0] tile_free;
    wire [9:0] tile_x,pixel_x;
    wire [8:0] tile_y,pixel_y;
    wire [15:0] coeff;
    wire [5:0] coeff_index,idct_index;
    wire [31:0] block_tag,idct_tag,idct_data;
    wire idct_valid,pixel_valid,pixel_idle,pixel_ready;
    wire [23:0] pixel_bgr;
    jpeg_entropy entropy (
        .clk(aclk), .reset(core_reset), .byte_data(jpeg_byte), .byte_valid(byte_valid),
        .byte_last(byte_last), .byte_ready(byte_ready), .width(width), .height(height),
        .h2(h2), .v2(v2), .gray(gray), .done(jpeg_done), .error(jpeg_error),
        .tile_free(tile_free), .reserve(reserve), .bank(bank), .tile_x(tile_x), .tile_y(tile_y),
        .idct_ready(idct_ready), .coeff_valid(coeff_valid), .coeff(coeff),
        .coeff_index(coeff_index), .block_end(block_end), .block_tag(block_tag)
    );
    jpeg_idct idct (
        .clk_i(aclk), .rst_i(core_reset), .img_start_i(1'b0), .img_end_i(1'b0),
        .inport_valid_i(coeff_valid), .inport_data_i(coeff), .inport_idx_i(coeff_index),
        .inport_eob_i(block_end), .inport_id_i(block_tag), .outport_accept_i(1'b1),
        .inport_accept_o(idct_ready), .outport_valid_o(idct_valid), .outport_data_o(idct_data),
        .outport_idx_o(idct_index), .outport_id_o(idct_tag)
    );
    jpeg_pixels pixels (
        .clk(aclk), .reset(core_reset), .width(width), .height(height), .h2(h2), .v2(v2),
        .gray(gray), .reserve(reserve), .bank(bank), .tile_x(tile_x), .tile_y(tile_y),
        .tile_free(tile_free), .idct_valid(idct_valid), .idct_data(idct_data),
        .idct_index(idct_index), .idct_tag(idct_tag), .pixel_valid(pixel_valid),
        .pixel_ready(pixel_ready), .pixel_x(pixel_x), .pixel_y(pixel_y), .pixel_bgr(pixel_bgr),
        .idle(pixel_idle)
    );

    // Gather up to eight consecutive pixels before handing the segment to the
    // AXI writer. Byte strobes preserve neighbours at unaligned ROI boundaries.
    reg [191:0] segment_data;
    reg [23:0] segment_mask;
    reg segment_pending;
    reg [9:0] segment_x;
    reg [8:0] segment_y;
    wire pixel_take = pixel_valid && pixel_ready;
    assign pixel_ready = active && !stopping && !segment_pending;
    always @(posedge aclk) begin
        if (core_reset) begin
            segment_pending <= 0;
            segment_mask <= 0;
        end else if (pixel_take) begin
            if (pixel_x[2:0] == 0) begin
                segment_x <= pixel_x;
                segment_y <= pixel_y;
            end
            segment_data[pixel_x[2:0]*24 +: 24] <= pixel_bgr;
            segment_mask[pixel_x[2:0]*3 +: 3] <= 3'b111;
            if (pixel_x[2:0] == 7 || pixel_x == width-1'b1) segment_pending <= 1;
        end else if (wr_state == WR_ALIGN) begin
            segment_pending <= 0;
            segment_mask <= 0;
        end
    end

    reg [31:0] offset_address;
    reg [247:0] write_data;
    reg [30:0] write_mask;
    reg [2:0] wr_total, wr_beats;
    wire [2:0] wr_room = 3'd0-m_axi_awaddr[5:3];
    wire page_split = (&m_axi_awaddr[11:6]) && wr_room != 0 && wr_total > wr_room;
    wire [30:0] aligned_mask = {7'b0,segment_mask} << offset_address[2:0];
    wire write_fault = m_axi_bvalid && m_axi_bready && m_axi_bresp != 0;
    assign m_axi_awlen = {5'b0,wr_beats}-1'b1;
    assign m_axi_awburst = 2'b01;
    assign m_axi_awsize = 3'd3;
    assign m_axi_awcache = 4'b0011;
    assign m_axi_awprot = 0;
    assign m_axi_awlock = 0;
    assign m_axi_awvalid = wr_state == WR_ADDR;
    assign m_axi_wdata = write_data[63:0];
    assign m_axi_wstrb = write_mask[7:0];
    assign m_axi_wlast = wr_beats == 1;
    assign m_axi_wvalid = wr_state == WR_DATA;
    assign m_axi_bready = wr_state == WR_RESP;
    always @(posedge aclk) begin
        if (!aresetn || !active) begin
            wr_state <= WR_IDLE;
        end else case (wr_state)
            WR_IDLE: if (!stopping && segment_pending) wr_state <= WR_OFFSET;
            WR_OFFSET: begin
                offset_address <= dest+segment_y*32'd2400+segment_x*32'd3;
                wr_state <= stopping ? WR_IDLE : WR_ALIGN;
            end
            WR_ALIGN: begin
                m_axi_awaddr <= {offset_address[31:3],3'b0};
                write_data <= {56'b0,segment_data} << {offset_address[2:0],3'b0};
                write_mask <= aligned_mask;
                wr_total <= |aligned_mask[30:24] ? 4 : |aligned_mask[23:16] ? 3 :
                    |aligned_mask[15:8] ? 2 : 1;
                wr_state <= stopping ? WR_IDLE : WR_SPLIT;
            end
            WR_SPLIT: begin
                wr_beats <= page_split ? wr_room : wr_total;
                wr_state <= stopping ? WR_IDLE : WR_ADDR;
            end
            WR_ADDR: if (m_axi_awready) wr_state <= WR_DATA;
            WR_DATA: if (m_axi_wready) begin
                write_data <= write_data >> 64;
                write_mask <= write_mask >> 8;
                wr_beats <= wr_beats-1'b1;
                wr_total <= wr_total-1'b1;
                m_axi_awaddr <= m_axi_awaddr+8;
                if (m_axi_wlast) wr_state <= WR_RESP;
            end
            WR_RESP: if (m_axi_bvalid)
                wr_state <= wr_total != 0 && !stopping && !write_fault ? WR_SPLIT : WR_IDLE;
            default: wr_state <= WR_IDLE;
        endcase
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            active <= 0; stopping <= 0; complete <= 0; fault <= 0;
            cycles <= 0; pixels_written <= 0; expected_pixels <= 0;
        end else if (!active) begin
            if (start) begin
                active <= desc_ok;
                stopping <= 0; complete <= 0; fault <= desc_ok ? 0 : ERR_DESC;
                cycles <= 0; pixels_written <= 0;
                expected_pixels <= width*height;
            end
        end else if (stopping) begin
            // AXI VALID cannot be withdrawn during an abort. Drain all
            // accepted requests before allowing software to reuse memory.
            if (rd_state == RD_IDLE && wr_state == WR_IDLE) active <= 0;
        end else begin
            cycles <= cycles+1'b1;
            if (pixel_take) pixels_written <= pixels_written+1'b1;
            if (abort || jpeg_error || read_fault || write_fault || cycles == WATCHDOG_CYCLES-1) begin
                stopping <= 1;
                fault <= abort ? ERR_ABORT : jpeg_error ? ERR_JPEG : read_fault ? ERR_READ :
                    write_fault ? ERR_WRITE : ERR_TIMEOUT;
            end else if (jpeg_done && pixel_idle && !segment_pending &&
                rd_state == RD_IDLE && wr_state == WR_IDLE) begin
                active <= 0;
                complete <= pixels_written == expected_pixels;
                if (pixels_written != expected_pixels) fault <= ERR_COUNT;
            end
        end
    end
endmodule
