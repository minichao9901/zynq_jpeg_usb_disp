connect -url tcp:127.0.0.1:3121
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
puts [rrd pc]
puts [mrd -force 0xF8000120 1]
disconnect
exit
