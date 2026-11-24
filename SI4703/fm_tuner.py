"""
I love slop coding :p

si4703.py - minimal MicroPython driver for the Silicon Labs Si4703 FM tuner (I2C).
 
Scope: tune a frequency, set volume, read RDS (PI, PTY, TP, station name, RadioText).
Defaults are European: 87.5-108 MHz, 100 kHz channel spacing, 50 us de-emphasis.
 
Example (RP2040 pins, adjust for your board):
 
    from machine import Pin, I2C
    import si4703
 
    si4703.hardware_reset(Pin(15), Pin(0))        # RST pin, SDA pin -> BEFORE creating I2C
    i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=100_000)
    radio = si4703.SI4703(i2c)
 
    radio.set_volume(5)                            # 0..15 (0 = mute)
    print(radio.tune(98.5))                        # returns actual frequency in MHz
    if radio.rds_wait(8000):                       # wait for full station name
        print(radio.pi, radio.ps, radio.radiotext)
 
    # Non-blocking alternative: call rds_poll() every ~40 ms from your main loop.
 
Wiring notes:
  * SEN must be tied high (2-wire mode); the module's I2C address is 0x10.
  * The chip needs a hardware reset with SDIO held low to select I2C mode, so call
    hardware_reset() before the I2C bus is created.
  * The headphone cable acts as the FM antenna on most breakout boards.
"""
import time
from machine import Pin
from micropython import const
 
# ---- Configuration values (these are the raw register bit patterns) ----
BAND_87_108 = const(0)    # 87.5-108 MHz  (Europe / USA)
BAND_76_108 = const(1)    # 76-108 MHz    (Japan wide)
BAND_76_90 = const(2)     # 76-90 MHz     (Japan)
 
SPACING_200K = const(0)   # USA / Australia
SPACING_100K = const(1)   # Europe / Japan
SPACING_50K = const(2)
 
DEEMPH_75US = const(0)    # USA
DEEMPH_50US = const(1)    # Europe
 
_ADDR = const(0x10)
 
# Register numbers
_DEVICEID = const(0x00)
_POWERCFG = const(0x02)
_CHANNEL = const(0x03)
_SYSCONFIG1 = const(0x04)
_SYSCONFIG2 = const(0x05)
_SYSCONFIG3 = const(0x06)
_TEST1 = const(0x07)
_STATUS = const(0x0A)
_READCHAN = const(0x0B)
_RDSA = const(0x0C)
_RDSB = const(0x0D)
_RDSC = const(0x0E)
_RDSD = const(0x0F)
 
# Bits
_DMUTE = const(0x4000)    # POWERCFG: 1 = mute disabled
_ENABLE = const(0x0001)   # POWERCFG
_TUNE = const(0x8000)     # CHANNEL
_RDS = const(0x1000)      # SYSCONFIG1: RDS enable
_RDSR = const(0x8000)     # STATUS: RDS group ready
_STC = const(0x4000)      # STATUS: seek/tune complete
 
_BAND_KHZ = ((87500, 108000), (76000, 108000), (76000, 90000))
_SPACING_KHZ = (200, 100, 50)
 
 
def hardware_reset(rst, sda):
    """Reset the chip into 2-wire (I2C) mode.
 
    rst, sda: machine.Pin objects for the RST and SDA lines.
    Call this BEFORE creating the I2C object.
    """
    sda.init(Pin.OUT, value=0)
    rst.init(Pin.OUT, value=0)
    time.sleep_ms(2)
    rst.value(1)
    time.sleep_ms(2)
    sda.init(Pin.IN)
 
 
class SI4703:
    def __init__(self, i2c, addr=_ADDR, band=BAND_87_108, spacing=SPACING_100K,
                 deemphasis=DEEMPH_50US, volume=1):
        self.i2c = i2c
        self.addr = addr
        self._r = [0] * 16          # shadow copy of all 16 registers
        self.max_bler = 1           # max block errors accepted for RDS (0..3)
 
        self.pi = 0
        self.pty = 0
        self.tp = False
        self._rds_reset()
 
        self._read()
        if (self._r[_DEVICEID] & 0x0FFF) != 0x242:
            raise OSError("Si4703 not found")
 
        # Start the crystal oscillator, then wait for it to settle
        self._r[_TEST1] = 0x8100
        self._write()
        time.sleep_ms(500)
 
        # Power up: unmute, enable, RDS on, region settings
        self._read()
        self._r[_POWERCFG] = _DMUTE | _ENABLE
        self._r[_SYSCONFIG1] = _RDS | ((deemphasis & 1) << 11)
        self._r[_SYSCONFIG2] = ((self._r[_SYSCONFIG2] & 0xFF00)
                                | ((band & 3) << 6) | ((spacing & 3) << 4)
                                | max(0, min(15, volume)))
        self._write()
        time.sleep_ms(110)          # max power-up time
 
    # ---------------- low level ----------------
    # The Si4703 has no register addressing: writes always start at reg 0x02
    # (0x02..0x07), reads always start at reg 0x0A and wrap (0x0A..0x0F, 0x00..0x09).
 
    def _read(self, n=32):
        d = self.i2c.readfrom(self.addr, n)
        r = self._r
        for i in range(n // 2):
            r[(_STATUS + i) & 0x0F] = (d[2 * i] << 8) | d[2 * i + 1]
 
    def _write(self):
        buf = bytearray(12)
        for i in range(6):
            v = self._r[_POWERCFG + i]
            buf[2 * i] = v >> 8
            buf[2 * i + 1] = v & 0xFF
        self.i2c.writeto(self.addr, buf)
 
    def _wait_stc(self, state, timeout_ms=2000):
        t0 = time.ticks_ms()
        while True:
            self._read(2)
            if bool(self._r[_STATUS] & _STC) == state:
                return
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise OSError("Si4703 tune timeout")
            time.sleep_ms(5)
 
    def _grid(self):
        band = (self._r[_SYSCONFIG2] >> 6) & 3
        space = (self._r[_SYSCONFIG2] >> 4) & 3
        lo, hi = _BAND_KHZ[band]
        return lo, hi, _SPACING_KHZ[space]
 
    # ---------------- region settings ----------------
    # After changing band or spacing, call tune() again.
 
    def set_band(self, band):
        if band not in (BAND_87_108, BAND_76_108, BAND_76_90):
            raise ValueError("invalid band")
        self._r[_SYSCONFIG2] = (self._r[_SYSCONFIG2] & 0xFF3F) | (band << 6)
        self._write()
 
    def set_spacing(self, spacing):
        if spacing not in (SPACING_200K, SPACING_100K, SPACING_50K):
            raise ValueError("invalid spacing")
        self._r[_SYSCONFIG2] = (self._r[_SYSCONFIG2] & 0xFFCF) | (spacing << 4)
        self._write()
 
    def set_deemphasis(self, deemphasis):
        if deemphasis not in (DEEMPH_75US, DEEMPH_50US):
            raise ValueError("invalid de-emphasis")
        self._r[_SYSCONFIG1] = (self._r[_SYSCONFIG1] & 0xF7FF) | (deemphasis << 11)
        self._write()
 
    # ---------------- tuning & volume ----------------
 
    def tune(self, mhz):
        """Tune to mhz (e.g. 98.5). Rounds to the nearest channel of the current
        band/spacing grid and returns the actual frequency in MHz."""
        khz = int(mhz * 1000 + 0.5)
        lo, hi, step = self._grid()
        if not lo <= khz <= hi:
            raise ValueError("frequency outside band")
        chan = (khz - lo + step // 2) // step
 
        self._r[_CHANNEL] = _TUNE | chan
        self._write()
        self._wait_stc(True)
        self._r[_CHANNEL] = chan            # clear TUNE
        self._write()
        self._wait_stc(False)
        self._rds_reset()
        return self.get_frequency()
 
    def get_frequency(self):
        """Currently tuned frequency in MHz."""
        self._read(4)
        lo, _, step = self._grid()
        return (lo + step * (self._r[_READCHAN] & 0x3FF)) / 1000
 
    def set_volume(self, volume):
        """Volume 0..15 (0 = mute)."""
        volume = max(0, min(15, int(volume)))
        self._r[_SYSCONFIG2] = (self._r[_SYSCONFIG2] & 0xFFF0) | volume
        self._write()
 
    def get_volume(self):
        return self._r[_SYSCONFIG2] & 0x0F
 
    def rssi(self):
        """Received signal strength, 0..75 dBuV."""
        self._read(2)
        return self._r[_STATUS] & 0xFF
 
    # ---------------- RDS ----------------
 
    def _rds_reset(self):
        self.pi = 0
        self.pty = 0
        self.tp = False
        self._ps = bytearray(b" " * 8)
        self._ps_mask = 0
        self._rt = bytearray(b" " * 64)
        self._rt_ab = None
 
    @staticmethod
    def _text(buf):
        return "".join(chr(c) if 32 <= c < 127 else " " for c in buf)
 
    @property
    def ps(self):
        """Programme Service name (8 chars, the station name)."""
        return self._text(self._ps)
 
    @property
    def radiotext(self):
        """RadioText (up to 64 chars)."""
        end = self._rt.find(b"\r")
        buf = self._rt if end < 0 else self._rt[:end]
        return self._text(buf).rstrip()
 
    @property
    def ps_complete(self):
        return self._ps_mask == 0x0F
 
    def rds_poll(self):
        """Read the RDS registers; decode a new group if one is ready.
        Call at least every ~40 ms. Returns True if a group was decoded."""
        self._read(12)
        r = self._r
        s = r[_STATUS]
        if not s & _RDSR:
            return False
 
        a, b, c, d = r[_RDSA], r[_RDSB], r[_RDSC], r[_RDSD]
        ea = (s >> 9) & 3
        eb = (r[_READCHAN] >> 14) & 3
        ec = (r[_READCHAN] >> 12) & 3
        ed = (r[_READCHAN] >> 10) & 3
        m = self.max_bler
 
        if eb > m:
            return False
        self.tp = bool(b & 0x0400)
        self.pty = (b >> 5) & 0x1F
        if ea <= m:
            self.pi = a
 
        group = b >> 12
        if group == 0 and ed <= m:                      # 0A/0B: station name
            seg = b & 3
            self._ps[2 * seg] = d >> 8
            self._ps[2 * seg + 1] = d & 0xFF
            self._ps_mask |= 1 << seg
        elif group == 2:                                # 2A/2B: RadioText
            version_b = b & 0x0800
            if ed > m or (not version_b and ec > m):
                return False
            ab = (b >> 4) & 1
            if ab != self._rt_ab:                       # text A/B flag toggled: new text
                self._rt_ab = ab
                self._rt = bytearray(b" " * 64)
            seg = b & 0x0F
            if version_b:
                i = seg * 2
                self._rt[i] = d >> 8
                self._rt[i + 1] = d & 0xFF
            else:
                i = seg * 4
                self._rt[i] = c >> 8
                self._rt[i + 1] = c & 0xFF
                self._rt[i + 2] = d >> 8
                self._rt[i + 3] = d & 0xFF
        return True
 
    def rds_wait(self, timeout_ms=8000):
        """Block until the full station name has been received (or timeout).
        Returns True on success. RadioText may need longer; keep calling rds_poll()."""
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            self.rds_poll()
            if self.ps_complete:
                return True
            time.sleep_ms(40)
        return False
 
