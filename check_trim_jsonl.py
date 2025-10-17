from pathlib import Path

p = Path("data/questions.jsonl")
lines = p.read_text(encoding="utf-8").splitlines()

bad = []
cleaned = []
for i, line in enumerate(lines, 1):
    if line.strip() == "":
        bad.append(i)
        continue
    if line != line.strip():
        print(f"⚠️ 行 {i}: 前後に空白あり → トリム")
    cleaned.append(line.strip())

if bad:
    print(f"🚫 空白のみ行: {bad}")
else:
    print("✅ 空白のみ行なし")

# 上書き保存（トリム済み）
p.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
print("🧹 修正・整形完了:", p)
