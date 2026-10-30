"""Synthetic peripheral bridge tests; no proprietary ROM bytes."""
import ctypes as C
import unittest
from gpce4_soc_test import Core

class HostTests(unittest.TestCase):
    def setUp(self):
        self.c=Core();self.c.reset();self.e=self.c.lib
        self.cpu=(C.c_uint32*24).from_address(self.e.gp_cpu_ptr())
    def entry(self,pc):
        self.cpu[0]=0xff0;self.cpu[6]=pc>>16;self.cpu[7]=pc&65535
        self.c.ram[0xff1]=0;self.c.ram[0xff2]=0x4000
    def test_cable_native_setup_tx_rx_and_wait_boundary(self):
        c,e=self.c,self.e
        e.gp_link_enable(1);self.entry(0x2084e9);e.gp_run(1)
        self.assertEqual((c.ram[0xca0],c.ram[0xccc]),(1,1))
        for n in range(8):c.ram[0xce0+n]=n+7
        self.entry(0x208926);e.gp_run(100)
        self.assertEqual(e.gp_link_status(),1)
        e.gp_link_tx_ptr.restype=C.c_void_p
        self.assertEqual(list((C.c_uint16*8).from_address(e.gp_link_tx_ptr())),list(range(7,15)))
        self.assertEqual(e.gp_link_tx_take(),1)
        c.ram[0xc9c]=15;c.ram[0xc9e]=3;c.ram[0x86b]=0x11
        self.entry(0x2005e9);self.assertEqual(e.gp_run(100),0)
        self.assertEqual(e.gp_link_status(),2)
        e.gp_link_rx_ptr.restype=C.c_void_p
        inbox=(C.c_uint16*8).from_address(e.gp_link_rx_ptr())
        for n in range(8):inbox[n]=n+17
        self.assertEqual(e.gp_link_receive(),1)
        self.assertEqual(e.gp_link_receive(),0)
        # A synthetic retf at the same firmware entry lets us examine delivery.
        c.flash[2*0x5e9]=0x90;c.flash[2*0x5e9+1]=0x9a
        e.gp_run(1)
        self.assertEqual(c.ram[0xccc],6)
        self.assertEqual(list(c.ram[0xcce:0xcd6]),list(range(17,25)))
    def test_custody_call_preserves_suspended_cpu_and_stack(self):
        c,e=self.c,self.e
        # r1=7; retf at the whitelisted bedtime entry, synthetic firmware.
        at=2*(0x210e61-0x200000)
        c.flash[at:at+4]=bytes([0x47,0x92,0x90,0x9a])
        before=bytes(self.cpu);stack=bytes(c.ram[0x1d00:0x1f01])
        e.gp_custody_call.restype=C.c_int32
        self.assertEqual(e.gp_custody_call(0x210e61,0,100),7)
        self.assertEqual(bytes(self.cpu),before)
        self.assertEqual(bytes(c.ram[0x1d00:0x1f01]),stack)
        self.assertLess(e.gp_custody_call(0x210e62,0,100),0)

if __name__=='__main__':unittest.main()
