import argparse
import sys
from .core import calc_sum

def main():
    parser = argparse.ArgumentParser(description="Calculate the sum of two numbers.")
    parser.add_argument("a", type=float, help="First number")
    parser.add_argument("b", type=float, help="Second number")
    
    args = parser.parse_args()
    
    try:
        result = calc_sum(args.a, args.b)
        # Check if result is an integer (e.g., 3.0 -> 3) to print cleanly if possible
        if result.is_integer():
            print(int(result))
        else:
            print(result)
    except Exception as e:
        print(f"Error calculating sum: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
