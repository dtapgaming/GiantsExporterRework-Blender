    
    
import string
digs = string.digits + string.ascii_letters


def int2string_base(x,base):
    # global digs
    digits = []
    while x:
        digits.append(digs[int(x % base)])
        x = int(x / base)
    digits.reverse()
    return ''.join(digits)