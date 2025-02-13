from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.cachehierarchies.ruby.mesi_three_level_cache_hierarchy import (MESIThreeLevelCacheHierarchy,)
from gem5.components.cachehierarchies.classic.private_l1_shared_l2_cache_hierarchy import PrivateL1SharedL2CacheHierarchy
from gem5.components.processors.simple_switchable_processor import SimpleSwitchableProcessor
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.coherence_protocol import CoherenceProtocol
from gem5.isas import ISA
from gem5.components.processors.cpu_types import CPUTypes
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.simulate.exit_event import ExitEvent
from gem5.resources.resource import BinaryResource, DiskImageResource, KernelResource
import sys
sys.path.append("configs")
import argparse

from ruby import Ruby

parser = argparse.ArgumentParser()
# SimpleSSD options
parser.add_argument("--ssd-interface", action="store", type=str,
                    default="nvme",
                    help="Interface to use to connect SimpleSSD.")
parser.add_argument("--ssd-config", action="store", type=str,
                    default=None,
                    help="Path to SimpleSSD configuration file.")
parser.add_argument("--disable-ide", action="store_true",
                    help="Disable default IDE controller.")
# Add the ruby specific and protocol specific args
if "--ruby" in sys.argv:
    Ruby.define_options(parser)

args = parser.parse_args()

simplessd = {
    'interface': args.ssd_interface,
    'config': args.ssd_config,
    'disable_ide': args.disable_ide
}

# This runs a check to ensure the gem5 binary is compiled to X86 and supports
# the MESI Two Level coherence protocol.
requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_THREE_LEVEL,
    kvm_required=True,
)

"""
# Here we setup a MESI Two Level Cache Hierarchy.
cache_hierarchy = MESIThreeLevelCacheHierarchy(
    l1d_size="32KiB",
    l1d_assoc=8,
    l1i_size="32KiB",
    l1i_assoc=8,
    l2_size="256KiB",
    l2_assoc=16,
    l3_size="4MiB",
    l3_assoc=32,
    num_l3_banks=1,
)
"""

cache_hierarchy = PrivateL1SharedL2CacheHierarchy(
    l1d_size="32KiB",
    l1i_size="32KiB",
    l2_size="256KiB"
)
# Setup the system memory.
# Note, by default DDR3_1600 defaults to a size of 8GiB. However, a current
# limitation with the X86 board is it can only accept memory systems up to 3GB.
# As such, we must fix the size.
memory = SingleChannelDDR3_1600("3GiB")

# Here we setup the processor. This is a special switchable processor in which
# a starting core type and a switch core type must be specified. Once a
# configuration is instantiated a user may call `processor.switch()` to switch
# from the starting core types to the switch core types. In this simulation
# we start with KVM cores to simulate the OS boot, then switch to the Timing
# cores for the command we wish to run after boot.

processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.KVM,
    switch_core_type=CPUTypes.TIMING,
    num_cores=4,
    isa=ISA.X86,
)

# Here we setup the board. The X86Board allows for Full-System X86 simulations.
board = X86Board(
    simplessd=simplessd,
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

# This is the command to run after the system has booted. The first `m5 exit`
# will stop the simulation so we can switch the CPU cores from KVM to timing
# and continue the simulation to run the echo command, sleep for a second,
# then, again, call `m5 exit` to terminate the simulation. After simulation
# has ended you may inspect `m5out/system.pc.com_1.device` to see the echo
# output.

command = "cat /sys/bus/pci/devices/0000:00:04.0/vendor;" \
        + "cat /sys/bus/pci/devices/0000:00:04.0/device;" \
        + "cat /sys/bus/pci/devices/0000:00:05.0/vendor;" \
        + "cat /sys/bus/pci/devices/0000:00:05.0/device;" \
        + "echo 144d 2001 > /sys/bus/pci/drivers/nvme/new_id;" \
        + "ls -l /sys/bus/pci/devices/0000:00:05.0/driver;" \
        + "cat /sys/bus/pci/devices/0000:00:05.0/power_state;" \
        + "cat /sys/bus/pci/devices/0000:00:05.0/resource;" \
        + "cat /proc/ioports;" \
        + "echo 'Finished KVM';" \
        + "m5 exit;" \
        + "sleep 1;" \
        + "echo 'Finished Timing CPU Execution.';" \
        + "m5 exit;"

# Here we set the Full System workload.
# The `set_workload` function for the X86Board takes a kernel, a disk image,
# and, optionally, a the contents of the "readfile". In the case of the
# "x86-ubuntu-18.04-img", a file to be executed as a script after booting the
# system.

board.set_kernel_disk_workload(
    kernel=KernelResource(local_path="/home/vijays2/research/thesis/fs_sim/binaries/x86_64-vmlinux-4.9.92"),
    disk_image=DiskImageResource(local_path="/home/vijays2/research/thesis/fs_sim/disks/x86root.img"),
    readfile_contents=command,
    kernel_args=["earlyprintk=ttyS0", "console=ttyS0", "root=/dev/sda1", "lpj=7999923", "acpi=off", "noibrs", "noibpb", "nopti", "nospectre_v2", "nospectre_v1", "l1tf=off", "nospec_store_bypass_disable", "no_stf_barrier", "mds=off", "mitigations=off"]
)

simulator = Simulator(
    board=board,
    on_exit_event={
        # Here we want override the default behavior for the first m5 exit
        # exit event. Instead of exiting the simulator, we just want to
        # switch the processor. The 2nd 'm5 exit' after will revert to using
        # default behavior where the simulator run will exit.
        ExitEvent.EXIT : (func() for func in [processor.switch]),
    },
)

simulator.run()
