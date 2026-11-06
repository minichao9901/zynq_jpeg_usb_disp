# USB uses PS MIO only. The LCD PL logic is unchanged from 19_vdma_lcd.
# Export the PS USB configuration and reuse the provided, routed LCD bit.
set root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $root build fpga usb_display.xpr]
open_bd_design [get_files system.bd]
set_property -dict [list CONFIG.PCW_USB_RESET_ENABLE {1} CONFIG.PCW_USB_RESET_SELECT {Share reset pin} CONFIG.PCW_USB_RESET_POLARITY {Active Low} CONFIG.PCW_USB0_RESET_ENABLE {1} CONFIG.PCW_USB0_RESET_IO {MIO 8}] [get_bd_cells processing_system7_0]
set_property CONFIG.c_num_fstores {1} [get_bd_cells axi_vdma_0]
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
write_hwdef -force -file [file join $root prebuilt system.hdf]
# PL is unchanged; keep the versioned shared bitstream.
if {![file exists [file join $root prebuilt usb_display.bit]]} {error "Missing shared prebuilt LCD bitstream"}
exit
