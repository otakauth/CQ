from pathlib import Path

file_path = Path("data/questions.jsonl")

fixed_lines = []
for line in file_path.read_text(encoding="utf-8").splitlines():
    stripped = line.rstrip()
    # 行末が "}," の場合は末尾カンマを削除
    if stripped.endswith("},"):
        stripped = stripped[:-1]
    fixed_lines.append(stripped)

# 修正版を上書き保存
file_path.write_text("\n".join(fixed_lines) + "\n", encoding="utf-8")

print("✅ 行末カンマを削除しました:", file_path)
