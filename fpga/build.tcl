# Vivado 2018.3. Recreate the LCD design from the compact source inputs.
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file join $root build fpga]
create_project usb_display $out -part xc7z020clg400-2 -force
set_param general.maxThreads 2
set_property ip_repo_paths [list [file join $root fpga ip_repo]] [current_project]
update_ip_catalog
source [file join $root fpga bd lcd_system.tcl]
set_property -dict [list CONFIG.PCW_USB0_PERIPHERAL_ENABLE {1} CONFIG.PCW_USB0_USB0_IO {MIO 28 .. 39} CONFIG.PCW_USB_RESET_ENABLE {1} CONFIG.PCW_USB_RESET_SELECT {Share reset pin} CONFIG.PCW_USB_RESET_POLARITY {Active Low} CONFIG.PCW_USB0_RESET_ENABLE {1} CONFIG.PCW_USB0_RESET_IO {MIO 8}] [get_bd_cells processing_system7_0]
set_property CONFIG.c_num_fstores {1} [get_bd_cells axi_vdma_0]
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
make_wrapper -files [get_files system.bd] -top
add_files [file join $out usb_display.srcs sources_1 bd system hdl system_wrapper.v]
add_files -fileset constrs_1 [file join $root fpga constraints lcd.xdc]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_hwdef -force -file [file join $out system.hdf]
if {[lsearch -exact $argv --rebuild-pl] < 0} {
    # USB is entirely in PS MIO. Preserve the known LCD PL implementation.
    if {![file exists [file join $root prebuilt usb_display.bit]]} {error "Missing shared prebuilt LCD bitstream"}
    exit
}
foreach run [get_runs] {
    if {[get_property IS_SYNTHESIS $run]} {
        set_property STEPS.SYNTH_DESIGN.TCL.PRE [file join $root fpga run_threads.tcl] $run
    }
}
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
file copy -force [file join $out usb_display.runs impl_1 system_wrapper.bit] [file join $out usb_display.bit]
exit
