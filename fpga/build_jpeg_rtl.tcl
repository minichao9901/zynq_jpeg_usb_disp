# Vivado 2018.3. Build and export a matched PL hardware handoff.
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file join $root build fpga-jpeg-rtl]
file mkdir $out
create_project usb_display $out -part xc7z020clg400-2 -force
set_param general.maxThreads 2
set_property ip_repo_paths [list [file join $root fpga ip_repo]] [current_project]
update_ip_catalog
add_files [glob -directory [file join $root fpga jpeg] *.v]
add_files [glob -directory [file join $root fpga jpeg core] *.v]
source [file join $root fpga bd lcd_system.tcl]
set_property -dict [list CONFIG.PCW_USB0_PERIPHERAL_ENABLE {1} CONFIG.PCW_USB0_USB0_IO {MIO 28 .. 39} CONFIG.PCW_USB_RESET_ENABLE {1} CONFIG.PCW_USB_RESET_SELECT {Share reset pin} CONFIG.PCW_USB_RESET_POLARITY {Active Low} CONFIG.PCW_USB0_RESET_ENABLE {1} CONFIG.PCW_USB0_RESET_IO {MIO 8}] [get_bd_cells processing_system7_0]
source [file join $root fpga bd jpeg_rtl.tcl]
validate_bd_design
save_bd_design
set bd [get_files system.bd]
set_property synth_checkpoint_mode None $bd
generate_target all $bd
add_files [make_wrapper -files $bd -top]
add_files -fileset constrs_1 [file join $root fpga constraints lcd.xdc]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_hwdef -force -file [file join $out next_system.hdf]
synth_design -top system_wrapper -part xc7z020clg400-2
write_checkpoint -force [file join $out synthesized.dcp]
opt_design
place_design
phys_opt_design
route_design
set routed [file join $out routed.dcp]
write_checkpoint -force $routed
proc timing_met {} {
    set setup [get_property SLACK [lindex [get_timing_paths -max_paths 1] 0]]
    set hold [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
    return [expr {$setup >= 0 && $hold >= 0}]
}
if {![timing_met]} {
    # Try physical optimization with actual routed delays before rejecting the design.
    close_design
    set_param general.maxThreads 4
    open_checkpoint $routed
    phys_opt_design -directive AggressiveExplore
    write_checkpoint -force $routed
}
report_timing_summary -check_timing_verbose -file [file join $out timing_summary.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_drc -file [file join $out drc.rpt]
if {![timing_met]} {
    error "JPEG RTL design did not meet timing; see timing_summary.rpt"
}
write_bitstream -force [file join $out next_usb_display.bit]
file rename -force [file join $out next_system.hdf] [file join $out system.hdf]
file rename -force [file join $out next_usb_display.bit] [file join $out usb_display.bit]
exit
