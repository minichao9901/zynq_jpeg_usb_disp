# Extend the LCD design without changing the VDMA or its DDR port.
delete_bd_objs [get_bd_cells axi_dynclk_0]
set clkgen [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 lcd_clock]
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {33.000} \
    CONFIG.USE_RESET {false} CONFIG.USE_LOCKED {true}] $clkgen
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins lcd_clock/clk_in1]
connect_bd_net [get_bd_pins lcd_clock/clk_out1] [get_bd_pins rgb2lcd_0/pixel_clk] \
    [get_bd_pins v_axi4s_vid_out_0/vid_io_out_clk] [get_bd_pins v_tc_0/clk]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 lcd_reset
connect_bd_net [get_bd_pins lcd_clock/clk_out1] [get_bd_pins lcd_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins lcd_clock/locked] [get_bd_pins lcd_reset/dcm_locked]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins lcd_reset/ext_reset_in]
connect_bd_net [get_bd_pins lcd_reset/peripheral_reset] [get_bd_pins v_axi4s_vid_out_0/vid_io_out_reset]

create_bd_cell -type module -reference jpeg_dma jpeg_dma_0
set_property CONFIG.PCW_USE_S_AXI_HP1 {1} [get_bd_cells processing_system7_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 jpeg_axi
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M02_AXI] [get_bd_intf_pins jpeg_dma_0/S_AXI]
connect_bd_intf_net [get_bd_intf_pins jpeg_dma_0/M_AXI] [get_bd_intf_pins jpeg_axi/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins jpeg_axi/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP1]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins jpeg_dma_0/aclk] \
    [get_bd_pins jpeg_axi/aclk] [get_bd_pins processing_system7_0/S_AXI_HP1_ACLK]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins jpeg_dma_0/aresetn] \
    [get_bd_pins jpeg_axi/aresetn]
set ctrl [lindex [get_bd_addr_segs -of_objects [get_bd_intf_pins jpeg_dma_0/S_AXI]] 0]
assign_bd_address -offset 0x43C10000 -range 64K $ctrl
assign_bd_address -offset 0 -range 1G -target_address_space [get_bd_addr_spaces jpeg_dma_0/M_AXI] \
    [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]
