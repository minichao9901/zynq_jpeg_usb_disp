set root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $root build fpga usb_display.xpr]
set_param general.maxThreads 2
foreach run [get_runs] {
    if {[get_property IS_SYNTHESIS $run]} {
        set_property STEPS.SYNTH_DESIGN.TCL.PRE [file join $root fpga run_threads.tcl] $run
        if {[string match "*dynclk*" $run] || [string match "*vdma*" $run]} {
            set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none $run
        }
    }
}
foreach run [get_runs *_synth_1] {
    set status [get_property STATUS $run]
    puts "$run: $status"
    if {![string match "*Complete*" $status]} {reset_run $run}
}
reset_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed: [get_property STATUS [get_runs impl_1]]"}
open_run impl_1
report_timing_summary -file [file join $root prebuilt timing_summary.rpt]
report_drc -file [file join $root prebuilt drc.rpt]
file copy -force [file join $root build fpga usb_display.runs impl_1 system_wrapper.bit] [file join $root prebuilt usb_display.bit]
exit
