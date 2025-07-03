# Copyright (c) 2021 The Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


from typing import (
    List,
    Sequence,
)

from m5.objects import (
    Addr,
    AddrRange,
    BaseXBar,
    Bridge,
    CowDiskImage,
    IdeDisk,
    IOXBar,
    Pc,
    Port,
    RawDiskImage,
    X86ACPIMadt,
    X86ACPIMadtIntSourceOverride,
    X86ACPIMadtIOAPIC,
    X86ACPIMadtLAPIC,
    X86E820Entry,
    X86FsLinux,
    X86IntelMPBus,
    X86IntelMPBusHierarchy,
    X86IntelMPIOAPIC,
    X86IntelMPIOIntAssignment,
    X86IntelMPProcessor,
    X86SMBiosBiosInformation,
    X86MSIHandler,
)
from m5.util.convert import toMemorySize
from m5.params import *
from ...components.boards.se_binary_workload import SEBinaryWorkload
from ...isas import ISA
from ...resources.resource import AbstractResource
from ...utils.override import overrides
from ..cachehierarchies.abstract_cache_hierarchy import AbstractCacheHierarchy
from ..memory.abstract_memory_system import AbstractMemorySystem
from ..processors.abstract_processor import AbstractProcessor
from .abstract_system_board import AbstractSystemBoard
from .kernel_disk_workload import KernelDiskWorkload


class X86Board(AbstractSystemBoard, KernelDiskWorkload, SEBinaryWorkload):
    """
    A board capable of full system simulation for X86.

    **Limitations**
    * Currently, this board's memory is hardcoded to 3GiB.
    * Much of the I/O subsystem is hard coded.
    """
    
    def __init__(
        self,
        simplessd: dict,
        clk_freq: str,
        processor: AbstractProcessor,
        memory: AbstractMemorySystem,
        cache_hierarchy: AbstractCacheHierarchy,
    ) -> None:
        super().__init__(
            clk_freq=clk_freq,
            processor=processor,
            memory=memory,
            cache_hierarchy=cache_hierarchy,
        )
        if self.get_processor().get_isa() != ISA.X86:
            raise Exception(
                "The X86Board requires a processor using the X86 "
                f"ISA. Current processor ISA: '{processor.get_isa().name}'."
            )
        self.simplessd_config = simplessd['config']
        self.simplessd_disable_ide = simplessd['disable_ide']
        self.simplessd_interface = simplessd['interface']
        
    @overrides(AbstractSystemBoard)
    def _setup_board(self) -> None:
        if self.is_fullsystem():
            self.pc = Pc()
            
            self.msi_handler = X86MSIHandler()
            
            self.workload = X86FsLinux()

            # North Bridge
            self.iobus = IOXBar()

            # Set up all of the I/O.
            self._setup_io_devices()

            self.m5ops_base = 0xFFFF0000
            
    def _setup_io_devices(self):
        """Sets up the x86 IO devices.
        .. note::

            This is mostly copy-paste from prior X86 FS setups. Some of it
            may not be documented and there may be bugs.
        """
        
        #if self.simplessd_disable_ide:
        #    delattr(self.pc.south_bridge, 'ide')
        #else:
        #    Disks
        #    disks = makeCowDisks(mdesc.disks())
        #    self.pc.south_bridge.ide.disks = disks
        if self.simplessd_interface == 'nvme':
            self.pc.nvme.SSDConfig = self.simplessd_config
            self.pc.nvme.InterruptLine = 17
            self.pc.nvme.InterruptPin = 1
        elif self.simplessd_interface == 'ocssd':
            self.pc.nvme.SSDConfig = self.simplessd_config
            self.pc.nvme.VendorID = 0x1D1D
            self.pc.nvme.DeviceID = 0x1F1F
            self.pc.nvme.InterruptLine = 17
            self.pc.nvme.InterruptPin = 1
        elif self.simple_ssd_interface == 'sata':
            self.pc.south_bridge.sata.SSDConfig = self.simplessd_config
            self.pc.south_bridge.sata.InterruptLine = 18
            self.pc.south_bridge.sata.InterruptPin = 1
        else:
            fatal(
                "Undefined SimpleSSD interface {}!".format(self.simplessd_interface))

        # Setup memory system specific settings.
        if self.get_cache_hierarchy().is_ruby():
            print("using ruby")
            self.pc.attachIO(self.get_io_bus(), [self.pc.south_bridge.ide.dma])
        else:
            print("setting up config space manually")
            self.msi_handler.pio = ( 
                self.get_cache_hierarchy().get_mem_side_port()
            )
            self.bridge = Bridge(delay="50ns")
            self.bridge.mem_side_port = self.get_io_bus().cpu_side_ports
            self.bridge.cpu_side_port = (
                self.get_cache_hierarchy().get_mem_side_port()
            )

            # # Constants similar to x86_traits.hh
            IO_address_space_base = 0x8000000000000000
            pci_config_address_space_base = 0xC000000000000000
            interrupts_address_space_base = 0xA000000000000000
            APIC_range_size = 1 << 12

            self.bridge.ranges = [
                AddrRange(0xC0000000, 0xFEE00000 - 1),
                AddrRange(0xFEF00000, 0xFFFF0000),
                AddrRange(
                    IO_address_space_base, interrupts_address_space_base - 1
                ),
                AddrRange(pci_config_address_space_base, Addr.max),
            ]
            
            self.apicbridge = Bridge(delay="50ns")
            self.apicbridge.cpu_side_port = self.get_io_bus().mem_side_ports
            self.apicbridge.mem_side_port = (
                self.get_cache_hierarchy().get_cpu_side_port()
            )
            self.apicbridge.ranges = [
                AddrRange(0xFEE00000, 0xFEF00000 - 1),
                AddrRange(
                    interrupts_address_space_base,
                    interrupts_address_space_base
                    + self.get_processor().get_num_cores() * APIC_range_size
                    - 1,
                )
            ]
            self.pc.attachIO(self.get_io_bus())

        # Add in a Bios information structure.
        self.workload.smbios_table.structures = [X86SMBiosBiosInformation()]

        # Set up the Intel MP table
        base_entries = []
        ext_entries = []
        # Updated the X86 board with MADT entries.
        madt_entries = []
        
        for i in range(self.get_processor().get_num_cores()):
            bp = X86IntelMPProcessor(
                local_apic_id=i,
                local_apic_version=0x14,
                enable=True,
                bootstrap=(i == 0),
            )
            base_entries.append(bp)
            lapic = X86ACPIMadtLAPIC(acpi_processor_id=i, apic_id=i, flags=1)
            madt_entries.append(lapic)
        
        
        io_apic = X86IntelMPIOAPIC(
            id=self.get_processor().get_num_cores(),
            version=0x11,
            enable=True,
            address=0xFEC00000,
        )

        self.pc.south_bridge.io_apic.apic_id = io_apic.id
        base_entries.append(io_apic)
        madt_entries.append(
            X86ACPIMadtIOAPIC(
                id=io_apic.id, address=io_apic.address, int_base=0
            )
        )

        pci_bus = X86IntelMPBus(bus_id=0, bus_type="PCI   ")
        base_entries.append(pci_bus)
        isa_bus = X86IntelMPBus(bus_id=1, bus_type="ISA   ")
        base_entries.append(isa_bus)
        connect_busses = X86IntelMPBusHierarchy(
            bus_id=1, subtractive_decode=True, parent_bus=0
        )
        ext_entries.append(connect_busses)

        pci_dev4_inta = X86IntelMPIOIntAssignment(
            interrupt_type="INT",
            polarity="ConformPolarity",
            trigger="ConformTrigger",
            source_bus_id=0,
            source_bus_irq=0 + (4 << 2),
            dest_io_apic_id=io_apic.id,
            dest_io_apic_intin=16,
        )

        pci_dev5_inta = X86IntelMPIOIntAssignment(
            interrupt_type = 'INT',
            polarity = 'ConformPolarity',
            trigger = 'ConformTrigger',
            source_bus_id = 0,
            source_bus_irq = 0 + (5 << 2),
            dest_io_apic_id = io_apic.id,
            dest_io_apic_intin = 17)
        
        pci_dev6_inta = X86IntelMPIOIntAssignment(
                interrupt_type = 'INT',
                polarity = 'ConformPolarity',
                trigger = 'ConformTrigger',
                source_bus_id = 0,
                source_bus_irq = 0 + (6 << 2),
                dest_io_apic_id = io_apic.id,
                dest_io_apic_intin = 18)
        
        base_entries.append(pci_dev4_inta)
        base_entries.append(pci_dev5_inta)
        base_entries.append(pci_dev6_inta)
        
        pci_dev4_inta_madt = X86ACPIMadtIntSourceOverride(
            bus_source=pci_dev4_inta.source_bus_id,
            irq_source=pci_dev4_inta.source_bus_irq,
            sys_int=pci_dev4_inta.dest_io_apic_intin,
            flags=0,
        )
        
        pci_dev5_inta_madt = X86ACPIMadtIntSourceOverride(
            bus_source=pci_dev5_inta.source_bus_id,
            irq_source=pci_dev5_inta.source_bus_irq,
            sys_int=pci_dev5_inta.dest_io_apic_intin,
            flags=0,
        )
        
        pci_dev6_inta_madt = X86ACPIMadtIntSourceOverride(
            bus_source=pci_dev6_inta.source_bus_id,
            irq_source=pci_dev6_inta.source_bus_irq,
            sys_int=pci_dev6_inta.dest_io_apic_intin,
            flags=0,
        )
        
        madt_entries.append(pci_dev4_inta_madt)
        madt_entries.append(pci_dev5_inta_madt)
        madt_entries.append(pci_dev6_inta_madt)
        
        def assignISAInt(irq, apicPin):
            assign_8259_to_apic = X86IntelMPIOIntAssignment(
                interrupt_type="ExtInt",
                polarity="ConformPolarity",
                trigger="ConformTrigger",
                source_bus_id=1,
                source_bus_irq=irq,
                dest_io_apic_id=io_apic.id,
                dest_io_apic_intin=0,
            )
            base_entries.append(assign_8259_to_apic)

            assign_to_apic = X86IntelMPIOIntAssignment(
                interrupt_type="INT",
                polarity="ConformPolarity",
                trigger="ConformTrigger",
                source_bus_id=1,
                source_bus_irq=irq,
                dest_io_apic_id=io_apic.id,
                dest_io_apic_intin=apicPin,
            )
            base_entries.append(assign_to_apic)
            # acpi
            assign_to_apic_acpi = X86ACPIMadtIntSourceOverride(
                bus_source=1, irq_source=irq, sys_int=apicPin, flags=0
            )
            madt_entries.append(assign_to_apic_acpi)

        assignISAInt(0, 2)
        assignISAInt(1, 1)

        for i in range(3, 15):
            assignISAInt(i, i)

        self.workload.intel_mp_table.base_entries = base_entries
        self.workload.intel_mp_table.ext_entries = ext_entries

        madt = X86ACPIMadt(
            local_apic_address=0, records=madt_entries, oem_id="madt"
        )
        # self.workload.acpi_description_table_pointer.rsdt.entries.append(madt)
        self.workload.acpi_description_table_pointer.xsdt.entries.append(madt)
        self.workload.acpi_description_table_pointer.oem_id = "gem5"
        # self.workload.acpi_description_table_pointer.rsdt.oem_id = "gem5"
        self.workload.acpi_description_table_pointer.xsdt.oem_id = "gem5"
        entries = [
            # Mark the first megabyte of memory as reserved
            X86E820Entry(addr=0, size="639KiB", range_type=1),
            X86E820Entry(addr=0x9FC00, size="385KiB", range_type=2),
            # Mark the rest of physical memory as available
            X86E820Entry(
                addr=0x100000,
                size=f"{self.mem_ranges[0].size() - 0x100000:d}B",
                range_type=1,
            ),
        ]
        
        # mark the range from the top of physical memory to 0xC0000000 as reserved to force PCI devices to be mapped to the correct range
        entries.append(X86E820Entry(addr = self.mem_ranges[0].size(),
            size='%dB' % (0xC0000000 - self.mem_ranges[0].size()),
            range_type=2))
        
        # Reserve the last 64KiB of the 32-bit address space for m5ops
        entries.append(
            X86E820Entry(addr=0xFFFF0000, size="64KiB", range_type=2)
        )

        self.workload.e820_table.entries = entries
        
        lapics = []
        for core in self.get_processor().get_cores():
            core.core.createInterruptController()
            core.core.connectUncachedPorts((self.get_cache_hierarchy().get_cpu_side_port()), (self.get_cache_hierarchy().get_mem_side_port()))
            lapics.extend(core.core.interrupts)
        self.msi_handler.lapics = lapics 

    @overrides(AbstractSystemBoard)
    def has_io_bus(self) -> bool:
        return self.is_fullsystem()

    @overrides(AbstractSystemBoard)
    def get_io_bus(self) -> IOXBar:
        if self.has_io_bus():
            return self.iobus
        else:
            raise Exception(
                "Cannot execute `get_io_bus()`: Board does not have an I/O "
                "bus to return. Use `has_io_bus()` to check this."
            )

    @overrides(AbstractSystemBoard)
    def has_dma_ports(self) -> bool:
        return self.is_fullsystem()

    @overrides(AbstractSystemBoard)
    def get_dma_ports(self) -> Sequence[Port]:
        if self.has_dma_ports():
            return [self.pc.south_bridge.ide.dma, self.iobus.mem_side_ports]
        else:
            raise Exception(
                "Cannot execute `get_dma_ports()`: Board does not have DMA "
                "ports to return. Use `has_dma_ports()` to check this."
            )

    @overrides(AbstractSystemBoard)
    def has_coherent_io(self) -> bool:
        return self.is_fullsystem()

    @overrides(AbstractSystemBoard)
    def get_mem_side_coherent_io_port(self) -> Port:
        if self.has_coherent_io():
            return self.iobus.mem_side_ports
        else:
            raise Exception(
                "Cannot execute `get_mem_side_coherent_io_port()`: Board does "
                "not have I/O ports to return. Use `has_coherent_io()` to "
                "check this."
            )

    @overrides(AbstractSystemBoard)
    def _setup_memory_ranges(self):
        memory = self.get_memory()

        if memory.get_size() > toMemorySize("3GiB"):
            raise Exception(
                "X86Board currently only supports memory sizes up "
                "to 3GiB because of the I/O hole."
            )
        data_range = AddrRange(memory.get_size())
        memory.set_memory_range([data_range])

        # Add the address range for the IO
        self.mem_ranges = [
            data_range,  # All data
            AddrRange(0xC0000000, size=0x100000),  # For I/0
        ]

    @overrides(KernelDiskWorkload)
    def get_disk_device(self):
        return "/dev/hda"

    @overrides(KernelDiskWorkload)
    def _add_disk_to_board(self, disk_image: AbstractResource):
        ide_disk = IdeDisk()
        ide_disk.driveID = "device0"
        ide_disk.image = CowDiskImage(
            child=RawDiskImage(read_only=True), read_only=False
        )
        ide_disk.image.child.image_file = disk_image.get_local_path()

        # Attach the SimObject to the system.
        self.pc.south_bridge.ide.disks = [ide_disk]

    @overrides(KernelDiskWorkload)
    def get_default_kernel_args(self) -> List[str]:
        return [
            "earlyprintk=ttyS0",
            "console=ttyS0",
            "lpj=7999923",
            "root={root_value}",
            "disk_device={disk_device}",
        ]
