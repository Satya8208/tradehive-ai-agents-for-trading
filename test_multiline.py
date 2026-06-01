"""
Quick test of the multi-line input logic
"""

print("Testing multi-line input collection...")
print("\n[Test] You (press ENTER twice when done):")

lines = []
while True:
    line = input()
    if line.strip() == "":
        break
    lines.append(line)

user_input = "\n".join(lines).strip()

print("\n" + "="*60)
print("COLLECTED INPUT:")
print("="*60)
print(user_input)
print("="*60)
print(f"\nTotal lines: {len(lines)}")
print("✅ Multi-line input works!")
