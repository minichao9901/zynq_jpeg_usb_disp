connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
puts [mrd -address-space AP0 -force 0x003c1700 32]
puts [mrd -address-space AP0 -force 0x41200000 2]
puts [mrd -address-space AP0 -force 0x43000000 12]
disconnect
exit
