# JTAG/RAM only. Never writes QSPI or other nonvolatile storage.
set root [file normalize [file join [file dirname [info script]] ..]]
set bit [file join $root prebuilt jpeg usb_display.bit]
set elf [file join $root prebuilt jpeg usb_display.elf]
set init [file join $root prebuilt jpeg ps7_init.tcl]
if {[llength $argv] == 3} {
    lassign $argv elf bit init
    set elf [file normalize $elf]
    set bit [file normalize $bit]
    set init [file normalize $init]
} elseif {[llength $argv] == 1} {
    set bit [file normalize [lindex $argv 0]]
} elseif {[llength $argv] != 0} {error "Expected ELF BIT PS_INIT_TCL, or no arguments for JPEG"}
foreach f [list $bit $elf $init] {
    if {![file exists $f]} {error "Missing artifact $f"}
}
connect -url tcp:127.0.0.1:3121
puts "LOAD_BIT=$bit LOAD_ELF=$elf"
puts [targets]
if {[catch {targets -set -filter {name =~ "APU"}}]} {
    # After unplugging board power, hw_server can retain a faulted DAP.
    targets -set -filter {name =~ "DAP*"}
    rst -system
    after 1000
    targets -set -filter {name =~ "APU"}
}
rst -system
after 1000
source $init
ps7_init
ps7_post_config
targets -set -filter {name =~ "xc7z020"}
fpga -f $bit
targets -set -filter {name =~ "ARM*#1"}
catch {stop}
targets -set -filter {name =~ "ARM*#0"}
rst -processor
dow $elf
con
after 2000
targets -set -filter {name =~ "ARM*#1"}
catch {stop}
targets -set -filter {name =~ "ARM*#0"}
puts "PC=[rrd pc]"
disconnect
exit
