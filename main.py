import time
from machine import ADC
from KY040/rotary_irq_rp2 import RotaryIRQ


def main():
    rotary = RotaryIRQ(pin_num_clk=16, pin_num_dt=15,min_val=0,max_val=205, reverse=False, range_mode=RotaryIRQ.RANGE_WRAP)
    potentiometer = ADC(31)
    keyboard = ADC(32)
    rot_init = rotary.value()
    pot_init = potentiometer.read_u16()
    key_init = keyboard.read_u16()
    try:
        while True:
            pot_new = potentiometer.read_u16()
            key_new = keyboard.read_u16()
            rot_new = rotary.value()
            if(rot_new != rot_init):
                rot_init = rot_new
                print("rot_value: " rot_new)
            if(abs(pot_new - pot_init) > 100):
                pot_init = pot_new
                print("pot_value: ", pot_new)
            if(abs(key_new - key_init) > 100):
                key_init = key_new
                print("key_value: ", key_new)
            time.sleep_ms(50)
    except KeyboardInterrupt:
        print("\nProgram stopped. Exiting...")

if __name__ == "__main__":
    main()