import time
from machine import ADC
from KY040/rotary_irq_rp2 import RotaryIRQ
from tm1637 import TM1637


def main():
    segment = TM1637Decimal(Pin(10),Pin(9))
    rotary = RotaryIRQ(pin_num_clk=16, pin_num_dt=15,min_val=0,max_val=205, reverse=False, range_mode=RotaryIRQ.RANGE_WRAP)
    potentiometer = ADC(31)
    keyboard = ADC(32)
    rot_init = rotary.value()
    pot_init = potentiometer.read_u16()
    key_init = keyboard.read_u16()
    freq = 87500 # frequency is in kHz, EU FM band 87.5 MHz - 108 MHz
    try:
        while True:
            #phase 1: process inputs by polling
            pot_new = potentiometer.read_u16()
            key_new = keyboard.read_u16()
            rot_new = rotary.value()
            if(rot_new != rot_init):
                rot_init = rot_new
                # calcualte frequency and tune fm module
                freq = 87500 + rot_init*100

            if(abs(pot_new - pot_init) > 100):
                pot_init = pot_new
                # change volume
            if(abs(key_new - key_init) > 100):
                key_init = key_new
                # itll do something
            #phase 2: send commands to fm tuner board
            #phase 3: update output devices
            segment.encode_string((string)freq/100)
            time.sleep_ms(50)
    except KeyboardInterrupt:
        print("\nProgram stopped. Exiting...")

if __name__ == "__main__":
    main()
