`timescale 1ns / 1ps
module jpeg_dma_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg resetn=0;
    localparam SRC=32'h00100fc0, FB=32'h02000000, FB_BYTES=1152000;
    localparam SENTINEL=8'h5a;
    reg [7:0] source[0:524287], frame[0:FB_BYTES-1];
    reg [15:0] s_awaddr=0,s_araddr=0;
    reg s_awvalid=0,s_wvalid=0,s_arvalid=0;
    reg [31:0] s_wdata=0;
    wire s_awready,s_wready,s_bvalid,s_arready,s_rvalid;
    wire [31:0] s_rdata;
    wire [31:0] araddr,awaddr;
    wire [7:0] arlen,awlen,wstrb;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,awburst;
    wire arvalid,rready,awvalid,wvalid,wlast,bready;
    wire [63:0] wdata;
    reg [63:0] rdata=0;
    reg rlast=0,rvalid=0,bvalid=0;
    reg [1:0] rresp=0,bresp=0;
    reg read_live=0,write_live=0;
    integer rd_address,rd_remaining,wr_address,wr_remaining;
    integer response_due[0:15], response_head=0, response_tail=0;
    integer b_latency=0, write_window=8, peak_responses=0;
    wire response_live=response_head!=response_tail;
    integer cycle=0,src_length,width,height,x,y,expected_fault,inject=0;
    reg injected=0,abort_sent=0;
    reg [31:0] random_state=32'h17bc33e9;
    wire arready=!read_live && random_state[0];
    wire awready=!write_live && response_tail-response_head<16 && random_state[1];
    wire wready=write_live && (random_state[2] || random_state[3]);
    string jpeg_file,out_file;
    integer p,i,f,count;
    reg [31:0] status,elapsed,actual;
    reg [31:0] aw_count,b_wait,peak;

    jpeg_dma #(.WATCHDOG_CYCLES(6000000)) dut (
        .aclk(clk), .aresetn(resetn),
        .s_axi_awaddr(s_awaddr), .s_axi_awprot(3'b0), .s_axi_awvalid(s_awvalid), .s_axi_awready(s_awready),
        .s_axi_wdata(s_wdata), .s_axi_wstrb(4'hf), .s_axi_wvalid(s_wvalid), .s_axi_wready(s_wready),
        .s_axi_bresp(), .s_axi_bvalid(s_bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(s_araddr), .s_axi_arprot(3'b0), .s_axi_arvalid(s_arvalid), .s_axi_arready(s_arready),
        .s_axi_rdata(s_rdata), .s_axi_rresp(), .s_axi_rvalid(s_rvalid), .s_axi_rready(1'b1),
        .m_axi_araddr(araddr), .m_axi_arlen(arlen), .m_axi_arsize(arsize), .m_axi_arburst(arburst),
        .m_axi_arvalid(arvalid), .m_axi_arready(arready), .m_axi_rdata(rdata),
        .m_axi_rresp(rresp), .m_axi_rlast(rlast), .m_axi_rvalid(rvalid), .m_axi_rready(rready),
        .m_axi_awaddr(awaddr), .m_axi_awlen(awlen), .m_axi_awsize(awsize), .m_axi_awburst(awburst),
        .m_axi_awvalid(awvalid), .m_axi_awready(awready), .m_axi_wdata(wdata),
        .m_axi_wstrb(wstrb), .m_axi_wlast(wlast), .m_axi_wvalid(wvalid), .m_axi_wready(wready),
        .m_axi_bresp(bresp), .m_axi_bvalid(bvalid), .m_axi_bready(bready)
    );

    always @(posedge clk) begin
        cycle <= cycle+1;
        random_state <= {random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        if (cycle>12000000) $fatal(1,"test timeout state=%d/%d/%d",dut.entropy.state,dut.rd_state,dut.wr_state);
        if (arvalid && arready) begin
            if (arsize!=3 || arburst!=1 || araddr[2:0]!=0 || arlen>7 ||
                araddr[11:0]+(arlen+1)*8>4096 || araddr<SRC ||
                araddr+(arlen+1)*8>SRC+((src_length+7)&~7))
                $fatal(1,"invalid AXI read %h len=%d",araddr,arlen);
            rd_address <= araddr-SRC;
            rd_remaining <= arlen+1;
            read_live <= 1;
        end
        if (rvalid && rready) begin
            rvalid <= 0;
            if (rlast) read_live <= 0;
        end
        if (read_live && !rvalid && (random_state[4] || random_state[5])) begin
            for (integer j=0;j<8;j=j+1)
                rdata[j*8+:8] <= rd_address+j<src_length ? source[rd_address+j] : 8'hff;
            rd_address <= rd_address+8;
            rd_remaining <= rd_remaining-1;
            rlast <= rd_remaining==1;
            rvalid <= 1;
            rresp <= inject==3 && !injected ? 2'b10 : 2'b00;
            if (inject==3) injected <= 1;
        end
        if (awvalid && awready) begin
            if (awsize!=3 || awburst!=1 || awaddr[2:0]!=0 || awlen>3 ||
                awaddr[11:0]+(awlen+1)*8>4096 || awaddr<FB ||
                awaddr+(awlen+1)*8>FB+FB_BYTES)
                $fatal(1,"invalid AXI write %h len=%d",awaddr,awlen);
            wr_address <= awaddr-FB;
            wr_remaining <= awlen+1;
            write_live <= 1;
        end
        if (wvalid && wready) begin
            if (wlast!=(wr_remaining==1) || wstrb==0 || (^wstrb)===1'bx)
                $fatal(1,"invalid AXI write beat");
            for (integer j=0;j<8;j=j+1)
                if (wstrb[j]) begin
                    if ((wr_address+j)/2400<y || (wr_address+j)/2400>=y+height ||
                        (wr_address+j)%2400<x*3 || (wr_address+j)%2400>=(x+width)*3)
                        $fatal(1,"write outside ROI at %d",wr_address+j);
                    frame[wr_address+j] <= wdata[j*8+:8];
                end
            wr_address <= wr_address+8;
            wr_remaining <= wr_remaining-1;
            if (wlast) begin
                write_live <= 0;
                response_due[response_tail%16] <= cycle+b_latency+
                    (inject==6 && !abort_sent ? 35 : {30'b0,random_state[7:6]});
                response_tail <= response_tail+1;
                if (response_tail-response_head+1>peak_responses)
                    peak_responses <= response_tail-response_head+1;
            end
        end
        if (response_live && !bvalid && cycle>=response_due[response_head%16]) begin
            bvalid <= 1;
            bresp <= inject==4 && !injected ? 2'b10 : 2'b00;
            if (inject==4) injected <= 1;
        end
        if (bvalid && bready) begin
            bvalid <= 0;
            response_head <= response_head+1;
        end
    end

    task control_write(input [15:0] addr, input [31:0] value);
        begin
            @(negedge clk);
            s_wdata=value; s_wvalid=1;
            do @(posedge clk); while (!s_wready);
            @(negedge clk); s_wvalid=0;
            s_awaddr=addr; s_awvalid=1;
            do @(posedge clk); while (!s_awready);
            @(negedge clk); s_awvalid=0;
            do @(posedge clk); while (!s_bvalid);
        end
    endtask

    task control_read(input [15:0] addr, output [31:0] value);
        begin
            @(negedge clk);
            s_araddr=addr; s_arvalid=1;
            do @(posedge clk); while (!s_arready);
            @(negedge clk); s_arvalid=0;
            do @(posedge clk); while (!s_rvalid);
            value=s_rdata;
        end
    endtask

    task run_job(input integer fault);
        begin
            control_write(8,SRC);
            control_write(12,src_length);
            control_write(16,FB+(y*800+x)*3);
            control_write(20,(height<<16)|width);
            control_write(0,1);
            if (inject==6) begin
                wait(response_live);
                control_write(0,2);
                abort_sent=1;
            end
            do begin
                repeat (40) @(posedge clk);
                control_read(4,status);
            end while (status[0]);
            if (read_live || write_live || response_live || bvalid)
                $fatal(1,"busy cleared before AXI drained");
            control_read(24,elapsed);
            control_read(28,actual);
            control_read(32,aw_count);
            control_read(44,b_wait);
            control_read(56,peak);
            if (fault==0 && (status!==32'd2 || actual!==width*height) ||
                fault!=0 && status!==((fault<<8)|4))
                $fatal(1,"status=%h fault=%d pixels=%d cycles=%d parser=%d byte=%d",
                    status,fault,actual,elapsed,dut.entropy.state,src_length-dut.bytes_left);
            if (peak>write_window || peak_responses>write_window)
                $fatal(1,"AXI write window exceeded");
            if (fault==0 && write_window>1 && b_latency>=25 && aw_count>=64 && peak<2)
                $fatal(1,"Expected overlapping AXI writes");
            $display("RESULT status=%08x pixels=%0d cycles=%0d aw=%0d b_wait=%0d peak=%0d",
                status,actual,elapsed,aw_count,b_wait,peak);
        end
    endtask

    initial begin
        if (!$value$plusargs("input=%s",jpeg_file) || !$value$plusargs("output=%s",out_file) ||
            !$value$plusargs("width=%d",width) || !$value$plusargs("height=%d",height) ||
            !$value$plusargs("x=%d",x) || !$value$plusargs("y=%d",y) ||
            !$value$plusargs("fault=%d",expected_fault))
            $fatal(1,"missing arguments");
        if (!$value$plusargs("inject=%d",inject)) inject=0;
        if (!$value$plusargs("b_latency=%d",b_latency)) b_latency=0;
        if (!$value$plusargs("write_window=%d",write_window)) write_window=8;
        f=$fopen(jpeg_file,"rb");
        src_length=$fread(source,f);
        $fclose(f);
        if (src_length<4 || src_length>=524288) $fatal(1,"bad fixture length");
        for (i=0;i<FB_BYTES;i=i+1) frame[i]=SENTINEL;
        repeat (5) @(negedge clk);
        resetn=1;
        control_read(0,status);
        if (status!==32'h4a504701) $fatal(1,"invalid hardware ID");
        control_write(60,write_window);
        control_read(60,status);
        if (status!==write_window) $fatal(1,"write window configuration failed");
        if (inject!=0) begin
            run_job(inject);
            inject=0;
        end
        run_job(expected_fault);
        if (expected_fault==0) begin
            f=$fopen(out_file,"wb");
            count=0;
            for (i=0;i<FB_BYTES;i=i+1)
                if (i/2400>=y && i/2400<y+height && i%2400>=x*3 && i%2400<(x+width)*3) begin
                    if ((^frame[i])===1'bx) $fatal(1,"unknown pixel at %d",i);
                    $fwrite(f,"%c",frame[i]);
                    count=count+1;
                end else if (frame[i]!==SENTINEL) $fatal(1,"ROI clobbered %d",i);
            $fclose(f);
            if (count!=width*height*3) $fatal(1,"bad output length");
        end
        $finish;
    end
endmodule
